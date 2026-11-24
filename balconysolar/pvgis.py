"""Optional PVGIS reference yield.

PVGIS v5.2 returns a monthly and annual yield for a fixed geometry. The call
is used only as a cross-check. It never blocks the estimate.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

PVGIS_URL = "https://re.jrc.ec.europa.eu/api/v5_2/PVcalc"
TIMEOUT = 25


def reference_yield(
    lat: float,
    lon: float,
    peak_power_kw: float,
    tilt: float,
    azimuth: float,
    loss: float = 14.0,
) -> dict | None:
    """Return PVGIS annual and monthly yield, or ``None`` on any failure."""
    params = {
        "lat": f"{lat:.4f}",
        "lon": f"{lon:.4f}",
        "peakpower": f"{max(0.05, peak_power_kw):.3f}",
        "loss": f"{loss:.1f}",
        "angle": f"{tilt:.1f}",
        "aspect": f"{_pvgis_aspect(azimuth):.1f}",
        "outputformat": "json",
    }
    url = PVGIS_URL + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": "balconysolar/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, OSError, json.JSONDecodeError):
        return None

    try:
        totals = payload["outputs"]["totals"]["fixed"]
        monthly = payload["outputs"]["monthly"]["fixed"]
    except (KeyError, TypeError):
        return None

    return {
        "annual_kwh": totals.get("E_y"),
        "monthly_kwh": [item.get("E_m") for item in monthly],
        "irradiance_kwh_m2": totals.get("H_y"),
        "source": "PVGIS v5.2 PVcalc",
    }


def _pvgis_aspect(surface_azimuth: float) -> float:
    """PVGIS uses 0 for south, -90 for east and 90 for west."""
    return ((surface_azimuth - 180.0 + 180.0) % 360.0) - 180.0


def compare(model_kwh: float, reference: dict | None) -> dict | None:
    """Return a comparison block for the API response."""
    if not reference or not reference.get("annual_kwh"):
        return None
    reference_kwh = float(reference["annual_kwh"])
    delta = (model_kwh - reference_kwh) / reference_kwh * 100.0
    return {
        "reference_kwh": round(reference_kwh, 1),
        "delta_percent": round(delta, 1),
        "monthly_kwh": reference.get("monthly_kwh"),
        "source": reference.get("source"),
    }