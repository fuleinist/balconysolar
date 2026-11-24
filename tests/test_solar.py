import unittest

from balconysolar import solar


class DeclinationTests(unittest.TestCase):
    def test_june_solstice_is_positive(self):
        self.assertAlmostEqual(solar.declination(172), 23.4, delta=0.6)

    def test_december_solstice_is_negative(self):
        self.assertAlmostEqual(solar.declination(355), -23.3, delta=0.6)

    def test_equinox_is_near_zero(self):
        self.assertAlmostEqual(solar.declination(81), 0.0, delta=1.0)


class SolarPositionTests(unittest.TestCase):
    def test_sydney_solar_noon_is_due_north(self):
        # 2025-11-25, solar noon near 01:45 UTC in Sydney.
        elevation, azimuth = solar.solar_position(-33.87, 151.21, 329, 1.75)
        self.assertGreater(elevation, 75.0)
        self.assertLess(elevation, 80.0)
        self.assertTrue(azimuth < 5.0 or azimuth > 355.0)

    def test_northern_noon_points_south(self):
        # 2025-06-21 near solar noon at 40 degrees north.
        elevation, azimuth = solar.solar_position(40.0, 0.0, 172, 12.0)
        self.assertAlmostEqual(elevation, 73.4, delta=1.5)
        self.assertAlmostEqual(azimuth, 180.0, delta=2.0)

    def test_sun_is_below_horizon_at_midnight(self):
        elevation, _ = solar.solar_position(-33.87, 151.21, 329, 13.0)
        self.assertLess(elevation, 0.0)


class TranspositionTests(unittest.TestCase):
    def test_horizontal_surface_matches_ghi(self):
        import math

        elevation, _ = solar.solar_position(-33.87, 151.21, 329, 2.0)
        cos_z = math.cos(math.radians(90.0 - elevation))
        dni, dhi = 600.0, 100.0
        ghi = dni * cos_z + dhi
        poa = solar.plane_of_array(
            -33.87, 151.21, 329, 2.0, ghi, dni, dhi, tilt=0.0, surface_azimuth=0.0
        )
        self.assertAlmostEqual(poa.total, ghi, delta=0.5)

    def test_vertical_panel_gains_less_at_summer_noon(self):
        midday = solar.plane_of_array(
            -33.87, 151.21, 329, 1.9, 950.0, 800.0, 120.0, tilt=90.0, surface_azimuth=0.0
        )
        tilted = solar.plane_of_array(
            -33.87, 151.21, 329, 1.9, 950.0, 800.0, 120.0, tilt=20.0, surface_azimuth=0.0
        )
        self.assertLess(midday.beam, tilted.beam)

    def test_panel_facing_away_gets_no_beam(self):
        poa = solar.plane_of_array(
            -33.87, 151.21, 329, 1.9, 950.0, 800.0, 120.0, tilt=90.0, surface_azimuth=180.0
        )
        self.assertEqual(poa.beam, 0.0)

    def test_night_returns_zero(self):
        poa = solar.plane_of_array(
            -33.87, 151.21, 329, 13.0, 0.0, 0.0, 0.0, tilt=90.0, surface_azimuth=0.0
        )
        self.assertEqual(poa.total, 0.0)


class HorizonTests(unittest.TestCase):
    def test_obstruction_fills_the_right_bins(self):
        profile = solar.horizon_profile(
            [solar.Obstruction(azimuth=90.0, elevation=30.0, width=20.0)]
        )
        self.assertAlmostEqual(solar.horizon_at(90.0, profile), 30.0, delta=0.1)
        self.assertLess(solar.horizon_at(270.0, profile), 0.1)

    def test_shading_blocks_the_beam(self):
        horizon = solar.horizon_profile(
            [solar.Obstruction(azimuth=0.0, elevation=80.0, width=120.0)]
        )
        poa = solar.plane_of_array(
            -33.87, 151.21, 329, 1.9, 950.0, 800.0, 120.0, 20.0, 0.0, horizon=horizon
        )
        self.assertTrue(poa.shaded)
        self.assertEqual(poa.beam, 0.0)

    def test_sky_view_factor_drops_with_a_tall_horizon(self):
        open_profile = solar.horizon_profile([])
        blocked = solar.horizon_profile(
            [solar.Obstruction(azimuth=0.0, elevation=60.0, width=360.0)]
        )
        self.assertGreater(solar.sky_view_factor(open_profile), solar.sky_view_factor(blocked))


class SplitTests(unittest.TestCase):
    def test_split_reproduces_ghi(self):
        ghi = 500.0
        elevation, _ = solar.solar_position(-33.87, 151.21, 329, 2.0)
        dni, dhi = solar.split_irradiance(ghi, elevation, 329)
        cos_z = __import__("math").cos(__import__("math").radians(90.0 - elevation))
        self.assertAlmostEqual(dni * cos_z + dhi, ghi, delta=1.0)


if __name__ == "__main__":
    unittest.main()