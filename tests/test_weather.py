import datetime as dt
import json
import os
import tempfile
import unittest

from balconysolar import db, weather


class SyntheticYearTests(unittest.TestCase):
    def test_full_year_of_hours(self):
        rows = weather.synthetic_year(-33.87)
        self.assertEqual(len(rows), 365 * 24)
        self.assertEqual(len(rows[0]), 6)

    def test_daylight_hours_produce_energy(self):
        rows = weather.synthetic_year(-33.87, 151.21)
        day = [row for row in rows if row[0] == 172]
        self.assertGreater(max(row[2] for row in day), 200.0)

    def test_night_hours_are_dark(self):
        rows = weather.synthetic_year(-33.87, 151.21)
        day = [row for row in rows if row[0] == 172]
        dark = [row for row in day if row[2] == 0.0]
        self.assertGreater(len(dark), 4)
        self.assertLess(len(dark), 20)

    def test_southern_winter_is_weaker_than_summer(self):
        rows = weather.synthetic_year(-33.87, 151.21)
        june = sum(row[2] for row in rows if row[0] == 172)
        december = sum(row[2] for row in rows if row[0] == 355)
        self.assertGreater(december, june)


class WindowTests(unittest.TestCase):
    def test_window_is_one_year_ending_a_week_ago(self):
        start, end = weather.default_window(dt.date(2026, 11, 25))
        self.assertEqual(end, dt.date(2026, 11, 18))
        self.assertEqual((end - start).days, 365)


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = db.Store(os.path.join(self.tmp.name, "test.db"))

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_round_trip(self):
        self.store.set_cache("k", json.dumps({"rows": [[1, 2, 3, 4, 5, 6]]}))
        self.assertIsNotNone(self.store.get_cache("k"))

    def test_missing_key_returns_none(self):
        self.assertIsNone(self.store.get_cache("absent"))

    def test_offline_load_uses_synthetic_year(self):
        result = weather.load_year(-33.87, 151.21, self.store, offline=True)
        self.assertEqual(result["source"], "modelled")
        self.assertEqual(len(result["rows"]), 365 * 24)

    def test_second_offline_call_still_works(self):
        first = weather.load_year(-33.87, 151.21, self.store, offline=True)
        second = weather.load_year(-33.87, 151.21, self.store, offline=True)
        self.assertEqual(len(first["rows"]), len(second["rows"]))


if __name__ == "__main__":
    unittest.main()