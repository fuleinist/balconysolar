"""Settle the PVGIS aspect convention for the southern hemisphere."""

import json
import urllib.parse
import urllib.request


def query(lat, lon, tilt, aspect):
    params = {
        "lat": lat, "lon": lon, "peakpower": 0.4, "loss": 14,
        "angle": tilt, "aspect": aspect, "outputformat": "json",
    }
    url = "https://re.jrc.ec.europa.eu/api/v5_2/PVcalc?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": "diag/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload["outputs"]["totals"]["fixed"].get("E_y")


def main():
    print("Southern hemisphere, Sydney (-33.87), tilt 30")
    for aspect in (0, 180, -180, -90, 90):
        print(f"  aspect {aspect:5d} -> {query(-33.87, 151.21, 30, aspect)}")

    print("\nNorthern hemisphere control, Paris (48.85), tilt 30")
    for aspect in (0, 180, -90, 90):
        print(f"  aspect {aspect:5d} -> {query(48.85, 2.35, 30, aspect)}")


if __name__ == "__main__":
    main()