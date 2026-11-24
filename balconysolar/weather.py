"""Weather data for the solar model.

The primary source is the Open-Meteo Archive API. It gives hourly global,
direct and diffuse irradiance with no key. Results are cached in SQLite.

When the network is down the module builds a clear-sky year from a small
monthly clearness table. The caller always sees which source was used.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import urllib.error
import urllib.parse
import urllib.request

from . import solar

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
CACHE_DAYS = 30
REQUEST_TIMEOUT = 45

# Monthly clearness index by latitude band. These are conservative means for
# temperate and subtropical Australia. They only drive the offline fallback.
CLEARNESS_TABLE = {
    -45: [0.52, 0.50, 0.47, 0.42, 0.37, 0.34, 0.35, 0.40, 0.45, 0.48, 0.50, 0.52],
    -40: [0.55, 0.53, 0.48, 0.43, 0.38, 0.35, 0.36, 0.42, 0.47, 0.51, 0.54, 0.56],
    -35: [0.56, 0.54, 0.50, 0.46, 0.42, 0.40, 0.42, 0.47, 0.51, 0.54, 0.55, 0.57],
    -30: [0.57, 0.55, 0.52, 0.49, 0.46, 0.45, 0.47, 0.51, 0.55, 0.57, 0.57, 0.58],
    -25: [0.58, 0.57, 0.55, 0.53, 0.51, 0.51, 0.53, 0.56, 0.58, 0.59, 0.58, 0.59],
    -20: [0.59, 0.58, 0.57, 0.56, 0.55, 0.55, 0.57, 0.59, 0.60, 0.60, 0.59, 0.60],
    0: [0.52, 0.52, 0.51, 0.50, 0.49, 0.48, 0.48, 0.49, 0.50, 0.51, 0.52, 0.52],
}


def _clearness_for(lat: float) -> list[float]:
    keys = sorted(CLEARNESS_TABLE)
    if lat <= keys[0]:
        return CLEARNESS_TABLE[keys[0]]
    if lat >= keys[-1]:
        return CLEARNESS_TABLE[keys[-1]]
    for low, high in zip(keys, keys[1:]):
        if low <= lat <= high:
            weight = (lat - low) / (high - low)
            return [
                CLEARNESS_TABLE[low][i]
                + (CLEARNESS_TABLE[high][i] - CLEARNESS_TABLE[low][i]) * weight
                for i in range(12)
            ]
    return CLEARNESS_TABLE[0]


def _hour_row(ts: dt.datetime, ghi: float, dni: float, dhi: float, temp: float) -> list:
    doy = ts.timetuple().tm_yday
    hour = ts.hour + ts.minute / 60.0
    return [doy, hour, float(ghi), float(dni), float(dhi), float(temp)]


def synthetic_year(lat: float, lon: float = 0.0) -> list[list]:
    """Build a clear-sky year that follows the seasonal clearness table.

    Hours are UTC, so the longitude must match the model location. Otherwise
    solar noon lands in the wrong hour and the beam misses the panel.
    """
    clearness = _clearness_for(lat)
    rows: list[list] = []
    start = dt.datetime(2025, 1, 1)
    for index in range(365 * 24):
        ts = start + dt.timedelta(hours=index)
        doy = ts.timetuple().tm_yday
        elevation, _ = solar.solar_position(lat, lon, doy, ts.hour + 0.5)
        ghi = solar.clear_sky_ghi(elevation) * clearness[ts.month - 1]
        dni = solar.clear_sky_dni(elevation) * clearness[ts.month - 1]
        dhi = max(0.0, ghi - dni * max(0.0, math.cos(math.radians(90.0 - elevation))))
        # A simple seasonal air temperature for the cell temperature model.
        seasonal = -5.0 * math.cos(2.0 * math.pi * (doy - 15) / 365.0)
        temp = 22.0 + seasonal * (abs(lat) / 35.0) + 6.0 * math.sin(
            math.pi * (ts.hour - 6) / 12.0
        )
        rows.append(_hour_row(ts, ghi, dni, dhi, temp))
    return rows


def fetch_archive(lat: float, lon: float, start: dt.date, end: dt.date) -> list[list]:
    """Fetch hourly irradiance and temperature from the Open-Meteo Archive."""
    params = {
        "latitude": f"{lat:.4f}",
        "longitude": f"{lon:.4f}",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "hourly": "shortwave_radiation,direct_normal_irradiance,diffuse_radiation,temperature_2m",
        "timezone": "UTC",
    }
    url = ARCHIVE_URL + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": "balconysolar/1.0"})
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        payload = json.loads(response.read().decode("utf-8"))

    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    ghi_values = hourly.get("shortwave_radiation") or []
    dni_values = hourly.get("direct_normal_irradiance") or []
    dhi_values = hourly.get("diffuse_radiation") or []
    temp_values = hourly.get("temperature_2m") or []

    rows: list[list] = []
    for index, stamp in enumerate(times):
        ts = dt.datetime.fromisoformat(stamp)
        ghi = ghi_values[index] if index < len(ghi_values) else 0.0
        dni = dni_values[index] if index < len(dni_values) else 0.0
        dhi = dhi_values[index] if index < len(dhi_values) else 0.0
        temp = temp_values[index] if index < len(temp_values) else 20.0
        rows.append(
            _hour_row(
                ts,
                ghi or 0.0,
                dni or 0.0,
                dhi or 0.0,
                20.0 if temp is None else temp,
            )
        )
    if len(rows) < 24 * 300:
        raise ValueError(f"archive returned only {len(rows)} hours")
    return rows


def default_window(today: dt.date | None = None) -> tuple[dt.date, dt.date]:
    """Return the last full year that the archive should hold."""
    today = today or dt.date.today()
    end = today - dt.timedelta(days=7)
    start = end - dt.timedelta(days=365)
    return start, end


def cache_key(lat: float, lon: float, start: dt.date, end: dt.date) -> str:
    return f"archive:{lat:.2f}:{lon:.2f}:{start.isoformat()}:{end.isoformat()}"


def load_year(
    lat: float,
    lon: float,
    store=None,
    force: bool = False,
    offline: bool = False,
) -> dict:
    """Return hourly rows plus a source label.

    The result is ``{"rows": [...], "source": "archive"|"modelled", "cell": {...}}``.
    """
    start, end = default_window()
    key = cache_key(lat, lon, start, end)

    if store is not None and not force:
        cached = store.get_cache(key, max_age_days=CACHE_DAYS)
        if cached:
            payload = json.loads(cached)
            return {
                "rows": payload["rows"],
                "source": payload.get("source", "archive"),
                "cell": payload.get("cell", {"lat": lat, "lon": lon}),
                "period": payload.get("period", [start.isoformat(), end.isoformat()]),
            }

    if not offline:
        try:
            rows = fetch_archive(lat, lon, start, end)
            result = {
                "rows": rows,
                "source": "archive",
                "cell": {"lat": round(lat, 2), "lon": round(lon, 2)},
                "period": [start.isoformat(), end.isoformat()],
            }
            if store is not None:
                store.set_cache(key, json.dumps(result))
            return result
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError, OSError, json.JSONDecodeError):
            pass

    rows = synthetic_year(lat, lon)
    return {
        "rows": rows,
        "source": "modelled",
        "cell": {"lat": round(lat, 2), "lon": round(lon, 2)},
        "period": ["clear-sky year", "clear-sky year"],
    }