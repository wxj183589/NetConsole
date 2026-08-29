from __future__ import annotations

import json

from netconsole.core.database import Database
from scripts.maintenance.retire_legacy_history_store import prepare


def test_candidate_drops_only_legacy_history_runtime_tables(tmp_path) -> None:
    data_root = tmp_path / "data"
    site_root = data_root / "sites" / "site-a"
    (data_root / "config").mkdir(parents=True)
    (site_root / "db").mkdir(parents=True)
    (data_root / "config" / "site_registry.json").write_text(
        json.dumps(
            {
                "sites": [
                    {
                        "site_id": "site-a",
                        "display_name": "Site A",
                        "relative_path": "sites/site-a",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    source = Database(site_root / "db" / "devices.db")
    source.initialize()
    with source.connect() as conn:
        conn.executescript(
            """
            CREATE TABLE history_outbox (
                event_id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                entity_key TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE history_state (
                kind TEXT NOT NULL,
                entity_key TEXT NOT NULL,
                state_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(kind, entity_key)
            );
            INSERT INTO history_outbox VALUES ('event-1', 'device_fact', 'device-1', '{}', '2026-08-29T00:00:00Z');
            INSERT INTO history_state VALUES ('device_fact', 'device-1', '{}', '2026-08-29T00:00:00Z');
            """
        )
        conn.commit()

    report = prepare(data_root, tmp_path / "candidate")
    item = report["sites"][0]
    assert report["status"] == "PASS"
    assert item["legacy_runtime_tables_removed"] == {
        "history_outbox": 1,
        "history_state": 1,
    }
    assert item["verification"]["legacy_runtime_tables"] == []
