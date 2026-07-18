from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping
from pathlib import Path


OPTICAL_RESULTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS optical_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_name TEXT,
    device_ip TEXT,
    device_type TEXT,
    group_name TEXT,
    interface_name TEXT,
    module_type TEXT,
    rx_power TEXT,
    tx_power TEXT,
    rx_status TEXT,
    tx_status TEXT,
    collected_at TEXT,
    raw_log_path TEXT,
    error_message TEXT
)
"""

INSERT_OPTICAL_RESULT = """
INSERT INTO optical_results (
    device_name, device_ip, device_type, group_name, interface_name, module_type,
    rx_power, tx_power, rx_status, tx_status, collected_at, raw_log_path, error_message
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


class TracksideOpticalResultRepository:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def append_rows(self, rows: Iterable[Mapping[str, object | None]]) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(OPTICAL_RESULTS_SCHEMA)
            for row in rows:
                conn.execute(
                    INSERT_OPTICAL_RESULT,
                    (
                        row.get("device_name"),
                        row.get("device_ip"),
                        row.get("device_type"),
                        row.get("group_name"),
                        row.get("interface_name"),
                        row.get("module_model"),
                        row.get("rx_power"),
                        row.get("tx_power"),
                        row.get("optical_alarm_status"),
                        row.get("tx_status"),
                        row.get("collected_at"),
                        row.get("raw_log_path"),
                        row.get("error_message"),
                    ),
                )
            conn.commit()
