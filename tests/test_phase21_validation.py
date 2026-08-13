from __future__ import annotations

import json
import sys
from pathlib import Path

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.core.runtime_profile import (
    HostEnvironmentProfile,
    ProfileValue,
    write_host_environment_profile,
)
from netconsole.services.history_store import HistoryStore
from scripts.maintenance.diagnose_server_hdd import _startup_events, collect_report
from scripts.maintenance.validate_phase21_snapshot import (
    _default_work_root,
    _run_isolated_backend,
    validate_snapshot,
)


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


def test_diagnostic_outbox_pending_uses_count_and_created_at_without_deep_history_scan(tmp_path: Path) -> None:
    database_path = tmp_path / "devices.db"
    database = Database(database_path)
    database.initialize()
    store = HistoryStore(database_path, site_id="demo")
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
    report = collect_report(database=database_path, disk_path=tmp_path)
    assert report["database"]["deep"] is False
    assert report["database"]["history_pending"] == 1
    assert report["database"]["history_oldest_pending"]
    assert "history_table_counts" not in report["database"]
    deep_report = collect_report(database=database_path, disk_path=tmp_path, deep=True)
    assert deep_report["database"]["history_table_counts"]["history_outbox"] == 1


def test_startup_parser_accepts_electron_pipe_and_python_json(tmp_path: Path) -> None:
    log = tmp_path / "electron.log"
    log.write_text(
        "2026-08-13T10:00:00Z | INFO | ELECTRON_BACKEND_FIRST_STDOUT | pid=123\n"
        "2026-08-13T10:00:01Z | INFO | ELECTRON_BACKEND_STARTUP_STAGE | active_site_database_ready\n"
        '{"event":"netconsole.electron_backend.startup_stage","stage":"listener_ready","elapsed_ms":42}\n'
        '{"event":"netconsole.electron_backend.ready","elapsed_ms":55}\n',
        encoding="utf-8",
    )
    report = _startup_events(log)
    assert [event["event"] for event in report["events"]] == [
        "ELECTRON_BACKEND_FIRST_STDOUT",
        "ELECTRON_BACKEND_STARTUP_STAGE",
        "ELECTRON_BACKEND_STARTUP_STAGE",
        "ELECTRON_BACKEND_READY",
    ]


def test_diagnostic_uses_existing_host_profile_for_ram(tmp_path: Path) -> None:
    database_path = tmp_path / "sites" / "demo" / "db" / "devices.db"
    Database(database_path).initialize()
    profile_path = tmp_path / "runtime" / "environment" / "host-profile.json"
    write_host_environment_profile(
        profile_path,
        HostEnvironmentProfile(
            memory={"bytes": ProfileValue(16 * 1024**3, "installer", "high")}
        ),
    )
    report = collect_report(database=database_path, disk_path=tmp_path)
    assert report["host"]["profile_status"] == "ready"
    assert report["host"]["memory"]["bytes"] == 16 * 1024**3


def test_isolated_backend_rejects_real_data_root(tmp_path: Path) -> None:
    result = _run_isolated_backend(Path(r"D:\NetConsoleData"))
    assert result == {"status": "NOT_EXECUTED", "reason": "REAL_DATA_ROOT_REJECTED"}


def test_default_validation_root_is_an_isolated_test_run(tmp_path: Path) -> None:
    root = _default_work_root()
    if sys.platform == "win32":
        assert root.parent == Path(r"D:\NetConsoleTestData").resolve()
    assert root != Path(r"D:\NetConsoleData").resolve()


def test_isolated_backend_listener_and_health_use_only_test_root(tmp_path: Path) -> None:
    paths = PathResolver(data_root=tmp_path)
    paths.ensure_site_dirs("snapshot")
    Database(paths.site_db_path("snapshot")).initialize()

    result = _run_isolated_backend(tmp_path)

    assert result["status"] == "PASS"
    assert result["health_status"] == "ok"
    assert result["exit_code"] == 0
    assert float(result["backend_ready_ms"]) > 0
