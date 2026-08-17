from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from netconsole.core.paths import PathResolver
from netconsole.services.database_footprint_maintenance import (
    DevelopmentDatabaseCompactService,
    assert_development_path,
    resolve_registered_active_site_readonly,
    sqlite_online_backup_readonly,
    sqlite_quick_profile,
)
from netconsole.services import database_footprint_maintenance as maintenance_module
from scripts.maintenance.rehearse_database_footprint import main as rehearsal_main
from scripts.maintenance.rehearse_database_footprint import _cleanup_sqlite_sidecars


def _database(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript(
            "CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT NOT NULL);"
            "INSERT INTO records(value) VALUES ('one'), ('two'), ('three');"
        )
    return path


def test_readonly_registered_active_site_resolution_has_no_side_effects(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    site_root = data_root / "sites" / "line-12"
    _database(site_root / "db" / "devices.db")
    _database(site_root / "db" / "tasks.db")
    config = data_root / "config"
    config.mkdir(parents=True)
    application = config / "application.json"
    registry = config / "site_registry.json"
    application.write_text(
        json.dumps({"current_site": "Line 12"}), encoding="utf-8"
    )
    registry.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "sites": [
                    {
                        "site_id": "line-12",
                        "display_name": "Line 12",
                        "relative_path": "sites/line-12",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    before = {path: path.read_bytes() for path in (application, registry)}

    record = resolve_registered_active_site_readonly(
        PathResolver(app_root=tmp_path, data_root=data_root)
    )

    assert record.site_id == "line-12"
    assert record.root_path == site_root.resolve()
    assert before == {path: path.read_bytes() for path in (application, registry)}


def test_readonly_online_backup_and_compact_replace_rollback(tmp_path: Path) -> None:
    source = _database(tmp_path / "source.db")
    snapshot = tmp_path / "run" / "snapshot.db"
    snapshot_result = sqlite_online_backup_readonly(
        source, snapshot, development_root=tmp_path
    )
    assert snapshot_result["quick_check"] == "ok"
    assert snapshot_result["table_counts"] == {"records": 3}
    assert not snapshot.with_name(f"{snapshot.name}-wal").exists()
    assert not snapshot.with_name(f"{snapshot.name}-shm").exists()

    with closing(sqlite3.connect(snapshot)) as connection:
        connection.execute("DELETE FROM records WHERE id = 2")
        connection.commit()
    before = sqlite_quick_profile(snapshot)
    compacted = tmp_path / "run" / "compacted.db"
    service = DevelopmentDatabaseCompactService(
        PathResolver(app_root=tmp_path, data_root=tmp_path / "maintenance"),
        site_id="line-12",
        development_root=tmp_path,
    )
    result = service.compact(snapshot, compacted)
    assert result.after["size_bytes"] <= result.before["size_bytes"]
    rollback = tmp_path / "run" / "snapshot.db.pre-compact"
    replacement = service.replace(snapshot, compacted, rollback)
    assert replacement["replaced"] is True
    assert sqlite_quick_profile(snapshot)["table_counts"] == {"records": 2}
    restored = service.rollback(snapshot, rollback)
    assert restored["rolled_back"] is True
    assert sqlite_quick_profile(snapshot)["table_counts"] == {"records": 2}
    assert before["schema_digest"] == sqlite_quick_profile(snapshot)["schema_digest"]


def test_site_package_staging_sidecars_are_removed_after_closed_owner(tmp_path: Path) -> None:
    database = _database(tmp_path / "site-package" / "tasks.db")
    for suffix in ("-wal", "-shm"):
        database.with_name(f"{database.name}{suffix}").write_bytes(b"staging")

    _cleanup_sqlite_sidecars(database)

    assert not database.with_name(f"{database.name}-wal").exists()
    assert not database.with_name(f"{database.name}-shm").exists()


def test_compact_replace_failure_keeps_active_database_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _database(tmp_path / "source.db")
    compacted = tmp_path / "compacted.db"
    service = DevelopmentDatabaseCompactService(
        PathResolver(app_root=tmp_path, data_root=tmp_path / "maintenance"),
        site_id="line-12",
        development_root=tmp_path,
    )
    service.compact(source, compacted)
    rollback = tmp_path / "source.rollback.db"
    original_replace = os.replace

    def fail_candidate_replace(src: str | Path, dst: str | Path) -> None:
        if Path(src) == compacted and Path(dst) == source:
            raise OSError("injected candidate replace failure")
        original_replace(src, dst)

    monkeypatch.setattr(maintenance_module.os, "replace", fail_candidate_replace)
    with pytest.raises(OSError, match="injected candidate"):
        service.replace(source, compacted, rollback)

    assert source.is_file()
    assert compacted.is_file()
    assert sqlite_quick_profile(source)["table_counts"] == {"records": 3}


def test_compact_rollback_failure_keeps_current_and_rollback_authorities(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _database(tmp_path / "source.db")
    compacted = tmp_path / "compacted.db"
    rollback = tmp_path / "source.rollback.db"
    service = DevelopmentDatabaseCompactService(
        PathResolver(app_root=tmp_path, data_root=tmp_path / "maintenance"),
        site_id="line-12",
        development_root=tmp_path,
    )
    with closing(sqlite3.connect(source)) as connection:
        connection.execute("DELETE FROM records WHERE id = 2")
        connection.commit()
    service.compact(source, compacted)
    service.replace(source, compacted, rollback)
    original_replace = os.replace

    def fail_rollback_replace(src: str | Path, dst: str | Path) -> None:
        if Path(src) == rollback and Path(dst) == source:
            raise OSError("injected rollback replace failure")
        original_replace(src, dst)

    monkeypatch.setattr(maintenance_module.os, "replace", fail_rollback_replace)
    with pytest.raises(OSError, match="injected rollback"):
        service.rollback(source, rollback)

    assert source.is_file()
    assert rollback.is_file()
    assert sqlite_quick_profile(source)["table_counts"] == {"records": 2}
    assert sqlite_quick_profile(rollback)["table_counts"] == {"records": 2}


def test_compact_replace_refuses_live_wal_sidecars(tmp_path: Path) -> None:
    source = _database(tmp_path / "source.db")
    compacted = tmp_path / "compacted.db"
    service = DevelopmentDatabaseCompactService(
        PathResolver(app_root=tmp_path, data_root=tmp_path / "maintenance"),
        site_id="line-12",
        development_root=tmp_path,
    )
    service.compact(source, compacted)
    writer = sqlite3.connect(source)
    try:
        assert str(writer.execute("PRAGMA journal_mode=WAL").fetchone()[0]).lower() == "wal"
        writer.execute("INSERT INTO records(value) VALUES ('uncheckpointed')")
        writer.commit()
        assert source.with_name(f"{source.name}-wal").stat().st_size > 0
        with pytest.raises(sqlite3.OperationalError, match="sidecars"):
            service.replace(source, compacted, tmp_path / "source.rollback.db")
    finally:
        writer.close()

    assert source.is_file()
    assert compacted.is_file()


def test_compact_replace_cleans_closed_wal_sidecars_and_allows_rollback(
    tmp_path: Path,
) -> None:
    source = _database(tmp_path / "source.db")
    compacted = tmp_path / "compacted.db"
    rollback = tmp_path / "source.rollback.db"
    service = DevelopmentDatabaseCompactService(
        PathResolver(app_root=tmp_path, data_root=tmp_path / "maintenance"),
        site_id="line-12",
        development_root=tmp_path,
    )
    service.compact(source, compacted)
    source.with_name(f"{source.name}-wal").write_bytes(b"")
    source.with_name(f"{source.name}-shm").write_bytes(b"\0" * 32768)

    service.replace(source, compacted, rollback)
    restored = service.rollback(source, rollback)

    assert restored["rolled_back"] is True
    assert not source.with_name(f"{source.name}-wal").exists()
    assert not source.with_name(f"{source.name}-shm").exists()


def test_development_path_guard_fails_closed(tmp_path: Path) -> None:
    assert assert_development_path(
        tmp_path / "allowed.db", development_root=tmp_path
    ) == (tmp_path / "allowed.db").resolve()
    with pytest.raises(ValueError, match="development root itself"):
        assert_development_path(tmp_path, development_root=tmp_path)
    with pytest.raises(ValueError, match="must be under"):
        assert_development_path(tmp_path.parent / "outside.db", development_root=tmp_path)


def test_rehearsal_cli_creates_readonly_snapshots_and_working_copies(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "production"
    site_root = data_root / "sites" / "line-12"
    _database(site_root / "db" / "devices.db")
    _database(site_root / "db" / "tasks.db")
    config = data_root / "config"
    config.mkdir(parents=True)
    application = config / "application.json"
    registry = config / "site_registry.json"
    application.write_text(
        json.dumps({"current_site": "line-12"}), encoding="utf-8"
    )
    registry.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "sites": [
                    {
                        "site_id": "line-12",
                        "display_name": "Line 12",
                        "relative_path": "sites/line-12",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    before = {path: path.read_bytes() for path in (application, registry)}
    run_root = tmp_path / "run"
    diagnostics = tmp_path / "diagnostics"

    assert rehearsal_main(
        [
            "snapshot",
            "--production-data-root",
            str(data_root),
            "--run-root",
            str(run_root),
            "--diagnostics-dir",
            str(diagnostics),
        ]
    ) == 0
    assert rehearsal_main(
        ["prepare-rehearsal", "--run-root", str(run_root)]
    ) == 0

    assert before == {path: path.read_bytes() for path in (application, registry)}
    assert (diagnostics / "RESOLVED_SITE.json").is_file()
    for path in (
        run_root / "source" / "devices.db",
        run_root / "source" / "tasks.db",
        run_root / "devices-rehearsal" / "devices.db",
        run_root / "tasks-rehearsal" / "tasks.db",
    ):
        assert sqlite_quick_profile(path)["quick_check"] == "ok"
    assert (run_root / "devices-rehearsal" / "history").is_dir()
