from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

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
                    raw TEXT,
                    source_identity TEXT,
                    raw_file TEXT,
                    raw_sha256 TEXT,
                    raw_offset_start INTEGER,
                    raw_offset_end INTEGER
                )
                """
            )
            columns = {
                str(row[1])
                for row in conn.execute("PRAGMA table_info(event_stream)").fetchall()
            }
            for name, definition in (
                ("source_identity", "TEXT"),
                ("raw_file", "TEXT"),
                ("raw_sha256", "TEXT"),
                ("raw_offset_start", "INTEGER"),
                ("raw_offset_end", "INTEGER"),
            ):
                if name not in columns:
                    conn.execute(f"ALTER TABLE event_stream ADD COLUMN {name} {definition}")
            conn.execute(
                "UPDATE event_stream SET source_identity = 'legacy:' || id "
                "WHERE source_identity IS NULL OR source_identity = ''"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_event_stream_session_time ON event_stream(session_id, event_time)")
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_event_stream_source_identity "
                "ON event_stream(source_identity) WHERE source_identity IS NOT NULL AND source_identity <> ''"
            )

    def write_event_to_db(self, event: OnlineMrEvent) -> None:
        raw = str(event.raw or "")
        payload = dict(event.payload or {})
        raw_file = str(payload.get("raw_file") or "").strip()
        if not raw_file:
            raw_file = f"raw/{event.module or event.source}.log"
        raw_offset_start = _optional_int(
            payload.get("offset_start", payload.get("raw_offset_start"))
        )
        raw_offset_end = _optional_int(
            payload.get("offset_end", payload.get("raw_offset_end"))
        )
        raw_sha256 = hashlib.sha256(raw.encode("utf-8")).hexdigest() if raw else ""
        source_identity = _source_identity(
            event,
            raw_file=raw_file,
            raw_sha256=raw_sha256,
            raw_offset_start=raw_offset_start,
            raw_offset_end=raw_offset_end,
        )
        # Raw evidence remains in the session/artifact owner.  Keep only parsed
        # payload facts and a reference/hash in this derived event index.
        payload.pop("raw", None)
        payload["raw_file"] = raw_file
        payload["raw_sha256"] = raw_sha256
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO event_stream (
                    event_time, session_id, device_id, source, module, event_type,
                    payload_json, raw, source_identity, raw_file, raw_sha256,
                    raw_offset_start, raw_offset_end
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT DO UPDATE SET
                    event_time=excluded.event_time,
                    session_id=excluded.session_id,
                    device_id=excluded.device_id,
                    source=excluded.source,
                    module=excluded.module,
                    event_type=excluded.event_type,
                    payload_json=excluded.payload_json,
                    raw=NULL,
                    raw_file=excluded.raw_file,
                    raw_sha256=excluded.raw_sha256,
                    raw_offset_start=excluded.raw_offset_start,
                    raw_offset_end=excluded.raw_offset_end
                """,
                (
                    event.timestamp.isoformat(sep=" ", timespec="milliseconds"),
                    event.session_id,
                    event.device_id,
                    event.source,
                    event.module,
                    event.event_type,
                    json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True),
                    None,
                    source_identity,
                    raw_file,
                    raw_sha256,
                    raw_offset_start,
                    raw_offset_end,
                ),
            )


def _source_identity(
    event: OnlineMrEvent,
    *,
    raw_file: str,
    raw_sha256: str,
    raw_offset_start: int | None,
    raw_offset_end: int | None,
) -> str:
    material: dict[str, Any] = {
        "session_id": event.session_id,
        "device_id": event.device_id,
        "source": event.source,
        "module": event.module,
        "event_type": event.event_type,
        "raw_file": raw_file,
        "raw_sha256": raw_sha256,
        "raw_offset_start": raw_offset_start,
        "raw_offset_end": raw_offset_end,
    }
    if raw_offset_start is None and raw_offset_end is None:
        material["event_time"] = event.timestamp.isoformat(timespec="microseconds")
    if not raw_sha256:
        material["payload"] = event.payload
    encoded = json.dumps(material, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _optional_int(value: object) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None
