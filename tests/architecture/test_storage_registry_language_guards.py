from __future__ import annotations

import json
from pathlib import Path

from scripts.architecture.checks import storage_registry_findings


def _registry(path: Path, *, source: str, database: str) -> Path:
    value = {
        "version": 1,
        "unknown_policy": "PROTECT",
        "data_classes": ["OPERATIONAL_CURRENT", "UNKNOWN"],
        "infrastructure_locations": [],
        "stores": [
            {
                "id": "test.current",
                "relative_path": database,
                "owner": "test",
                "data_type": "OPERATIONAL_CURRENT",
                "authority": "test authority",
                "producer": ["test producer"],
                "consumers": ["test consumer"],
                "retention_owner": "test owner",
                "rebuildable": False,
                "site_package_policy": "include",
                "backup_policy": "owner managed",
                "migration_policy": "owner managed recovery",
                "schema_version": 1,
                "allowed_data_classes": ["OPERATIONAL_CURRENT"],
                "forbidden_data_classes": ["UNKNOWN"],
                "source_locations": [source],
            }
        ],
    }
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _direct_sql(path: Path) -> Path:
    path.write_text("[]\n", encoding="utf-8")
    return path


def test_storage_registry_guard_scans_go_and_electron_sources(tmp_path: Path) -> None:
    go_source = tmp_path / "agent" / "store.go"
    go_source.parent.mkdir()
    go_source.write_text(
        'package agent\nimport _ "modernc.org/sqlite"\nconst path = "agent-state.db"\n',
        encoding="utf-8",
    )
    electron_source = tmp_path / "electron" / "store.ts"
    electron_source.parent.mkdir()
    electron_source.write_text(
        "import { DatabaseSync } from 'node:sqlite'\nnew DatabaseSync('desktop.sqlite')\n",
        encoding="utf-8",
    )
    registry = _registry(
        tmp_path / "registry.json",
        source="some/other/source.py",
        database="sites/{site_id}/db/devices.db",
    )

    findings = storage_registry_findings(
        registry,
        source_roots=[go_source.parent, electron_source.parent],
        direct_sql_path=_direct_sql(tmp_path / "direct.json"),
    )

    unregistered = [item for item in findings if item.rule_id == "UNREGISTERED_STORAGE"]
    assert {Path(item.path).name for item in unregistered} == {"store.go", "store.ts"}
    assert any("non-Python source" in item.message for item in unregistered)


def test_storage_registry_guard_rejects_second_database_in_registered_source(
    tmp_path: Path,
) -> None:
    source = tmp_path / "registered_store.py"
    source.write_text(
        "import sqlite3\n"
        "sqlite3.connect('known.db')\n"
        "sqlite3.connect('rogue.db')\n",
        encoding="utf-8",
    )
    registry = _registry(
        tmp_path / "registry.json",
        source=source.as_posix(),
        database="sites/{site_id}/db/known.db",
    )

    findings = storage_registry_findings(
        registry,
        source_roots=[tmp_path],
        direct_sql_path=_direct_sql(tmp_path / "direct.json"),
    )

    unregistered = [item for item in findings if item.rule_id == "UNREGISTERED_STORAGE"]
    assert len(unregistered) == 1
    assert unregistered[0].path == source.as_posix()
    assert "rogue.db" in unregistered[0].message
    assert "physical database declaration" in unregistered[0].message


def test_storage_registry_guard_does_not_borrow_wildcard_from_another_store(
    tmp_path: Path,
) -> None:
    source = tmp_path / "registered_store.py"
    source.write_text(
        "import sqlite3\n"
        "sqlite3.connect('known.db')\n"
        "sqlite3.connect('analysis.sqlite')\n",
        encoding="utf-8",
    )
    registry_path = _registry(
        tmp_path / "registry.json",
        source=source.as_posix(),
        database="sites/{site_id}/db/known.db",
    )
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    wildcard = dict(registry["stores"][0])
    wildcard.update(
        {
            "id": "other.wildcard",
            "relative_path": "sites/{site_id}/sessions/*.sqlite",
            "source_locations": [(tmp_path / "other_store.py").as_posix()],
        }
    )
    (tmp_path / "other_store.py").write_text(
        "import sqlite3\nsqlite3.connect('session.sqlite')\n",
        encoding="utf-8",
    )
    registry["stores"].append(wildcard)
    registry_path.write_text(json.dumps(registry), encoding="utf-8")

    findings = storage_registry_findings(
        registry_path,
        source_roots=[tmp_path],
        direct_sql_path=_direct_sql(tmp_path / "direct.json"),
    )

    assert any(
        item.rule_id == "UNREGISTERED_STORAGE"
        and item.path == source.as_posix()
        and "analysis.sqlite" in item.message
        for item in findings
    )


def test_storage_registry_guard_requires_explicit_unknown_active_producer(
    tmp_path: Path,
) -> None:
    source = tmp_path / "unknown_store.py"
    source.write_text("import sqlite3\nsqlite3.connect('unknown.db')\n", encoding="utf-8")
    registry = json.loads(_registry(
        tmp_path / "registry.json",
        source=source.as_posix(),
        database="sites/{site_id}/db/unknown.db",
    ).read_text(encoding="utf-8"))
    store = registry["stores"][0]
    store["data_type"] = "UNKNOWN"
    store["authority"] = "UNKNOWN_PROTECT"
    store["retention_owner"] = "UNKNOWN_PROTECT"
    store["allowed_data_classes"] = ["UNKNOWN"]
    store["forbidden_data_classes"] = []
    registry_path = tmp_path / "unknown-registry.json"
    registry_path.write_text(json.dumps(registry), encoding="utf-8")

    findings = storage_registry_findings(
        registry_path,
        source_roots=[tmp_path],
        direct_sql_path=_direct_sql(tmp_path / "direct.json"),
    )

    assert any(
        item.rule_id == "STORAGE_UNKNOWN_ACTIVE_PRODUCER"
        and "boolean active_producer" in item.message
        for item in findings
    )
