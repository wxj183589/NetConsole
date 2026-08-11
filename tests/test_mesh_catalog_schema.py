from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from netconsole.repositories.mesh_catalog_repository import MeshCatalogRepository
from netconsole.repositories.mesh_catalog_schema import CATALOG_SCHEMA_VERSION


def _open_catalog(path: Path) -> str:
    MeshCatalogRepository(path)
    with sqlite3.connect(path) as connection:
        return str(
            connection.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()[0]
        )


def test_catalog_schema_migration_serializes_concurrent_severity_upgrade(
    tmp_path: Path,
) -> None:
    path = tmp_path / "catalog.sqlite"
    MeshCatalogRepository(path)
    with sqlite3.connect(path) as connection:
        connection.execute("DROP INDEX IF EXISTS idx_mesh_session_index_warning")
        for column in (
            "info_count",
            "warning_count",
            "error_count",
            "actionable_warning_count",
        ):
            connection.execute(
                f"ALTER TABLE mesh_session_index DROP COLUMN {column}"
            )
        connection.execute("DELETE FROM schema_meta WHERE key = 'schema_version'")
        connection.commit()

    with ThreadPoolExecutor(max_workers=8) as executor:
        versions = list(executor.map(_open_catalog, [path] * 16))

    assert versions == [CATALOG_SCHEMA_VERSION] * 16
    with sqlite3.connect(path) as connection:
        columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(mesh_session_index)"
            ).fetchall()
        }
        version = connection.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        ).fetchone()[0]
    assert {
        "info_count",
        "warning_count",
        "error_count",
        "actionable_warning_count",
    } <= columns
    assert version == CATALOG_SCHEMA_VERSION
