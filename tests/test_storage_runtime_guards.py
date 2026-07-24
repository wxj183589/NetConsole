from __future__ import annotations

import json
from pathlib import Path

import pytest

from netconsole.core.backend_instance_lock import BackendInstanceInUseError, BackendInstanceLock
from netconsole.core.paths import PathResolver
from netconsole.core.storage_manifest import (
    CURRENT_STORAGE_SCHEMA_VERSION,
    StorageCompatibilityError,
    StorageMigrationConfirmationRequired,
    prepare_storage_manifest,
)
from netconsole.core.version import APP_VERSION


def _paths(tmp_path: Path) -> PathResolver:
    return PathResolver(app_root=tmp_path / "app", data_root=tmp_path / "data-root")


def test_backend_instance_lock_records_owner_and_reclaims_after_release(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    first = BackendInstanceLock(paths)
    second = BackendInstanceLock(paths)

    first.acquire()
    owner = json.loads(first.path.read_text(encoding="utf-8"))
    assert set(owner) == {"pid", "started_at", "version", "executable", "data_root"}
    assert owner["version"] == APP_VERSION
    assert owner["data_root"] == str(paths.data_root)
    with pytest.raises(BackendInstanceInUseError, match="另一个 NetConsole Backend"):
        second.acquire()

    first.release()
    second.acquire()
    second.release()


def test_storage_manifest_is_created_and_updated_without_schema_migration(tmp_path: Path) -> None:
    paths = _paths(tmp_path)

    created = prepare_storage_manifest(paths)
    opened = prepare_storage_manifest(paths)

    assert created.schema_version == CURRENT_STORAGE_SCHEMA_VERSION
    assert opened.minimum_app_version == APP_VERSION
    assert opened.last_opened_app_version == APP_VERSION
    assert json.loads(paths.storage_manifest_path.read_text(encoding="utf-8"))["migration_id"] == ""


def test_storage_manifest_rejects_newer_schema_and_older_app(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    paths.config_dir.mkdir(parents=True)
    paths.storage_manifest_path.write_text(
        json.dumps(
            {
                "schema_version": CURRENT_STORAGE_SCHEMA_VERSION + 1,
                "minimum_app_version": APP_VERSION,
                "last_opened_app_version": APP_VERSION,
                "last_migration_time": "",
                "migration_id": "future",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(StorageCompatibilityError, match="高于当前应用"):
        prepare_storage_manifest(paths)

    paths.storage_manifest_path.write_text(
        json.dumps(
            {
                "schema_version": CURRENT_STORAGE_SCHEMA_VERSION,
                "minimum_app_version": "v99.0.0",
                "last_opened_app_version": "v99.0.0",
                "last_migration_time": "",
                "migration_id": "future-version",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(StorageCompatibilityError, match="最低版本"):
        prepare_storage_manifest(paths)


def test_storage_manifest_rejects_legacy_layout_before_creating_empty_sites(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    (paths.data_root / "data" / "sites" / "legacy").mkdir(parents=True)

    with pytest.raises(StorageMigrationConfirmationRequired, match="受控迁移"):
        prepare_storage_manifest(paths)

    assert not paths.sites_dir.exists()
    assert not paths.storage_manifest_path.exists()
