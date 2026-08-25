from __future__ import annotations

import json
import time
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
    first = BackendInstanceLock(paths, active_site_id="line-a")
    second = BackendInstanceLock(paths)

    first.acquire()
    owner = json.loads(first.path.read_text(encoding="utf-8"))
    assert set(owner) == {
        "pid", "started_at", "version", "executable", "data_root", "instance_id", "active_site_id"
    }
    assert owner["version"] == APP_VERSION
    assert owner["data_root"] == str(paths.data_root)
    assert owner["instance_id"]
    assert owner["active_site_id"] == "line-a"
    with pytest.raises(BackendInstanceInUseError, match="另一个 NetConsole Backend"):
        second.acquire()

    first.release()
    second.acquire()
    second.release()


def test_warm_handoff_uses_owner_and_transition_lock_until_primary_promotion(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    current = BackendInstanceLock(paths, active_site_id="line-a")
    current.acquire()
    owner = json.loads(current.path.read_text(encoding="utf-8"))
    candidate = BackendInstanceLock(
        paths,
        active_site_id="line-b",
        warm_handoff_owner_id=str(owner["instance_id"]),
    )
    candidate.acquire()
    assert candidate.warm_handoff is True
    assert candidate.handle is None
    assert candidate.transition_handle is not None

    with pytest.raises(BackendInstanceInUseError):
        BackendInstanceLock(paths, active_site_id="line-c").acquire()

    current.release()
    deadline = time.monotonic() + 2
    while candidate.handle is None and time.monotonic() < deadline:
        time.sleep(0.02)
    assert candidate.handle is not None
    assert candidate.transition_handle is None
    promoted_owner = json.loads(candidate.path.read_text(encoding="utf-8"))
    assert promoted_owner["active_site_id"] == "line-b"
    candidate.release()


def test_warm_handoff_rejects_unknown_owner_or_same_site(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    current = BackendInstanceLock(paths, active_site_id="line-a")
    current.acquire()
    owner = json.loads(current.path.read_text(encoding="utf-8"))
    with pytest.raises(BackendInstanceInUseError):
        BackendInstanceLock(
            paths,
            active_site_id="line-b",
            warm_handoff_owner_id="0" * 32,
        ).acquire()
    with pytest.raises(BackendInstanceInUseError):
        BackendInstanceLock(
            paths,
            active_site_id="line-a",
            warm_handoff_owner_id=str(owner["instance_id"]),
        ).acquire()
    current.release()


def test_storage_manifest_is_created_and_updated_without_schema_migration(tmp_path: Path) -> None:
    paths = _paths(tmp_path)

    created = prepare_storage_manifest(paths)
    opened = prepare_storage_manifest(paths)

    assert created.schema_version == CURRENT_STORAGE_SCHEMA_VERSION
    assert opened.minimum_app_version == APP_VERSION
    assert opened.last_opened_app_version == APP_VERSION
    persisted = json.loads(paths.storage_manifest_path.read_text(encoding="utf-8"))
    assert persisted["migration_id"] == ""
    assert persisted["format_version"] == 1
    assert persisted["data_root"] == str(paths.data_root)
    assert persisted["installation_id"]


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
