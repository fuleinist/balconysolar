"""Capture real screenshots of the running app with Playwright."""

import json
import os
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8771"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "screenshots")

PAYLOAD = {
    "label": "Chatswood balcony, 400 W",
    "location": {"lat": -33.7969, "lon": 151.1833, "label": "Chatswood, Sydney"},
    "balcony": {"azimuth": 0, "tilt": 90, "rail_height_m": 1.1, "floor_level": 4},
    "panel": {"wp": 400, "area_m2": 1.95, "efficiency": 0.205, "temp_coeff": -0.0035, "noct": 45},
    "inverter": {"limit_w": 400, "efficiency": 0.96},
    "obstructions": [{"azimuth": 120, "elevation": 28, "width": 50}],
    "load": {"daily_kwh": 8.0},
    "tariff": {"import_aud_kwh": 0.32, "export_aud_kwh": 0.05, "export_allowed": True},
    "capex_aud": 780,
}


def post(path, payload):
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        BASE + path, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.loads(response.read().decode("utf-8"))


def main():
    os.makedirs(OUT, exist_ok=True)

    scenario = post("/api/scenarios", PAYLOAD)
    scenario_id = scenario["id"]
    print("scenario", scenario_id, "annual", scenario["result"]["annual_kwh"])

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=2)
        page.goto(BASE + "/", wait_until="networkidle")
        page.wait_for_function(
            "() => { const el = document.getElementById('payback'); return el && el.textContent.trim() !== '—'; }",
            timeout=180000,
        )
        time.sleep(1.5)
        page.screenshot(path=os.path.join(OUT, "app-desktop.png"), full_page=True)
        print("saved app-desktop.png")

        brief = browser.new_page(viewport={"width": 900, "height": 1400}, device_scale_factor=2)
        brief.goto(f"{BASE}/brief/{scenario_id}", wait_until="networkidle")
        time.sleep(0.8)
        brief.screenshot(path=os.path.join(OUT, "brief-desktop.png"), full_page=True)
        print("saved brief-desktop.png")

        browser.close()


if __name__ == "__main__":
    main()