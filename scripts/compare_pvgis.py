"""Local check: compare the model with the PVGIS reference for several tilts."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from balconysolar import model, pvgis, weather

CASES = [
    ("north vertical", 90, 0),
    ("east vertical", 90, 90),
    ("west vertical", 90, 270),
    ("south vertical", 90, 180),
    ("north 20 deg", 20, 0),
    ("north 45 deg", 45, 0),
]

LAT, LON = -33.87, 151.21


def main() -> int:
    with_pvgis = weather.load_year(LAT, LON, None, offline=False)
    print("source:", with_pvgis["source"], "rows:", len(with_pvgis["rows"]))
    print()
    header = f"{'case':16s} {'tilt':>4s} {'az':>4s} {'model':>8s} {'poa':>8s} {'ghi':>8s} {'pvgis':>8s} {'delta':>7s}"
    print(header)
    print("-" * len(header))
    for name, tilt, azimuth in CASES:
        inputs = model.Inputs(lat=LAT, lon=LON, tilt=tilt, surface_azimuth=azimuth)
        result = model.estimate(inputs, with_pvgis["rows"], with_pvgis["source"])
        reference = pvgis.reference_yield(LAT, LON, 0.4, tilt, azimuth)
        ref_kwh = reference["annual_kwh"] if reference else None
        delta = None
        if ref_kwh:
            delta = (result["annual_kwh"] - ref_kwh) / ref_kwh * 100.0
        print(
            f"{name:16s} {tilt:4d} {azimuth:4d} {result['annual_kwh']:8.1f} "
            f"{result['irradiance']['poa_kwh_m2']:8.1f} {result['irradiance']['ghi_kwh_m2']:8.1f} "
            f"{(ref_kwh if ref_kwh else 0):8.1f} {(delta if delta is not None else 0):6.1f}%"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())