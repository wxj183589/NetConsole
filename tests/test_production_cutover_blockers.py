from __future__ import annotations

import json
from pathlib import Path

from scripts.maintenance.migrate_task_result_blobs import _resolve
from netconsole.storage.lldp_optical_retention_migration import _active_sites


def _registry(root: Path) -> None:
    (root / "config").mkdir(parents=True)
    (root / "sites" / "registered" / "db").mkdir(parents=True)
    (root / "sites" / "x" / "db").mkdir(parents=True)
    (root / "sites" / "registered" / "db" / "devices.db").write_bytes(b"registered")
    (root / "sites" / "registered" / "db" / "tasks.db").write_bytes(b"registered")
    (root / "sites" / "x" / "db" / "devices.db").write_bytes(b"unregistered")
    (root / "sites" / "x" / "db" / "tasks.db").write_bytes(b"unregistered")
    (root / "config" / "site_registry.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "sites": [
                    {
                        "site_id": "registered-site",
                        "display_name": "Registered",
                        "relative_path": "sites/registered",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_task_blob_migration_resolves_only_registered_sites(tmp_path: Path) -> None:
    _registry(tmp_path)

    resolved = _resolve(tmp_path, None, True)

    assert resolved == [("registered-site", tmp_path / "sites" / "registered" / "db" / "tasks.db")]


def test_engineering_migration_resolves_only_registered_sites(tmp_path: Path) -> None:
    root = tmp_path / "NetConsoleData-dev"
    _registry(root)

    resolved = _active_sites(root, None)

    assert resolved == [("registered-site", root / "sites" / "registered" / "db" / "devices.db")]
