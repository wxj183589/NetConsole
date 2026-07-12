from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from netconsole.core.database import Database
from netconsole.services.wifi_survey.scanner import WifiObservation


class WifiSurveyRepository:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.initialize()

    def initialize(self) -> None:
        with self.database.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS wifi_floor_plans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    image_path TEXT NOT NULL,
                    width_px INTEGER,
                    height_px INTEGER,
                    meter_per_px REAL,
                    created_at TEXT,
                    updated_at TEXT
                );
                CREATE TABLE IF NOT EXISTS wifi_survey_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    floor_plan_id INTEGER NOT NULL REFERENCES wifi_floor_plans(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    adapter_name TEXT,
                    started_at TEXT,
                    ended_at TEXT,
                    remark TEXT,
                    created_at TEXT,
                    updated_at TEXT
                );
                CREATE TABLE IF NOT EXISTS wifi_survey_points (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL REFERENCES wifi_survey_sessions(id) ON DELETE CASCADE,
                    point_index INTEGER NOT NULL,
                    x_px REAL NOT NULL,
                    y_px REAL NOT NULL,
                    x_meter REAL,
                    y_meter REAL,
                    remark TEXT,
                    created_at TEXT
                );
                CREATE TABLE IF NOT EXISTS wifi_observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    point_id INTEGER NOT NULL REFERENCES wifi_survey_points(id) ON DELETE CASCADE,
                    scan_time TEXT,
                    ssid TEXT,
                    bssid TEXT,
                    rssi_dbm REAL,
                    signal_quality INTEGER,
                    channel INTEGER,
                    frequency_mhz INTEGER,
                    band TEXT,
                    security TEXT,
                    raw_text TEXT,
                    raw_json TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_wifi_sessions_floor_plan ON wifi_survey_sessions(floor_plan_id);
                CREATE INDEX IF NOT EXISTS idx_wifi_points_session ON wifi_survey_points(session_id);
                CREATE INDEX IF NOT EXISTS idx_wifi_observations_point ON wifi_observations(point_id);
                """
            )
            conn.commit()

    def create_floor_plan(self, name: str, image_path: str, width_px: int, height_px: int) -> dict[str, object]:
        now = _now()
        with self.database.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO wifi_floor_plans (name, image_path, width_px, height_px, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (name, image_path, width_px, height_px, now, now),
            )
            conn.commit()
            return self.get_floor_plan(int(cursor.lastrowid))

    def list_floor_plans(self) -> list[dict[str, object]]:
        with self.database.connect() as conn:
            rows = conn.execute("SELECT * FROM wifi_floor_plans ORDER BY updated_at DESC, id DESC").fetchall()
        return [dict(row) for row in rows]

    def get_floor_plan(self, floor_plan_id: int) -> dict[str, object]:
        with self.database.connect() as conn:
            row = conn.execute("SELECT * FROM wifi_floor_plans WHERE id = ?", (floor_plan_id,)).fetchone()
        if row is None:
            raise KeyError(f"Floor plan not found: {floor_plan_id}")
        return dict(row)

    def update_floor_plan_scale(self, floor_plan_id: int, meter_per_px: float) -> None:
        with self.database.connect() as conn:
            conn.execute(
                "UPDATE wifi_floor_plans SET meter_per_px = ?, updated_at = ? WHERE id = ?",
                (meter_per_px, _now(), floor_plan_id),
            )
            conn.commit()

    def create_session(self, floor_plan_id: int, name: str, adapter_name: str = "", remark: str = "") -> dict[str, object]:
        now = _now()
        with self.database.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO wifi_survey_sessions (
                    floor_plan_id, name, adapter_name, started_at, remark, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (floor_plan_id, name, adapter_name, now, remark, now, now),
            )
            conn.commit()
            return dict(conn.execute("SELECT * FROM wifi_survey_sessions WHERE id = ?", (cursor.lastrowid,)).fetchone())

    def list_sessions(self, floor_plan_id: int | None = None) -> list[dict[str, object]]:
        with self.database.connect() as conn:
            if floor_plan_id is None:
                rows = conn.execute("SELECT * FROM wifi_survey_sessions ORDER BY started_at DESC, id DESC").fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM wifi_survey_sessions WHERE floor_plan_id = ? ORDER BY started_at DESC, id DESC",
                    (floor_plan_id,),
                ).fetchall()
        return [dict(row) for row in rows]

    def create_point(self, session_id: int, point_index: int, x_px: float, y_px: float, meter_per_px: float | None) -> dict[str, object]:
        x_meter = x_px * meter_per_px if meter_per_px else None
        y_meter = y_px * meter_per_px if meter_per_px else None
        with self.database.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO wifi_survey_points (session_id, point_index, x_px, y_px, x_meter, y_meter, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (session_id, point_index, x_px, y_px, x_meter, y_meter, _now()),
            )
            conn.commit()
            return dict(conn.execute("SELECT * FROM wifi_survey_points WHERE id = ?", (cursor.lastrowid,)).fetchone())

    def list_points(self, session_id: int) -> list[dict[str, object]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM wifi_survey_points WHERE session_id = ? ORDER BY point_index ASC, id ASC",
                (session_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def save_observations(self, point_id: int, observations: list[WifiObservation]) -> None:
        with self.database.connect() as conn:
            conn.executemany(
                """
                INSERT INTO wifi_observations (
                    point_id, scan_time, ssid, bssid, rssi_dbm, signal_quality, channel,
                    frequency_mhz, band, security, raw_text, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        point_id,
                        item.scan_time,
                        item.ssid,
                        item.bssid,
                        item.rssi_dbm,
                        item.signal_quality,
                        item.channel,
                        item.frequency_mhz,
                        item.band,
                        item.security,
                        item.raw_text,
                        item.raw_json or json.dumps(item.to_dict(), ensure_ascii=False),
                    )
                    for item in observations
                ],
            )
            conn.commit()

    def list_observations_by_session(self, session_id: int) -> list[dict[str, object]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT p.point_index, p.x_px, p.y_px, p.x_meter, p.y_meter, o.*
                FROM wifi_survey_points p
                LEFT JOIN wifi_observations o ON o.point_id = p.id
                WHERE p.session_id = ?
                ORDER BY p.point_index ASC, o.rssi_dbm DESC
                """,
                (session_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_observations_by_point(self, point_id: int) -> list[dict[str, object]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM wifi_observations WHERE point_id = ? ORDER BY rssi_dbm DESC",
                (point_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_network_tree(self, session_id: int) -> list[dict[str, object]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    COALESCE(NULLIF(o.ssid, ''), '<hidden>') AS ssid,
                    o.bssid,
                    o.channel,
                    MAX(o.rssi_dbm) AS latest_rssi,
                    MAX(o.scan_time) AS last_seen
                FROM wifi_survey_points p
                JOIN wifi_observations o ON o.point_id = p.id
                WHERE p.session_id = ? AND o.bssid IS NOT NULL
                GROUP BY COALESCE(NULLIF(o.ssid, ''), '<hidden>'), o.bssid, o.channel
                ORDER BY ssid, latest_rssi DESC
                """,
                (session_id,),
            ).fetchall()
        return [dict(row) for row in rows]


def _now() -> str:
    return datetime.now().isoformat(sep=" ", timespec="seconds")
