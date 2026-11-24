"""SQLite storage for scenarios and the irradiance cache."""

from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import threading
import uuid

SCHEMA = """
CREATE TABLE IF NOT EXISTS scenarios (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    label TEXT NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    payload_json TEXT NOT NULL,
    result_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cache (
    cache_key TEXT PRIMARY KEY,
    fetched_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scenarios_created ON scenarios (created_at DESC);
"""


class Store:
    """A small SQLite wrapper with one connection and a lock."""

    def __init__(self, path: str = "data/balconysolar.db"):
        self.path = path
        directory = os.path.dirname(os.path.abspath(path))
        if directory:
            os.makedirs(directory, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    # ---- cache -----------------------------------------------------------
    def get_cache(self, key: str, max_age_days: int = 30) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT fetched_at, payload_json FROM cache WHERE cache_key = ?", (key,)
            ).fetchone()
        if not row:
            return None
        try:
            fetched = dt.datetime.fromisoformat(row["fetched_at"])
        except ValueError:
            return None
        if dt.datetime.utcnow() - fetched > dt.timedelta(days=max_age_days):
            return None
        return row["payload_json"]

    def set_cache(self, key: str, payload: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO cache (cache_key, fetched_at, payload_json) VALUES (?, ?, ?) "
                "ON CONFLICT(cache_key) DO UPDATE SET fetched_at = excluded.fetched_at, "
                "payload_json = excluded.payload_json",
                (key, dt.datetime.utcnow().isoformat(timespec="seconds"), payload),
            )
            self._conn.commit()

    # ---- scenarios -------------------------------------------------------
    def save_scenario(self, label: str, payload: dict, result: dict) -> str:
        scenario_id = uuid.uuid4().hex[:10]
        created = dt.datetime.now().astimezone().isoformat(timespec="seconds")
        location = payload.get("location") or {}
        with self._lock:
            self._conn.execute(
                "INSERT INTO scenarios (id, created_at, label, lat, lon, payload_json, result_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    scenario_id,
                    created,
                    label or "Untitled balcony",
                    float(location.get("lat", 0.0)),
                    float(location.get("lon", 0.0)),
                    json.dumps(payload),
                    json.dumps(result),
                ),
            )
            self._conn.commit()
        return scenario_id

    def list_scenarios(self, limit: int = 20) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, created_at, label, lat, lon, result_json FROM scenarios "
                "ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        output = []
        for row in rows:
            result = json.loads(row["result_json"])
            output.append(
                {
                    "id": row["id"],
                    "created_at": row["created_at"],
                    "label": row["label"],
                    "lat": row["lat"],
                    "lon": row["lon"],
                    "annual_kwh": result.get("annual_kwh"),
                    "payback_years": result.get("payback_years"),
                    "savings_aud": result.get("savings_aud"),
                }
            )
        return output

    def get_scenario(self, scenario_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM scenarios WHERE id = ?", (scenario_id,)
            ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "created_at": row["created_at"],
            "label": row["label"],
            "payload": json.loads(row["payload_json"]),
            "result": json.loads(row["result_json"]),
        }

    def delete_scenario(self, scenario_id: str) -> bool:
        with self._lock:
            cursor = self._conn.execute("DELETE FROM scenarios WHERE id = ?", (scenario_id,))
            self._conn.commit()
            return cursor.rowcount > 0

    def close(self) -> None:
        with self._lock:
            self._conn.close()