"""Solar geometry, plane-of-array transposition and horizon shading.

All angles are degrees unless a name ends in ``_rad``. Azimuth is measured
from true north, clockwise. Time is UTC unless stated otherwise.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

SOLAR_CONSTANT = 1367.0


def day_of_year(month: int, day: int) -> int:
    """Return the day of year for a month and day in a non-leap year."""
    cumulative = (0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334)
    return cumulative[month - 1] + day


def declination(n: int) -> float:
    """Solar declination in degrees from the NOAA fractional-year form."""
    gamma = 2.0 * math.pi / 365.0 * (n - 1)
    return math.degrees(
        0.006918
        - 0.399912 * math.cos(gamma)
        + 0.070257 * math.sin(gamma)
        - 0.006758 * math.cos(2 * gamma)
        + 0.000907 * math.sin(2 * gamma)
        - 0.002697 * math.cos(3 * gamma)
        + 0.001480 * math.sin(3 * gamma)
    )


def equation_of_time(n: int) -> float:
    """Equation of time in minutes."""
    gamma = 2.0 * math.pi / 365.0 * (n - 1)
    return 229.18 * (
        0.000075
        + 0.001868 * math.cos(gamma)
        - 0.032077 * math.sin(gamma)
        - 0.014615 * math.cos(2 * gamma)
        - 0.040849 * math.sin(2 * gamma)
    )


def solar_position(lat: float, lon: float, n: int, utc_hour: float) -> tuple[float, float]:
    """Return (elevation, azimuth) in degrees for a UTC hour.

    ``utc_hour`` is a decimal hour, so 13.5 means 13:30 UTC.
    """
    decl = declination(n)
    eot = equation_of_time(n)

    # True solar time in minutes. For UTC input the zone correction is zero.
    tst = utc_hour * 60.0 + eot + 4.0 * lon
    hour_angle = tst / 4.0 - 180.0

    lat_rad = math.radians(lat)
    decl_rad = math.radians(decl)
    ha_rad = math.radians(hour_angle)

    sin_elev = math.sin(lat_rad) * math.sin(decl_rad) + math.cos(lat_rad) * math.cos(
        decl_rad
    ) * math.cos(ha_rad)
    sin_elev = max(-1.0, min(1.0, sin_elev))
    elevation = math.degrees(math.asin(sin_elev))

    az_south = math.degrees(
        math.atan2(
            math.sin(ha_rad),
            math.cos(ha_rad) * math.sin(lat_rad) - math.tan(decl_rad) * math.cos(lat_rad),
        )
    )
    azimuth = (az_south + 180.0) % 360.0
    return elevation, azimuth


def air_mass(elevation: float) -> float:
    """Kasten-Young relative air mass. Returns 0 when the sun is below the horizon."""
    if elevation <= 0.0:
        return 0.0
    return 1.0 / (
        math.sin(math.radians(elevation))
        + 0.50572 * (elevation + 6.07995) ** -1.6364
    )


def extraterrestrial_normal(n: int) -> float:
    """Extraterrestrial normal irradiance in W/m2."""
    return SOLAR_CONSTANT * (1.0 + 0.033 * math.cos(math.radians(360.0 * n / 365.0)))


def clear_sky_ghi(elevation: float) -> float:
    """Haurwitz clear-sky global horizontal irradiance in W/m2."""
    if elevation <= 0.0:
        return 0.0
    cos_z = math.cos(math.radians(90.0 - elevation))
    cos_z = max(0.01, cos_z)
    return 1098.0 * cos_z * math.exp(-0.059 / cos_z)


def clear_sky_dni(elevation: float) -> float:
    """Simple clear-sky beam irradiance in W/m2 from air mass."""
    if elevation <= 0.0:
        return 0.0
    return 1353.0 * (0.7 ** (air_mass(elevation) ** 0.678))


def erbs_diffuse_fraction(clearness: float) -> float:
    """Erbs diffuse fraction from the clearness index."""
    if clearness <= 0.22:
        return 1.0 - 0.09 * clearness
    if clearness <= 0.80:
        return (
            0.9511
            - 0.1604 * clearness
            + 4.388 * clearness**2
            - 16.638 * clearness**3
            + 12.336 * clearness**4
        )
    return 0.165


def split_irradiance(ghi: float, elevation: float, n: int) -> tuple[float, float]:
    """Return (dni, dhi) from GHI when the components are missing."""
    if ghi <= 0.0 or elevation <= 0.0:
        return 0.0, 0.0
    cos_z = max(0.01, math.cos(math.radians(90.0 - elevation)))
    extraterrestrial_horizontal = extraterrestrial_normal(n) * cos_z
    clearness = ghi / max(1.0, extraterrestrial_horizontal)
    clearness = max(0.0, min(1.1, clearness))
    diffuse_fraction = erbs_diffuse_fraction(clearness)
    dhi = diffuse_fraction * ghi
    dni = (ghi - dhi) / cos_z
    # A coarse grid can imply more beam than the atmosphere can pass.
    dni = max(0.0, min(dni, clear_sky_dni(elevation)))
    return dni, dhi


def angle_of_incidence(surface_tilt: float, surface_azimuth: float, elevation: float, azimuth: float) -> float:
    """Return cos(angle of incidence) for a tilted surface. Negative means back-lit."""
    if elevation <= 0.0:
        return 0.0
    zen_rad = math.radians(90.0 - elevation)
    tilt_rad = math.radians(surface_tilt)
    delta_az = math.radians(azimuth - surface_azimuth)
    cos_aoi = math.cos(zen_rad) * math.cos(tilt_rad) + math.sin(zen_rad) * math.sin(
        tilt_rad
    ) * math.cos(delta_az)
    return max(-1.0, min(1.0, cos_aoi))


@dataclass
class Obstruction:
    """A blocking edge seen from the panel."""

    azimuth: float
    elevation: float
    width: float = 30.0


def horizon_profile(obstructions: list[Obstruction], bins: int = 36) -> list[float]:
    """Build a horizon elevation profile in 360/bins degree bins."""
    step = 360.0 / bins
    profile = [0.0] * bins
    for item in obstructions:
        if item.elevation <= 0.0:
            continue
        half = max(0.0, item.width) / 2.0
        start = item.azimuth - half
        end = item.azimuth + half
        # Walk every bin centre inside the angular span, wrapping at north.
        for index in range(bins):
            centre = index * step + step / 2.0
            delta = (centre - start) % 360.0
            if delta <= (end - start):
                profile[index] = max(profile[index], item.elevation)
    return profile


def horizon_at(azimuth: float, profile: list[float]) -> float:
    """Interpolate the horizon elevation at an azimuth."""
    if not profile:
        return 0.0
    bins = len(profile)
    step = 360.0 / bins
    position = (azimuth % 360.0) / step - 0.5
    low = math.floor(position)
    weight = position - low
    low_value = profile[int(low) % bins]
    high_value = profile[int(low + 1) % bins]
    return low_value + (high_value - low_value) * weight


def sky_view_factor(profile: list[float]) -> float:
    """Approximate the unobstructed share of the sky hemisphere.

    Each blocked horizon bin removes a slice proportional to its elevation
    angle. The result is clamped to the range 0.2 to 1.0.
    """
    if not profile:
        return 1.0
    blocked = sum(min(90.0, max(0.0, value)) for value in profile) / len(profile)
    return max(0.2, min(1.0, 1.0 - blocked / 90.0))


@dataclass
class PoaComponents:
    """Plane-of-array irradiance components in W/m2."""

    beam: float = 0.0
    beam_unshaded: float = 0.0
    diffuse: float = 0.0
    diffuse_unshaded: float = 0.0
    ground: float = 0.0
    total: float = 0.0
    cos_aoi: float = 0.0
    shaded: bool = False
    sun_elevation: float = 0.0
    sun_azimuth: float = 0.0


def plane_of_array(
    lat: float,
    lon: float,
    n: int,
    utc_hour: float,
    ghi: float,
    dni: float,
    dhi: float,
    tilt: float,
    surface_azimuth: float,
    horizon: list[float] | None = None,
    albedo: float = 0.2,
) -> PoaComponents:
    """Transpose horizontal irradiance onto a tilted surface."""
    elevation, azimuth = solar_position(lat, lon, n, utc_hour)
    result = PoaComponents(sun_elevation=elevation, sun_azimuth=azimuth)
    if elevation <= 0.0:
        return result

    if ghi <= 0.0:
        return result

    if dni <= 0.0 and dhi <= 0.0:
        dni, dhi = split_irradiance(ghi, elevation, n)

    # Hourly archive data on a coarse grid can overstate the beam at low sun.
    # Cap DNI at the clear-sky value for the same elevation.
    dni = min(dni, clear_sky_dni(elevation))

    cos_aoi = angle_of_incidence(tilt, surface_azimuth, elevation, azimuth)
    result.cos_aoi = cos_aoi

    blocked = False
    if horizon:
        blocked = elevation < horizon_at(azimuth, horizon)
    result.shaded = blocked

    beam = max(0.0, dni * max(0.0, cos_aoi))
    result.beam_unshaded = beam
    result.beam = 0.0 if blocked else beam

    cos_zen = max(0.01, math.cos(math.radians(90.0 - elevation)))
    anisotropy = min(1.0, max(0.0, dni / max(1.0, extraterrestrial_normal(n) * cos_zen)))
    tilt_rad = math.radians(tilt)
    sky_fraction = (1.0 - anisotropy) * (1.0 + math.cos(tilt_rad)) / 2.0
    if cos_aoi > 0.0:
        # The circumsolar ratio must not exceed one. Without the clamp a
        # vertical panel facing a low sun receives more diffuse than the sky holds.
        sky_fraction += anisotropy * min(1.0, cos_aoi / cos_zen)
    view = sky_view_factor(horizon or [])
    diffuse_full = dhi * max(0.0, sky_fraction)
    result.diffuse_unshaded = diffuse_full
    result.diffuse = diffuse_full * view

    result.ground = ghi * albedo * (1.0 - math.cos(tilt_rad)) / 2.0
    result.total = result.beam + result.diffuse + result.ground
    return result


def solar_noon_utc(lat: float, lon: float, n: int) -> float:
    """Return the UTC decimal hour of solar noon for a day and place."""
    eot = equation_of_time(n)
    minutes = 720.0 - 4.0 * lon - eot
    return (minutes / 60.0) % 24.0


def sun_vector(elevation: float, azimuth: float) -> tuple[float, float, float]:
    """Unit vector for the sun in an east-north-up frame."""
    elev_rad = math.radians(elevation)
    az_rad = math.radians(azimuth)
    east = math.cos(elev_rad) * math.sin(az_rad)
    north = math.cos(elev_rad) * math.cos(az_rad)
    up = math.sin(elev_rad)
    return east, north, up