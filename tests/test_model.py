import unittest

from balconysolar import model, solar


def simple_rows(count=48, ghi=800.0, dni=700.0, dhi=100.0, temp=22.0):
    """Two days of constant midday-ish weather for deterministic tests."""
    rows = []
    for day in (1, 2):
        for hour in range(24):
            rows.append([day, float(hour), ghi, dni, dhi, temp])
    return rows


class CellTemperatureTests(unittest.TestCase):
    def test_cell_is_hotter_than_air_in_sun(self):
        self.assertGreater(model.cell_temperature(25.0, 800.0, 45.0), 25.0)

    def test_cell_equals_air_without_sun(self):
        self.assertAlmostEqual(model.cell_temperature(18.0, 0.0, 45.0), 18.0)


class DcPowerTests(unittest.TestCase):
    def test_stc_power_minus_system_loss(self):
        panel = model.Panel(wp=400.0, noct=20.0, temp_coeff=-0.0035)
        # NOCT 20 keeps the cell at ambient, so only the system loss applies.
        watts, _ = model.dc_power(panel, 1000.0, 25.0)
        self.assertAlmostEqual(watts, 400.0 * (1 - model.SYSTEM_LOSS), delta=0.5)

    def test_no_power_without_irradiance(self):
        watts, _ = model.dc_power(model.Panel(), 0.0, 20.0)
        self.assertEqual(watts, 0.0)

    def test_hot_cell_loses_power(self):
        panel = model.Panel()
        cool, _ = model.dc_power(panel, 900.0, 5.0)
        hot, _ = model.dc_power(panel, 900.0, 40.0)
        self.assertLess(hot, cool)


class EstimateTests(unittest.TestCase):
    def make_inputs(self, **overrides):
        values = dict(lat=-33.87, lon=151.21, tilt=90.0, surface_azimuth=0.0, daily_kwh=8.0)
        values.update(overrides)
        return model.Inputs(**values)

    def test_estimate_returns_twelve_months(self):
        result = model.estimate(self.make_inputs(), simple_rows(), source="modelled")
        self.assertEqual(len(result["monthly"]), 12)
        self.assertEqual(result["hours"], 48)
        self.assertEqual(len(result["day_profile"]), 24)

    def test_monthly_totals_match_annual(self):
        result = model.estimate(self.make_inputs(), simple_rows())
        self.assertAlmostEqual(
            sum(item["kwh"] for item in result["monthly"]), result["annual_kwh"], delta=0.3
        )

    def test_day_profile_sums_to_daily_energy(self):
        result = model.estimate(self.make_inputs(), simple_rows())
        self.assertAlmostEqual(sum(result["day_profile"]), result["day_kwh"], delta=0.05)

    def test_zero_export_removes_export_and_adds_curtailment(self):
        shared = dict(rows=simple_rows(), inputs=self.make_inputs(daily_kwh=1.0))
        allowed = model.estimate(shared["inputs"], shared["rows"])
        blocked = model.estimate(
            self.make_inputs(daily_kwh=1.0, export_allowed=False), simple_rows()
        )
        self.assertGreater(allowed["exported_kwh"], 0.0)
        self.assertEqual(blocked["exported_kwh"], 0.0)
        self.assertGreater(blocked["curtailed_kwh"], 0.0)

    def test_payback_is_none_without_savings(self):
        result = model.estimate(
            self.make_inputs(import_tariff=0.0, export_tariff=0.0), simple_rows()
        )
        self.assertIsNone(result["payback_years"])
        self.assertEqual(result["savings_aud"], 0)

    def test_payback_range_brackets_the_central_value(self):
        result = model.estimate(self.make_inputs(), simple_rows())
        low, high = result["payback_range"]
        self.assertLessEqual(low, result["payback_years"])
        self.assertGreaterEqual(high, result["payback_years"])

    def test_north_beats_east_at_thirty_degrees(self):
        from balconysolar import weather

        rows = weather.synthetic_year(-33.87, 151.21)
        north = model.estimate(self.make_inputs(tilt=30.0), rows)
        east = model.estimate(self.make_inputs(tilt=30.0, surface_azimuth=90.0), rows)
        self.assertGreater(north["annual_kwh"], east["annual_kwh"] * 1.2)

    def test_thirty_degree_tilt_beats_vertical(self):
        from balconysolar import weather

        rows = weather.synthetic_year(-33.87, 151.21)
        tilted = model.estimate(self.make_inputs(tilt=30.0), rows)
        vertical = model.estimate(self.make_inputs(tilt=90.0), rows)
        self.assertGreater(tilted["annual_kwh"], vertical["annual_kwh"])

    def test_obstruction_reduces_yield_and_reports_shading(self):
        clear = model.estimate(self.make_inputs(), simple_rows())
        blocked = model.estimate(
            self.make_inputs(obstructions=[solar.Obstruction(0.0, 85.0, 180.0)]),
            simple_rows(),
        )
        self.assertLess(blocked["annual_kwh"], clear["annual_kwh"])
        self.assertGreater(blocked["losses"]["shading_kwh"], 0.0)

    def test_inverter_clipping_is_reported(self):
        panel = model.Panel(wp=2000.0)
        result = model.estimate(
            self.make_inputs(panel=panel, inverter=model.Inverter(limit_w=400.0)),
            simple_rows(ghi=1000.0, dni=900.0, dhi=100.0),
        )
        self.assertGreater(result["losses"]["clipping_kwh"], 0.0)

    def test_source_label_is_honest(self):
        modelled = model.estimate(self.make_inputs(), simple_rows(), source="modelled")
        archive = model.estimate(self.make_inputs(), simple_rows(), source="archive")
        self.assertIn("Clear-sky", modelled["data_source"])
        self.assertIn("Open-Meteo", archive["data_source"])


if __name__ == "__main__":
    unittest.main()