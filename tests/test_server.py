import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from balconysolar import server


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.httpd = server.create_server(
            "127.0.0.1", 0, os.path.join(cls.tmp.name, "test.db")
        )
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        if server.STORE is not None:
            server.STORE.close()
            server.STORE = None
        cls.tmp.cleanup()

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def get(self, path):
        with urllib.request.urlopen(self.url(path), timeout=30) as response:
            return response.status, response.read()

    def post(self, path, payload):
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.url(path),
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def test_health(self):
        status, body = self.get("/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["ok"])

    def test_presets(self):
        status, body = self.get("/api/panels")
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertGreaterEqual(len(payload["panels"]), 3)
        self.assertGreaterEqual(len(payload["inverters"]), 3)

    def test_index_page(self):
        status, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"balconysolar", body)

    def test_estimate_offline(self):
        status, payload = self.post(
            "/api/estimate",
            {
                "location": {"lat": -33.87, "lon": 151.21, "label": "Sydney"},
                "balcony": {"azimuth": 0, "tilt": 90, "floor_level": 3},
                "panel": {"wp": 400, "area_m2": 1.95},
                "inverter": {"limit_w": 400, "efficiency": 0.96},
                "offline": True,
            },
        )
        self.assertEqual(status, 200)
        self.assertGreater(payload["annual_kwh"], 100.0)
        self.assertEqual(len(payload["monthly"]), 12)
        self.assertEqual(len(payload["day_profile"]), 24)
        self.assertEqual(payload["source_kind"], "modelled")
        self.assertIn("assumptions", payload)

    def test_estimate_rejects_bad_latitude(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.post("/api/estimate", {"location": {"lat": 999, "lon": 0}, "offline": True})
        self.assertEqual(caught.exception.code, 400)

    def test_scenario_round_trip(self):
        status, payload = self.post(
            "/api/scenarios",
            {
                "label": "Test balcony",
                "location": {"lat": -33.87, "lon": 151.21, "label": "Sydney"},
                "balcony": {"azimuth": 10, "tilt": 90},
                "panel": {"wp": 400, "area_m2": 1.95},
                "offline": True,
            },
        )
        self.assertEqual(status, 201)
        scenario_id = payload["id"]

        status, body = self.get(f"/api/scenarios/{scenario_id}")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["label"], "Test balcony")

        status, body = self.get(f"/brief/{scenario_id}")
        self.assertEqual(status, 200)
        self.assertIn(b"Balcony solar brief", body)

    def test_missing_scenario_returns_404(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.get("/api/scenarios/nope")
        self.assertEqual(caught.exception.code, 404)


if __name__ == "__main__":
    unittest.main()