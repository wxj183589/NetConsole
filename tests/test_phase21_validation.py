from __future__ import annotations

import json
from pathlib import Path

from netconsole.core.database import Database
from netconsole.services.history_store import HistoryStore
from scripts.maintenance.diagnose_server_hdd import collect_report
from scripts.maintenance.validate_phase21_snapshot import validate_snapshot


def test_synthetic_current_schema_fast_path_and_history_are_isolated(tmp_path: Path) -> None:
    database_path = tmp_path / "sites" / "snapshot" / "db" / "devices.db"
    database = Database(database_path)
    database.initialize()
    store = HistoryStore(database_path, site_id="snapshot")
    with database.connect() as connection:
        assert store.record_event(
            connection,
            kind="device_interface",
            entity_key="device-1:GE1/0/1",
            payload={"device_uuid": "device-1", "link_status": "up"},
            collected_at="2026-08-01T00:00:00",
            meaningful_fields=("device_uuid", "link_status"),
        )
        connection.commit()
    assert store.drain(limit=1).written == 1
    before = database_path.stat().st_size
    database.initialize()
    assert database_path.stat().st_size == before
    assert store.count_events(kind="device_interface") == 1
    assert not (database_path.parent / "history" / "migration.db").exists()


def test_validation_without_offline_copy_is_explicitly_not_executed(tmp_path: Path) -> None:
    result = validate_snapshot(tmp_path / "missing-devices.db")
    assert result["status"] == "NOT_EXECUTED"
    assert result["reason"] == "OFFLINE_SNAPSHOT_NOT_AVAILABLE"


def test_diagnostic_report_is_read_only_and_tolerates_missing_database(tmp_path: Path) -> None:
    report = collect_report(database=tmp_path / "missing.db", disk_path=tmp_path)
    assert report["readonly"] is True
    assert report["database"]["exists"] is False
    assert report["disk_counters"]["active_time_percent"] == "unknown"
    assert json.dumps(report, ensure_ascii=False)
