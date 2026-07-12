from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable


class MRDatabase:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS mr_samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    sample_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_mr_samples_session_time
                    ON mr_samples(session_id, timestamp);
                """
            )

    def append_sample(self, session_id: str, timestamp: float, sample_type: str, payload: dict[str, object]) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO mr_samples (session_id, timestamp, sample_type, payload_json) VALUES (?, ?, ?, ?)",
                (session_id, float(timestamp), sample_type, json.dumps(payload, ensure_ascii=False, separators=(",", ":"))),
            )
            return int(cursor.lastrowid)

    def list_samples(self, session_id: str, limit: int = 5000) -> list[dict[str, object]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT timestamp, sample_type, payload_json
                FROM mr_samples
                WHERE session_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (session_id, int(limit)),
            ).fetchall()
        return [
            {"timestamp": row[0], "sample_type": row[1], "payload": json.loads(row[2])}
            for row in reversed(rows)
        ]

    def append_many(self, rows: Iterable[tuple[str, float, str, dict[str, object]]]) -> None:
        with self.connect() as conn:
            conn.executemany(
                "INSERT INTO mr_samples (session_id, timestamp, sample_type, payload_json) VALUES (?, ?, ?, ?)",
                [(session_id, timestamp, sample_type, json.dumps(payload, ensure_ascii=False, separators=(",", ":"))) for session_id, timestamp, sample_type, payload in rows],
            )

    def connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)
