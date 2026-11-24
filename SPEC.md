# balconysolar — SPEC

## One line

A sizing tool for a renter's plug-in balcony panel. It returns yield, self-consumption and payback from real hourly weather.

## Problem

A renter cannot put panels on the roof. A balcony rail can hold one panel. The open question is whether that balcony gets sun.

A north-facing balcony on level 3 is not the same as a north-facing balcony behind a tower. Tilt matters. Rail height matters. A vertical panel loses most of the summer noon sun and gains winter sun.

Sales pages quote a single number. Renters need a range, a reason and a payback estimate before they spend 700 dollars.

## Product boundary

`sunshift` is a solar and battery scheduler. It moves loads to the sunny hours of an existing system.

`balconysolar` is a pre-purchase sizer. There is no hardware, no telemetry and no control loop. One renter, one balcony, one panel, one decision.

## Users

1. A renter with a balcony and a power point.
2. A strata committee member who checks whether a panel is allowed.
3. A community energy group that advises renters.

## MVP features

- **Balcony record.** Latitude, longitude, orientation in degrees, panel tilt, rail height and floor level.
- **Horizon editor.** Add an obstruction by direction, height angle and width. The tool builds a 36-bin horizon.
- **Real weather.** One year of hourly global, direct and diffuse irradiance plus air temperature from the Open-Meteo Archive API. Cached in SQLite for 30 days.
- **Offline fallback.** A clear-sky model with monthly clearness factors when the network is down. The answer is labelled `modelled`.
- **Plane-of-array model.** Solar position, angle of incidence, Hay-Davies diffuse transposition, ground reflection and horizon beam shading.
- **Panel model.** Peak power, area, temperature coefficient and NOCT. Cell temperature from the NOCT model.
- **Inverter model.** AC limit and efficiency. Clipping loss is reported.
- **Self-consumption.** An hourly load shape scaled to a daily kWh figure. Self-used, exported and imported energy are separate.
- **Money.** Import tariff, feed-in tariff, export allowed or zero-export, capital cost in AUD.
- **Payback range.** Low, central and high estimates from a yield band and a tariff band. No single false-precision number.
- **Loss breakdown.** Shading, clipping, temperature, soiling and inverter losses in kWh.
- **Monthly chart and mean-day chart.** Plain SVG, no chart library.
- **Saved scenarios.** SQLite store with a short id.
- **Printable brief.** A4 page with the result, assumptions, data source and a landlord permission checklist.
- **PVGIS cross-check.** An optional call compares the model with the PVGIS v5.2 reference yield.

## Non-goals

- Electrical design, wiring advice or grid approval.
- Battery storage.
- Panel sales or affiliate links.
- Shading from moving objects such as trees in leaf.
- Roof-mounted systems.

## Acceptance criteria

1. A horizontal surface receives the same global irradiance as the input GHI within 1 percent.
2. A north-facing 90 degree panel in Sydney returns an annual yield within 20 percent of the PVGIS reference for the same geometry.
3. The mean-day chart sums to the annual total within 0.5 percent.
4. Shading an obstruction across the solar path lowers beam yield and reports the loss.
5. Zero export removes export credit and raises self-consumption share.
6. Payback is undefined, not infinite, when savings are zero.
7. Every response names its data source and its assumptions.
8. All tests pass with `python -m unittest`.
9. The app runs with only the Python standard library.

## Data sources

- Open-Meteo Archive API: hourly `shortwave_radiation`, `direct_normal_irradiance`, `diffuse_radiation`, `temperature_2m`. Free, no key.
- PVGIS v5.2 `PVcalc`: reference annual yield for a set geometry. Free, no key.
- Panel and inverter presets: values from public datasheets of common 400 to 500 W modules and 400 to 800 W microinverters.

## Risks

- The archive grid is about 5 to 25 km. Local cloud and building shade can differ. The tool shows the grid cell and asks for a correction.
- The horizon model is an approximation. It uses straight edges, not a photo.
- Tariffs change. The user edits them. The payback is a range, not a promise.