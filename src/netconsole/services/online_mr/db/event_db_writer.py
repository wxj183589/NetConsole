from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from netconsole.services.online_mr.event_bus import OnlineMrEvent


class OnlineMrEventDbWriter:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.initialize()

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS event_stream (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_time TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    device_id INTEGER,
                    source TEXT NOT NULL,
                    module TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    raw TEXT
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_event_stream_session_time ON event_stream(session_id, event_time)")

    def write_event_to_db(self, event: OnlineMrEvent) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO event_stream (
                    event_time, session_id, device_id, source, module, event_type, payload_json, raw
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.timestamp.isoformat(sep=" ", timespec="milliseconds"),
                    event.session_id,
                    event.device_id,
                    event.source,
                    event.module,
                    event.event_type,
                    json.dumps(event.payload, ensure_ascii=False, default=str),
                    event.raw,
                ),
            )
