"""Panel, inverter, self-consumption and money model."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import solar

# A coarse household load shape. Values are multiples of the mean hourly load.
LOAD_SHAPE = [
    0.62, 0.52, 0.46, 0.44, 0.48, 0.68, 1.02, 1.28, 1.10, 0.92, 0.86, 0.84,
    0.88, 0.84, 0.82, 0.88, 1.02, 1.30, 1.58, 1.66, 1.48, 1.22, 0.94, 0.74,
]

PANELS = [
    {"id": "rigid-400", "name": "Rigid 400 W", "wp": 400, "area_m2": 1.95, "efficiency": 0.205, "temp_coeff": -0.0035, "noct": 45},
    {"id": "rigid-440", "name": "Rigid 440 W", "wp": 440, "area_m2": 2.05, "efficiency": 0.215, "temp_coeff": -0.0034, "noct": 44},
    {"id": "rigid-500", "name": "Rigid 500 W", "wp": 500, "area_m2": 2.28, "efficiency": 0.219, "temp_coeff": -0.0034, "noct": 44},
    {"id": "flex-200", "name": "Flexible 200 W", "wp": 200, "area_m2": 1.35, "efficiency": 0.148, "temp_coeff": -0.0038, "noct": 47},
    {"id": "flex-400", "name": "Flexible 400 W", "wp": 400, "area_m2": 2.55, "efficiency": 0.157, "temp_coeff": -0.0038, "noct": 47},
]

INVERTERS = [
    {"id": "micro-400", "name": "Microinverter 400 W", "limit_w": 400, "efficiency": 0.96},
    {"id": "micro-600", "name": "Microinverter 600 W", "limit_w": 600, "efficiency": 0.96},
    {"id": "micro-800", "name": "Microinverter 800 W", "limit_w": 800, "efficiency": 0.965},
    {"id": "string-1000", "name": "String inverter 1000 W", "limit_w": 1000, "efficiency": 0.97},
]

SYSTEM_LOSS = 0.08  # soiling, mismatch, wiring and connector loss
DEFAULT_CAPEX = 780.0
CO2_FACTOR_KG_PER_KWH = 0.79


@dataclass
class Panel:
    wp: float = 400.0
    area_m2: float = 1.95
    efficiency: float = 0.205
    temp_coeff: float = -0.0035
    noct: float = 45.0


@dataclass
class Inverter:
    limit_w: float = 400.0
    efficiency: float = 0.96


@dataclass
class Inputs:
    lat: float
    lon: float
    tilt: float = 90.0
    surface_azimuth: float = 0.0
    floor_level: int = 3
    rail_height_m: float = 1.1
    panel: Panel = field(default_factory=Panel)
    inverter: Inverter = field(default_factory=Inverter)
    obstructions: list = field(default_factory=list)
    daily_kwh: float = 8.0
    import_tariff: float = 0.32
    export_tariff: float = 0.05
    export_allowed: bool = True
    capex: float = DEFAULT_CAPEX
    albedo: float = 0.20


def cell_temperature(air_temp: float, poa: float, noct: float) -> float:
    """NOCT cell temperature model."""
    return air_temp + (noct - 20.0) / 800.0 * max(0.0, poa)


def dc_power(panel: Panel, poa: float, air_temp: float, system_loss: float = SYSTEM_LOSS) -> tuple[float, float]:
    """Return (dc watts, temperature derate fraction)."""
    if poa <= 0.0:
        return 0.0, 0.0
    t_cell = cell_temperature(air_temp, poa, panel.noct)
    temp_factor = 1.0 + panel.temp_coeff * (t_cell - 25.0)
    temp_factor = max(0.70, min(1.10, temp_factor))
    gross = panel.wp * (poa / 1000.0)
    return gross * temp_factor * (1.0 - system_loss), 1.0 - temp_factor


def estimate(inputs: Inputs, rows: list[list], source: str = "archive") -> dict:
    """Run the hourly model over a year of weather rows."""
    horizon = solar.horizon_profile(inputs.obstructions)

    monthly = [
        {"month": m, "kwh": 0.0, "poa_kwh": 0.0, "shaded_hours": 0, "days": 0}
        for m in range(1, 13)
    ]
    hour_sum = [0.0] * 24

    annual_ac = 0.0
    annual_poa = 0.0
    annual_beam = 0.0
    annual_diffuse = 0.0
    annual_ground = 0.0
    annual_ghi = 0.0
    annual_temp_loss = 0.0
    annual_clip_loss = 0.0
    annual_shading_loss = 0.0
    annual_system_loss = 0.0

    self_used = 0.0
    exported = 0.0
    imported = 0.0
    curtailed = 0.0
    daily_load_kw = inputs.daily_kwh / 24.0

    days = set()
    for row in rows:
        doy, hour, ghi, dni, dhi, temp = row
        doy = int(doy)
        hour_index = int(hour) % 24
        days.add(doy)
        month = _month_from_doy(doy)

        poa = solar.plane_of_array(
            inputs.lat,
            inputs.lon,
            doy,
            hour + 0.5,
            ghi,
            dni,
            dhi,
            inputs.tilt,
            inputs.surface_azimuth,
            horizon,
            inputs.albedo,
        )

        dc, temp_derate = dc_power(inputs.panel, poa.total, temp)
        ac_ideal = dc * inputs.inverter.efficiency
        ac = min(ac_ideal, inputs.inverter.limit_w)
        ac_kwh = ac / 1000.0

        annual_ac += ac_kwh
        annual_poa += poa.total / 1000.0
        annual_beam += poa.beam / 1000.0
        annual_diffuse += poa.diffuse / 1000.0
        annual_ground += poa.ground / 1000.0
        annual_ghi += ghi / 1000.0
        annual_temp_loss += (poa.total / 1000.0) * max(0.0, temp_derate)
        annual_clip_loss += max(0.0, ac_ideal - ac) / 1000.0
        annual_system_loss += dc * SYSTEM_LOSS / (1.0 - SYSTEM_LOSS) / 1000.0

        # Beam and sky-diffuse energy lost to the obstruction horizon. Both
        # terms use the same capped DNI, so the physical cap is not reported
        # as shading.
        annual_shading_loss += max(
            0.0,
            (poa.beam_unshaded - poa.beam) + (poa.diffuse_unshaded - poa.diffuse),
        ) / 1000.0

        if poa.shaded:
            monthly[month - 1]["shaded_hours"] += 1

        monthly[month - 1]["kwh"] += ac_kwh
        monthly[month - 1]["poa_kwh"] += poa.total / 1000.0
        hour_sum[hour_index] += ac_kwh

        load_kw = daily_load_kw * LOAD_SHAPE[hour_index]
        self_used += min(ac_kwh, load_kw)
        imported += max(0.0, load_kw - ac_kwh)
        surplus = max(0.0, ac_kwh - load_kw)
        if inputs.export_allowed:
            exported += surplus
        else:
            curtailed += surplus

    day_count = max(1, len(days))
    for item in monthly:
        item["kwh"] = round(item["kwh"], 1)
        item["poa_kwh"] = round(item["poa_kwh"], 1)
        item["days"] = _days_in_month(item["month"])

    savings = self_used * inputs.import_tariff + exported * inputs.export_tariff
    payback = inputs.capex / savings if savings > 0.01 else None

    low_savings = savings * 0.88 * 0.92
    high_savings = savings * 1.12 * 1.08
    payback_high = inputs.capex / low_savings if low_savings > 0.01 else None
    payback_low = inputs.capex / high_savings if high_savings > 0.01 else None

    specific = annual_ac / (inputs.panel.wp / 1000.0) if inputs.panel.wp else 0.0

    return {
        "annual_kwh": round(annual_ac, 1),
        "specific_yield": round(specific, 1),
        "monthly": monthly,
        "day_profile": [round(value / day_count, 3) for value in hour_sum],
        "day_kwh": round(sum(hour_sum) / day_count, 2),
        "self_consumed_kwh": round(self_used, 1),
        "exported_kwh": round(exported, 1),
        "imported_kwh": round(imported, 1),
        "curtailed_kwh": round(curtailed, 1),
        "self_consumption_ratio": round(self_used / annual_ac, 3) if annual_ac > 0 else 0.0,
        "savings_aud": round(savings, 0),
        "capex_aud": round(inputs.capex, 0),
        "payback_years": round(payback, 1) if payback else None,
        "payback_range": [
            round(payback_low, 1) if payback_low else None,
            round(payback_high, 1) if payback_high else None,
        ],
        "co2_kg": round(annual_ac * CO2_FACTOR_KG_PER_KWH, 0),
        "losses": {
            "shading_kwh": round(annual_shading_loss, 1),
            "temperature_kwh": round(annual_temp_loss, 1),
            "clipping_kwh": round(annual_clip_loss, 1),
            "system_kwh": round(annual_system_loss, 1),
        },
        "irradiance": {
            "poa_kwh_m2": round(annual_poa, 1),
            "ghi_kwh_m2": round(annual_ghi, 1),
            "beam_kwh_m2": round(annual_beam, 1),
            "diffuse_kwh_m2": round(annual_diffuse, 1),
            "ground_kwh_m2": round(annual_ground, 1),
        },
        "shaded_hours": sum(item["shaded_hours"] for item in monthly),
        "hours": len(rows),
        "data_source": "Open-Meteo Archive (hourly reanalysis)" if source == "archive" else "Clear-sky model (offline fallback)",
        "source_kind": source,
    }


def _month_from_doy(doy: int) -> int:
    bounds = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    total = 0
    for index, days in enumerate(bounds, start=1):
        total += days
        if doy <= total:
            return index
    return 12


def _days_in_month(month: int) -> int:
    return [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]