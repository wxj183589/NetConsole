from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from netconsole.core.database import Database
from scripts.maintenance import retire_legacy_history_store as retirement
from scripts.maintenance.retire_legacy_history_store import _sqlite_backup, prepare


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
    conn = source.connect()
    try:
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
    finally:
        conn.close()

    report = prepare(data_root, tmp_path / "candidate")
    item = report["sites"][0]
    assert report["status"] == "PASS"
    assert item["legacy_runtime_tables_removed"] == {
        "history_outbox": 1,
        "history_state": 1,
    }
    assert item["verification"]["legacy_runtime_tables"] == []

    candidate_db = item["candidate_database"]
    copied_db = tmp_path / "copied-main.db"
    _sqlite_backup(Path(candidate_db), copied_db)
    with sqlite3.connect(copied_db) as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert not {"history_outbox", "history_state"} & tables


def test_development_apply_retires_only_empty_legacy_runtime_store(
    tmp_path, monkeypatch
) -> None:
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
    conn = source.connect()
    try:
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
            """
        )
        conn.commit()
    finally:
        conn.close()

    candidate_root = tmp_path / "candidate"
    report = retirement.prepare(data_root, candidate_root)
    assert report["status"] == "PASS"
    monkeypatch.setattr(retirement, "TARGET_DEVELOPMENT_ROOT", data_root.resolve())
    temporary_backup = tmp_path / "temporary-backup"
    applied = retirement.apply_development(data_root, candidate_root, temporary_backup)

    assert applied["status"] == "PASS"
    assert applied["temporary_backup_retired"] is True
    assert not temporary_backup.exists()
    assert not (site_root / "db" / "history").exists()
    with source.connect_readonly() as conn:
        tables = {
            str(row[0])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "history_outbox" not in tables
        assert "history_state" not in tables


def test_development_apply_rejects_non_empty_history_store(tmp_path, monkeypatch) -> None:
    data_root = tmp_path / "data"
    site_root = data_root / "sites" / "site-a"
    (data_root / "config").mkdir(parents=True)
    (site_root / "db" / "history").mkdir(parents=True)
    (data_root / "config" / "site_registry.json").write_text(
        json.dumps({"sites": [{"site_id": "site-a", "relative_path": "sites/site-a"}]}),
        encoding="utf-8",
    )
    source = Database(site_root / "db" / "devices.db")
    source.initialize()
    (site_root / "db" / "history" / "catalog.db").write_bytes(b"protected")

    candidate_root = tmp_path / "candidate"
    retirement.prepare(data_root, candidate_root)
    monkeypatch.setattr(retirement, "TARGET_DEVELOPMENT_ROOT", data_root.resolve())
    with pytest.raises(RuntimeError, match="non-empty external HistoryStore"):
        retirement.apply_development(data_root, candidate_root, tmp_path / "temporary-backup")
