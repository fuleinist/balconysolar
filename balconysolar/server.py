"""HTTP server for balconysolar.

The stack is the Python standard library. FastAPI is not used because the
installed FastAPI and Starlette versions conflict on this machine.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import db, model, pvgis, solar, weather

ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(ROOT, "static")
MAX_BODY = 256 * 1024

STORE = None


def _static_path(name: str) -> str | None:
    safe = os.path.normpath(name).replace("\\", "/")
    if safe.startswith("..") or os.path.isabs(safe):
        return None
    path = os.path.join(STATIC_DIR, safe)
    if not os.path.isfile(path):
        return None
    return path


def build_inputs(payload: dict) -> tuple[model.Inputs, dict]:
    """Turn a JSON request into model inputs plus a normalised echo."""
    location = payload.get("location") or {}
    lat = float(location.get("lat", -33.8688))
    lon = float(location.get("lon", 151.2093))
    if not (-90.0 <= lat <= 90.0):
        raise ValueError("latitude must be between -90 and 90")
    if not (-180.0 <= lon <= 180.0):
        raise ValueError("longitude must be between -180 and 180")

    balcony = payload.get("balcony") or {}
    tilt = float(balcony.get("tilt", 90.0))
    surface_azimuth = float(balcony.get("azimuth", 0.0)) % 360.0
    floor_level = int(balcony.get("floor_level", 3))
    rail_height = float(balcony.get("rail_height_m", 1.1))

    panel_data = payload.get("panel") or {}
    panel = model.Panel(
        wp=float(panel_data.get("wp", 400)),
        area_m2=float(panel_data.get("area_m2", 1.95)),
        efficiency=float(panel_data.get("efficiency", 0.205)),
        temp_coeff=float(panel_data.get("temp_coeff", -0.0035)),
        noct=float(panel_data.get("noct", 45)),
    )
    if panel.wp <= 0 or panel.wp > 5000:
        raise ValueError("panel peak power must be between 1 and 5000 W")

    inverter_data = payload.get("inverter") or {}
    inverter = model.Inverter(
        limit_w=float(inverter_data.get("limit_w", panel.wp)),
        efficiency=float(inverter_data.get("efficiency", 0.96)),
    )

    obstructions = []
    for item in payload.get("obstructions") or []:
        obstructions.append(
            solar.Obstruction(
                azimuth=float(item.get("azimuth", 0.0)) % 360.0,
                elevation=float(item.get("elevation", 0.0)),
                width=float(item.get("width", 30.0)),
            )
        )

    load = payload.get("load") or {}
    tariff = payload.get("tariff") or {}

    inputs = model.Inputs(
        lat=lat,
        lon=lon,
        tilt=max(0.0, min(90.0, tilt)),
        surface_azimuth=surface_azimuth,
        floor_level=max(0, floor_level),
        rail_height_m=rail_height,
        panel=panel,
        inverter=inverter,
        obstructions=obstructions,
        daily_kwh=max(0.5, min(60.0, float(load.get("daily_kwh", 8.0)))),
        import_tariff=max(0.0, float(tariff.get("import_aud_kwh", 0.32))),
        export_tariff=max(0.0, float(tariff.get("export_aud_kwh", 0.05))),
        export_allowed=bool(tariff.get("export_allowed", True)),
        capex=max(0.0, float(payload.get("capex_aud", model.DEFAULT_CAPEX))),
        albedo=max(0.0, min(0.9, float(payload.get("albedo", 0.2)))),
    )

    echo = {
        "location": {"lat": lat, "lon": lon, "label": location.get("label", "")},
        "balcony": {
            "tilt": inputs.tilt,
            "azimuth": inputs.surface_azimuth,
            "floor_level": inputs.floor_level,
            "rail_height_m": inputs.rail_height_m,
        },
        "panel": panel.__dict__,
        "inverter": inverter.__dict__,
        "obstructions": [item.__dict__ for item in obstructions],
        "load": {"daily_kwh": inputs.daily_kwh},
        "tariff": {
            "import_aud_kwh": inputs.import_tariff,
            "export_aud_kwh": inputs.export_tariff,
            "export_allowed": inputs.export_allowed,
        },
        "capex_aud": inputs.capex,
    }
    return inputs, echo


def run_estimate(payload: dict, offline: bool = False) -> dict:
    inputs, echo = build_inputs(payload)
    year = weather.load_year(inputs.lat, inputs.lon, STORE, offline=offline)
    result = model.estimate(inputs, year["rows"], year["source"])

    reference = None
    if not offline and payload.get("check_pvgis"):
        reference = pvgis.reference_yield(
            inputs.lat,
            inputs.lon,
            inputs.panel.wp / 1000.0,
            inputs.tilt,
            inputs.surface_azimuth,
        )

    result["inputs"] = echo
    result["weather"] = {
        "source": year["source"],
        "cell": year["cell"],
        "period": year["period"],
        "label": result["data_source"],
    }
    result["pvgis"] = pvgis.compare(result["annual_kwh"], reference) if reference else None
    result["assumptions"] = assumptions(inputs, year)
    return result


def assumptions(inputs: model.Inputs, year: dict) -> list[str]:
    items = [
        f"Weather cell {year['cell']['lat']:.2f}, {year['cell']['lon']:.2f} over {year['period'][0]} to {year['period'][1]}.",
        f"Panel tilt {inputs.tilt:.0f} degrees, surface azimuth {inputs.surface_azimuth:.0f} degrees from north.",
        f"System loss {model.SYSTEM_LOSS * 100:.0f} percent for soiling, mismatch and wiring.",
        f"Load shape assumes {inputs.daily_kwh:.1f} kWh per day with an evening peak.",
        f"Inverter limit {inputs.inverter.limit_w:.0f} W at {inputs.inverter.efficiency * 100:.0f} percent efficiency.",
    ]
    if not inputs.export_allowed:
        items.append("Export is disabled, so surplus energy is spilled.")
    if inputs.obstructions:
        items.append(
            f"{len(inputs.obstructions)} obstruction edge(s) from the horizon editor."
        )
    if year["source"] != "archive":
        items.append("Weather is modelled clear-sky data, not an archive. Treat the result as an estimate.")
    return items


class Handler(BaseHTTPRequestHandler):
    server_version = "balconysolar/1.0"

    # ---- helpers ---------------------------------------------------------
    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _error(self, status: int, message: str) -> None:
        self._json(status, {"error": message})

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > MAX_BODY:
            raise ValueError("request body is too large")
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def log_message(self, fmt: str, *args) -> None:
        if os.environ.get("BALCONYSOLAR_QUIET") != "1":
            super().log_message(fmt, *args)

    # ---- routes ----------------------------------------------------------
    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path in ("/", "/index.html"):
            return self._serve_static("index.html")
        if path.startswith("/static/"):
            return self._serve_static(path[len("/static/"):])
        if path == "/api/health":
            return self._json(
                HTTPStatus.OK,
                {"ok": True, "service": "balconysolar", "panels": len(model.PANELS)},
            )
        if path == "/api/panels":
            return self._json(
                HTTPStatus.OK,
                {"panels": model.PANELS, "inverters": model.INVERTERS, "defaults": {"capex_aud": model.DEFAULT_CAPEX}},
            )
        if path == "/api/scenarios":
            return self._json(HTTPStatus.OK, {"scenarios": STORE.list_scenarios()})
        if path.startswith("/api/scenarios/"):
            scenario = STORE.get_scenario(path.rsplit("/", 1)[-1])
            if not scenario:
                return self._error(HTTPStatus.NOT_FOUND, "scenario not found")
            return self._json(HTTPStatus.OK, scenario)
        if path.startswith("/brief/"):
            return self._serve_brief(path.rsplit("/", 1)[-1])
        if path == "/api/pvgis":
            return self._pvgis_check(query)
        if path == "/api/geocode":
            return self._geocode(query)

        return self._error(HTTPStatus.NOT_FOUND, "not found")

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        try:
            payload = self._body()
        except (ValueError, json.JSONDecodeError) as exc:
            return self._error(HTTPStatus.BAD_REQUEST, str(exc))

        if path == "/api/estimate":
            try:
                result = run_estimate(payload, offline=payload.get("offline", False))
            except ValueError as exc:
                return self._error(HTTPStatus.BAD_REQUEST, str(exc))
            return self._json(HTTPStatus.OK, result)

        if path == "/api/scenarios":
            try:
                result = run_estimate(payload)
            except ValueError as exc:
                return self._error(HTTPStatus.BAD_REQUEST, str(exc))
            scenario_id = STORE.save_scenario(
                str(payload.get("label") or _default_label(payload)), payload, result
            )
            return self._json(HTTPStatus.CREATED, {"id": scenario_id, "result": result})

        return self._error(HTTPStatus.NOT_FOUND, "not found")

    def do_DELETE(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith("/api/scenarios/"):
            scenario_id = parsed.path.rsplit("/", 1)[-1]
            if STORE.delete_scenario(scenario_id):
                return self._json(HTTPStatus.OK, {"deleted": scenario_id})
            return self._error(HTTPStatus.NOT_FOUND, "scenario not found")
        return self._error(HTTPStatus.NOT_FOUND, "not found")

    # ---- handlers --------------------------------------------------------
    def _serve_static(self, name: str) -> None:
        path = _static_path(name)
        if not path:
            return self._error(HTTPStatus.NOT_FOUND, "file not found")
        content_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
        with open(path, "rb") as handle:
            body = handle.read()
        self._send(HTTPStatus.OK, body, content_type)

    def _serve_brief(self, scenario_id: str) -> None:
        scenario = STORE.get_scenario(scenario_id)
        if not scenario:
            return self._error(HTTPStatus.NOT_FOUND, "scenario not found")
        html = render_brief(scenario)
        self._send(HTTPStatus.OK, html.encode("utf-8"), "text/html; charset=utf-8")

    def _pvgis_check(self, query: dict) -> None:
        try:
            lat = float(query.get("lat", ["-33.8688"])[0])
            lon = float(query.get("lon", ["151.2093"])[0])
            tilt = float(query.get("tilt", ["90"])[0])
            azimuth = float(query.get("azimuth", ["0"])[0])
            kw = float(query.get("peakpower", ["0.4"])[0])
        except ValueError:
            return self._error(HTTPStatus.BAD_REQUEST, "bad numeric parameter")
        reference = pvgis.reference_yield(lat, lon, kw, tilt, azimuth)
        if not reference:
            return self._json(HTTPStatus.OK, {"available": False})
        return self._json(HTTPStatus.OK, {"available": True, "reference": reference})

    def _geocode(self, query: dict) -> None:
        term = (query.get("q") or [""])[0].strip()
        if not term:
            return self._error(HTTPStatus.BAD_REQUEST, "query is empty")
        url = (
            "https://geocoding-api.open-meteo.com/v1/search?"
            + urllib.parse.urlencode({"name": term, "count": 5, "language": "en", "format": "json"})
        )
        try:
            import urllib.request

            request = urllib.request.Request(url, headers={"User-Agent": "balconysolar/1.0"})
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception:
            return self._json(HTTPStatus.OK, {"results": []})
        results = [
            {
                "name": item.get("name"),
                "admin": item.get("admin1"),
                "country": item.get("country_code"),
                "lat": item.get("latitude"),
                "lon": item.get("longitude"),
            }
            for item in (payload.get("results") or [])
        ]
        return self._json(HTTPStatus.OK, {"results": results})


def _default_label(payload: dict) -> str:
    location = payload.get("location") or {}
    label = location.get("label") or "Balcony"
    panel = payload.get("panel") or {}
    return f"{label} {panel.get('wp', 400):.0f} W"


def _fmt(value, suffix: str = "") -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:,.1f}{suffix}"
    if isinstance(value, int):
        return f"{value:,}{suffix}"
    return f"{value}{suffix}"


def render_brief(scenario: dict) -> str:
    """Render the printable A4 brief."""
    result = scenario["result"]
    inputs = result.get("inputs", {})
    payload = scenario["payload"] or {}
    panel = inputs.get("panel", {})
    balcony = inputs.get("balcony", {})
    tariff = inputs.get("tariff", {})
    monthly = result.get("monthly", [])
    peak = max([item["kwh"] for item in monthly] or [1.0]) or 1.0

    bars = []
    names = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"]
    for item in monthly:
        height = max(2.0, item["kwh"] / peak * 92.0)
        bars.append(
            f'<div class="bar"><span class="bar-value">{item["kwh"]:.0f}</span>'
            f'<div class="bar-fill" style="height:{height:.1f}%"></div>'
            f'<span class="bar-label">{names[item["month"] - 1]}</span></div>'
        )

    payback = result.get("payback_years")
    payback_range = result.get("payback_range") or [None, None]
    payback_text = (
        f"{payback:.1f} years (range {_fmt(payback_range[0])} to {_fmt(payback_range[1])})"
        if payback
        else "No payback at these tariffs"
    )

    losses = result.get("losses", {})
    assumptions_list = "".join(f"<li>{item}</li>" for item in result.get("assumptions", []))
    obstructions = inputs.get("obstructions") or []
    obstruction_text = (
        ", ".join(f"{item['azimuth']:.0f} deg at {item['elevation']:.0f} deg" for item in obstructions)
        if obstructions
        else "None recorded"
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Balcony solar brief — {scenario['label']}</title>
<style>
  @page {{ size: A4; margin: 16mm; }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: "Segoe UI", Arial, sans-serif; color: #1d2320; margin: 0; background: #fff; }}
  .sheet {{ max-width: 178mm; margin: 0 auto; padding: 8mm 0; }}
  header {{ display: flex; justify-content: space-between; align-items: flex-start; border-bottom: 3px solid #1d2320; padding-bottom: 10px; }}
  h1 {{ font-size: 26px; margin: 0 0 4px; letter-spacing: -0.5px; }}
  .sub {{ color: #5b6660; font-size: 13px; margin: 0; }}
  .stamp {{ text-align: right; font-size: 11px; color: #5b6660; }}
  .grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin: 18px 0; }}
  .card {{ border: 1px solid #d8ded9; border-radius: 8px; padding: 12px; }}
  .card .k {{ font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; color: #6a756f; }}
  .card .v {{ font-size: 24px; font-weight: 700; margin-top: 4px; }}
  .card .u {{ font-size: 12px; color: #5b6660; }}
  h2 {{ font-size: 14px; text-transform: uppercase; letter-spacing: 0.09em; margin: 22px 0 10px; }}
  .chart {{ display: flex; align-items: flex-end; gap: 6px; height: 130px; border-bottom: 1px solid #c9d1cc; padding-bottom: 2px; }}
  .bar {{ flex: 1; display: flex; flex-direction: column; justify-content: flex-end; align-items: center; height: 100%; }}
  .bar-fill {{ width: 70%; background: linear-gradient(180deg, #f2b134, #e08b1f); border-radius: 3px 3px 0 0; }}
  .bar-label {{ font-size: 10px; color: #6a756f; margin-top: 4px; }}
  .bar-value {{ font-size: 9px; color: #6a756f; margin-bottom: 3px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th, td {{ text-align: left; padding: 7px 6px; border-bottom: 1px solid #e4e9e5; }}
  th {{ font-weight: 600; color: #4a554f; }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .notes {{ font-size: 12px; color: #4a554f; line-height: 1.5; }}
  .notes li {{ margin-bottom: 4px; }}
  .checklist {{ font-size: 12.5px; }}
  .checklist li {{ margin-bottom: 6px; list-style: none; }}
  .checklist li::before {{ content: "\\2610"; margin-right: 8px; color: #e08b1f; }}
  footer {{ margin-top: 24px; border-top: 1px solid #d8ded9; padding-top: 8px; font-size: 10.5px; color: #7a857f; }}
</style>
</head>
<body>
<div class="sheet">
  <header>
    <div>
      <h1>Balcony solar brief</h1>
      <p class="sub">{scenario['label']} · {balcony.get('azimuth', 0):.0f} deg orientation · {balcony.get('tilt', 90):.0f} deg tilt</p>
    </div>
    <div class="stamp">
      {scenario['created_at'][:10]}<br />
      Ref {scenario['id']}
    </div>
  </header>

  <div class="grid">
    <div class="card">
      <div class="k">Annual yield</div>
      <div class="v">{_fmt(result.get('annual_kwh'))}</div>
      <div class="u">kWh per year</div>
    </div>
    <div class="card">
      <div class="k">Bill savings</div>
      <div class="v">A${_fmt(result.get('savings_aud'))}</div>
      <div class="u">{result.get('self_consumption_ratio', 0) * 100:.0f}% used at home</div>
    </div>
    <div class="card">
      <div class="k">Payback</div>
      <div class="v">{payback:.1f}</div>
      <div class="u">years, range {_fmt(payback_range[0])} to {_fmt(payback_range[1])}</div>
    </div>
  </div>

  <h2>Monthly yield (kWh)</h2>
  <div class="chart">{''.join(bars)}</div>

  <h2>System</h2>
  <table>
    <tr><th>Panel</th><td class="num">{panel.get('wp', 400):.0f} W, {panel.get('area_m2', 0):.2f} m2</td></tr>
    <tr><th>Inverter limit</th><td class="num">{inputs.get('inverter', {}).get('limit_w', 0):.0f} W</td></tr>
    <tr><th>Specific yield</th><td class="num">{_fmt(result.get('specific_yield'))} kWh/kWp</td></tr>
    <tr><th>Irradiance on the panel</th><td class="num">{_fmt(result.get('irradiance', {}).get('poa_kwh_m2'))} kWh/m2</td></tr>
    <tr><th>Self-consumed</th><td class="num">{_fmt(result.get('self_consumed_kwh'))} kWh</td></tr>
    <tr><th>Exported</th><td class="num">{_fmt(result.get('exported_kwh'))} kWh</td></tr>
    <tr><th>Curtailed</th><td class="num">{_fmt(result.get('curtailed_kwh'))} kWh</td></tr>
    <tr><th>Tariffs</th><td class="num">A${tariff.get('import_aud_kwh', 0):.2f} import, A${tariff.get('export_aud_kwh', 0):.2f} feed-in</td></tr>
    <tr><th>Capital cost</th><td class="num">A${_fmt(result.get('capex_aud'))}</td></tr>
    <tr><th>Shading loss</th><td class="num">{_fmt(losses.get('shading_kwh'))} kWh</td></tr>
    <tr><th>Temperature loss</th><td class="num">{_fmt(losses.get('temperature_kwh'))} kWh</td></tr>
    <tr><th>Clipping loss</th><td class="num">{_fmt(losses.get('clipping_kwh'))} kWh</td></tr>
  </table>

  <h2>Assumptions</h2>
  <ul class="notes">{assumptions_list}</ul>
  <p class="notes"><strong>Obstructions:</strong> {obstruction_text}</p>

  <h2>Landlord and strata checklist</h2>
  <ul class="checklist">
    <li>Ask the owner in writing. Keep the reply.</li>
    <li>Check the strata by-law for fixtures on common property.</li>
    <li>Confirm the balcony rail can carry the panel and wind load.</li>
    <li>Use a licensed electrician for any fixed wiring.</li>
    <li>Confirm the inverter is on the Clean Energy Council approved list.</li>
    <li>Ask the network about export limits before you buy an export meter.</li>
    <li>Keep the panel clear of the fire egress path.</li>
  </ul>

  <footer>
    Sources: {result.get('data_source', '')}. PVGIS reference is optional and shown in the app.
    This brief is an estimate for planning only. It is not electrical advice.
  </footer>
</div>
</body>
</html>"""


def create_server(host: str = "127.0.0.1", port: int = 8770, db_path: str = "data/balconysolar.db") -> ThreadingHTTPServer:
    global STORE
    STORE = db.Store(db_path)
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="balconysolar server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8770)
    parser.add_argument("--db", default="data/balconysolar.db")
    args = parser.parse_args(argv)

    server = create_server(args.host, args.port, args.db)
    print(f"balconysolar running at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if STORE:
            STORE.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())