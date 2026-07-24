from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from scripts.maintenance.migrate_unified_data_root import ALLOWED_TARGET_ROOTS, migrate


def _database(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE sample (value TEXT NOT NULL)")
        connection.execute("INSERT INTO sample (value) VALUES (?)", (value,))
        connection.commit()


def test_unified_migration_preserves_conflicts_and_never_changes_sources(tmp_path: Path) -> None:
    primary = tmp_path / "legacy-primary"
    secondary = tmp_path / "legacy-secondary"
    target = tmp_path / "unified"
    bootstrap = tmp_path / "bootstrap.json"
    primary_db = primary / "data" / "sites" / "line-12" / "db" / "devices.db"
    secondary_db = secondary / "data" / "sites" / "line-12" / "db" / "devices.db"
    _database(primary_db, "primary")
    _database(secondary_db, "secondary")
    (primary / "data" / "config").mkdir(parents=True)
    (primary / "data" / "config" / "app.json").write_text(
        '{"current_site":"line-12"}', encoding="utf-8"
    )
    (primary / "data" / "config" / "site_registry.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "sites": [
                    {
                        "site_id": "line-12",
                        "display_name": "十二号线",
                        "relative_path": "data/sites/line-12",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    unique = secondary / "data" / "sites" / "line-12" / "files" / "reports" / "unique.txt"
    unique.parent.mkdir(parents=True)
    unique.write_text("unique", encoding="utf-8")
    bootstrap.write_text(
        '{"schema_version":1,"data_root":"D:\\\\old","active_site_id":"line-12"}',
        encoding="utf-8",
    )
    primary_hash = primary_db.read_bytes()
    secondary_hash = secondary_db.read_bytes()

    report = migrate(target, primary, [secondary], desktop_bootstrap=bootstrap)

    assert report.status == "completed"
    assert primary_db.read_bytes() == primary_hash
    assert secondary_db.read_bytes() == secondary_hash
    assert (target / "sites" / "line-12" / "db" / "devices.db").read_bytes() == primary_hash
    assert (target / "sites" / "line-12" / "files" / "reports" / "unique.txt").read_text(encoding="utf-8") == "unique"
    conflicts = list((target / "migrations" / "conflicts" / "source-1").rglob("devices.db"))
    assert len(conflicts) == 1
    assert conflicts[0].read_bytes() == secondary_hash
    assert json.loads((target / "config" / "site_registry.json").read_text(encoding="utf-8"))["sites"][0]["relative_path"] == "sites/line-12"
    assert json.loads((target / "runtime" / "electron" / "user-data" / "bootstrap.json").read_text(encoding="utf-8"))["data_root"] == str(target.resolve())
    assert not any((target / "staging").iterdir())
    assert {item.name for item in target.iterdir()} == ALLOWED_TARGET_ROOTS
