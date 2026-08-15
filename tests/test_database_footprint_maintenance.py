from __future__ import annotations

import json
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


def _database(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
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

    with closing(sqlite3.connect(snapshot)) as connection:
        connection.execute("DELETE FROM records WHERE id = 2")
        connection.commit()
    before = sqlite_quick_profile(snapshot)
    compacted = tmp_path / "run" / "compacted.db"
    service = DevelopmentDatabaseCompactService(development_root=tmp_path)
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


def test_development_path_guard_fails_closed(tmp_path: Path) -> None:
    assert assert_development_path(
        tmp_path / "allowed.db", development_root=tmp_path
    ) == (tmp_path / "allowed.db").resolve()
    with pytest.raises(ValueError, match="development root itself"):
        assert_development_path(tmp_path, development_root=tmp_path)
    with pytest.raises(ValueError, match="must be under"):
        assert_development_path(tmp_path.parent / "outside.db", development_root=tmp_path)
