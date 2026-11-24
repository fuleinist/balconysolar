# balconysolar — PLAN

## Stack

- Python 3.11 standard library only. No FastAPI, because the installed FastAPI and Starlette versions conflict on this machine.
- `http.server.ThreadingHTTPServer` for HTTP.
- `sqlite3` for the scenario store and the irradiance cache.
- Vanilla JS and hand-written SVG for the charts.
- `unittest` for tests.

## Modules

| File | Role |
|---|---|
| `balconysolar/solar.py` | Solar position, angle of incidence, transposition, horizon shading. |
| `balconysolar/weather.py` | Open-Meteo archive fetch, SQLite cache, clear-sky fallback. |
| `balconysolar/model.py` | Panel, inverter, self-consumption, money and payback. |
| `balconysolar/pvgis.py` | Optional PVGIS reference call. |
| `balconysolar/db.py` | SQLite schema and queries. |
| `balconysolar/server.py` | Router, JSON API and static files. |
| `balconysolar/static/` | `index.html`, `app.js`, `styles.css`. |

## Build order

1. Solar geometry and transposition. Test against known solar noon values.
2. Weather fetch and cache. Test the parser with a fixed fixture.
3. Panel and inverter model. Test temperature derate and clipping.
4. Self-consumption and money. Test the zero-export case.
5. HTTP API and the single-page UI.
6. Printable brief and saved scenarios.
7. README, logo and screenshots.

## Verification

- Unit tests for each module.
- One end-to-end estimate for Sydney, north, 90 degree tilt.
- A comparison with the live PVGIS call.
- A headless screenshot of the result view.

## Budget

Ten spec, build and verify cycles. Commit after each cycle.