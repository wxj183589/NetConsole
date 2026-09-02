from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from netconsole.core.paths import PathResolver
from netconsole.core.database import Database
from netconsole.models.wps_sync import TRACKSIDE_AP_WPS_BUSINESS_KEY, WpsTargetType
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.repositories.device_group_repository import DeviceGroupRepository
from netconsole.repositories.wps_sync_repository import WpsSyncRepository
from netconsole.backend.api.main import _current_site_name
from netconsole.services.ap_identity import ApIdentityQueryService
from netconsole.services.site_storage import (
    DataRootApplicationService,
    SiteApplicationService,
    SitePackageService,
    SiteRecord,
    SiteStorageError,
    validate_display_name,
    validate_site_id,
)
from netconsole.services.site_lifecycle import SiteCleanupApplicationService
from netconsole.services.site_package_staging import SitePackageStagingLifecycle


def _paths(tmp_path: Path) -> PathResolver:
    app = tmp_path / "app"
    app.mkdir(parents=True)
    return PathResolver(app_root=app, data_root=tmp_path / "data-root")


def _create_auxiliary_sqlite(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE samples (value TEXT NOT NULL)")
        connection.execute("INSERT INTO samples (value) VALUES (?)", (value,))
        connection.commit()
    finally:
        connection.close()


def _test_wps_protection(value: bytes, entropy: bytes) -> bytes:
    key = hashlib.sha256(entropy).digest()
    return bytes(item ^ key[index % len(key)] for index, item in enumerate(value))


def test_site_package_staging_recovers_interrupted_internal_and_publish_work(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    lifecycle = SitePackageStagingLifecycle(paths)
    internal = paths.temp_dir / "netconsole-site-export-interrupted"
    internal.mkdir(parents=True)
    (internal / "devices.db").write_bytes(b"sqlite-staging")
    imported = paths.temp_dir / "site-import-staging" / "interrupted"
    imported.mkdir(parents=True)
    (imported / "tasks.sqlite").write_bytes(b"sqlite-staging")

    destination = (tmp_path / "exports" / "site.ncsite").resolve()
    destination.parent.mkdir(parents=True)
    operation_id = "a" * 32
    publish = destination.with_name(f".{destination.name}.{operation_id}.tmp")
    publish.write_bytes(b"partial-package")
    lifecycle.journal_dir.mkdir(parents=True)
    (lifecycle.journal_dir / f"{operation_id}.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "operation_id": operation_id,
                "staging_path": str(publish),
                "destination_path": str(destination),
            }
        ),
        encoding="utf-8",
    )

    result = lifecycle.recover_orphans()

    assert result.to_dict() == {
        "status": "PASS",
        "removed_internal_entries": 2,
        "removed_publish_files": 1,
        "removed_journals": 1,
        "restored_site_imports": 0,
        "completed_site_imports": 0,
        "restored_sync_imports": 0,
        "completed_sync_imports": 0,
        "failures": [],
    }
    assert not internal.exists()
    assert not imported.exists()
    assert not publish.exists()
    assert lifecycle.recover_orphans().status == "PASS"


def test_site_package_staging_recovery_rejects_unbound_external_path(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    lifecycle = SitePackageStagingLifecycle(paths)
    operation_id = "b" * 32
    destination = (tmp_path / "exports" / "site.ncsite").resolve()
    protected = (tmp_path / "protected.txt").resolve()
    protected.write_text("protect", encoding="utf-8")
    lifecycle.journal_dir.mkdir(parents=True)
    journal = lifecycle.journal_dir / f"{operation_id}.json"
    journal.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "operation_id": operation_id,
                "staging_path": str(protected),
                "destination_path": str(destination),
            }
        ),
        encoding="utf-8",
    )

    result = lifecycle.recover_orphans()

    assert result.status == "PARTIAL"
    assert protected.read_text(encoding="utf-8") == "protect"
    assert journal.is_file()


def test_site_sync_import_startup_recovery_restores_applying_operation(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    lifecycle = SitePackageStagingLifecycle(paths)
    operation_id = "1" * 32
    import_uuid = "11111111-1111-1111-1111-111111111111"
    target = paths.sites_dir / "line-one"
    devices = target / "db" / "devices.db"
    tasks = target / "db" / "tasks.db"
    metadata = target / "site_meta.json"
    recovery = target / "files" / "backups" / f"sync-import-{import_uuid}"
    audit = target / "sync" / "imports" / f"{import_uuid}.json"
    _create_auxiliary_sqlite(devices, "after")
    _create_auxiliary_sqlite(tasks, "after")
    metadata.write_text('{"revision":2}', encoding="utf-8")
    _create_auxiliary_sqlite(recovery / "db" / "devices.db", "before")
    _create_auxiliary_sqlite(recovery / "db" / "tasks.db", "before")
    (recovery / "site_meta.json").write_text('{"revision":1}', encoding="utf-8")
    journal = lifecycle.begin_sync_import(
        operation_id=operation_id,
        target=target,
        recovery=recovery,
        package_id="package-1",
        package_sha256="a" * 64,
        base_revision=1,
        raw_only=False,
        devices_existed=True,
        tasks_existed=True,
        metadata_existed=True,
        audit_path=audit,
    )
    lifecycle.mark_sync_import(journal, "PREPARED")
    lifecycle.mark_sync_import(journal, "APPLYING")
    created = target / "files" / "sync-imports" / "new.log"
    lifecycle.record_sync_import_created_path(journal, created)
    created.parent.mkdir(parents=True)
    created.write_text("new", encoding="utf-8")
    audit.parent.mkdir(parents=True)
    audit.write_text("{}", encoding="utf-8")

    result = lifecycle.recover_orphans()

    assert result.failures == []
    with sqlite3.connect(devices) as connection:
        assert connection.execute("SELECT value FROM samples").fetchone() == ("before",)
    with sqlite3.connect(tasks) as connection:
        assert connection.execute("SELECT value FROM samples").fetchone() == ("before",)
    assert json.loads(metadata.read_text(encoding="utf-8"))["revision"] == 1
    assert not created.exists()
    assert not audit.exists()
    assert not recovery.exists()
    assert not journal.exists()
    assert result.restored_sync_imports == 1


def test_site_sync_import_startup_recovery_keeps_applied_operation(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    lifecycle = SitePackageStagingLifecycle(paths)
    operation_id = "2" * 32
    import_uuid = "22222222-2222-2222-2222-222222222222"
    target = paths.sites_dir / "line-two"
    recovery = target / "files" / "backups" / f"sync-import-{import_uuid}"
    audit = target / "sync" / "imports" / f"{import_uuid}.json"
    _create_auxiliary_sqlite(target / "db" / "devices.db", "committed")
    (target / "site_meta.json").write_text('{"revision":5}', encoding="utf-8")
    _create_auxiliary_sqlite(recovery / "db" / "devices.db", "before")
    journal = lifecycle.begin_sync_import(
        operation_id=operation_id,
        target=target,
        recovery=recovery,
        package_id="package-2",
        package_sha256="b" * 64,
        base_revision=4,
        raw_only=False,
        devices_existed=True,
        tasks_existed=False,
        metadata_existed=False,
        audit_path=audit,
    )
    lifecycle.mark_sync_import(journal, "PREPARED")
    lifecycle.mark_sync_import(journal, "APPLYING")
    audit.parent.mkdir(parents=True)
    audit.write_text(
        json.dumps(
            {
                "package_id": "package-2",
                "package_sha256": "b" * 64,
                "applied_revision": 5,
            }
        ),
        encoding="utf-8",
    )
    lifecycle.mark_sync_import(journal, "APPLIED", applied_revision=5)

    result = lifecycle.recover_orphans()

    with sqlite3.connect(target / "db" / "devices.db") as connection:
        assert connection.execute("SELECT value FROM samples").fetchone() == ("committed",)
    assert recovery.is_dir()
    assert audit.is_file()
    assert not journal.exists()
    assert result.completed_sync_imports == 1


@pytest.mark.parametrize("metadata", [None, '{"revision":4}'])
def test_site_sync_applied_recovery_requires_published_target_revision(
    tmp_path: Path,
    metadata: str | None,
) -> None:
    paths = _paths(tmp_path)
    lifecycle = SitePackageStagingLifecycle(paths)
    operation_id = "3" * 32
    import_uuid = "33333333-3333-3333-3333-333333333333"
    target = paths.sites_dir / "line-three"
    recovery = target / "files" / "backups" / f"sync-import-{import_uuid}"
    audit = target / "sync" / "imports" / f"{import_uuid}.json"
    _create_auxiliary_sqlite(target / "db" / "devices.db", "unverified")
    _create_auxiliary_sqlite(recovery / "db" / "devices.db", "before")
    if metadata is not None:
        (target / "site_meta.json").write_text(metadata, encoding="utf-8")
    journal = lifecycle.begin_sync_import(
        operation_id=operation_id,
        target=target,
        recovery=recovery,
        package_id="package-3",
        package_sha256="c" * 64,
        base_revision=4,
        raw_only=False,
        devices_existed=True,
        tasks_existed=False,
        metadata_existed=False,
        audit_path=audit,
    )
    lifecycle.mark_sync_import(journal, "PREPARED")
    lifecycle.mark_sync_import(journal, "APPLYING")
    audit.parent.mkdir(parents=True)
    audit.write_text(
        json.dumps(
            {
                "package_id": "package-3",
                "package_sha256": "c" * 64,
                "applied_revision": 5,
            }
        ),
        encoding="utf-8",
    )
    lifecycle.mark_sync_import(journal, "APPLIED", applied_revision=5)

    result = lifecycle.recover_orphans()

    assert result.completed_sync_imports == 0
    assert result.failures and result.failures[0]["path"] == str(journal)
    assert journal.is_file()
    assert recovery.is_dir()
    assert audit.is_file()


def test_site_package_staging_recovers_interrupted_site_replacement(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    lifecycle = SitePackageStagingLifecycle(paths)
    target = paths.sites_dir / "site-one"
    target.mkdir(parents=True)
    (target / "site_meta.json").write_text("original", encoding="utf-8")
    backup = paths.archive_dir / f"site-import-{target.name}-{'c' * 32}"
    backup.parent.mkdir(parents=True)
    journal = lifecycle.begin_site_replacement(target, backup)
    os.replace(target, backup)
    lifecycle.mark_site_replacement(journal, "BACKUP_PUBLISHED")

    result = lifecycle.recover_orphans()

    assert result.status == "PASS"
    assert result.restored_site_imports == 1
    assert result.removed_journals == 1
    assert (target / "site_meta.json").read_text(encoding="utf-8") == "original"
    assert not backup.exists()
    assert not journal.exists()


def test_site_package_staging_rolls_back_published_uncommitted_replacement(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    lifecycle = SitePackageStagingLifecycle(paths)
    target = paths.sites_dir / "site-one"
    target.mkdir(parents=True)
    (target / "site_meta.json").write_text("original", encoding="utf-8")
    backup = paths.archive_dir / f"site-import-{target.name}-{'d' * 32}"
    backup.parent.mkdir(parents=True)
    journal = lifecycle.begin_site_replacement(target, backup)
    os.replace(target, backup)
    lifecycle.mark_site_replacement(journal, "BACKUP_PUBLISHED")
    target.mkdir()
    (target / "site_meta.json").write_text("uncommitted", encoding="utf-8")
    lifecycle.mark_site_replacement(journal, "TARGET_PUBLISHED")

    result = lifecycle.recover_orphans()

    assert result.status == "PASS"
    assert result.restored_site_imports == 1
    assert (target / "site_meta.json").read_text(encoding="utf-8") == "original"
    assert not backup.exists()
    assert not journal.exists()


def test_site_package_staging_preserves_application_committed_replacement(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    lifecycle = SitePackageStagingLifecycle(paths)
    target = paths.sites_dir / "site-one"
    target.mkdir(parents=True)
    (target / "site_meta.json").write_text("committed", encoding="utf-8")
    backup = paths.archive_dir / f"site-import-{target.name}-{'e' * 32}"
    backup.mkdir(parents=True)
    (backup / "site_meta.json").write_text("original", encoding="utf-8")
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    (paths.config_dir / "site_registry.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "sites": [
                    {
                        "site_id": "site-one",
                        "display_name": "site-one",
                        "relative_path": "sites/site-one",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    journal = lifecycle.begin_site_replacement(target, backup)
    lifecycle.mark_site_replacement(journal, "TARGET_PUBLISHED")
    lifecycle.bind_site_replacement_registry(
        journal,
        site_id="site-one",
        preimage={
            "site_id": "site-one",
            "display_name": "site-one",
            "relative_path": "sites/site-one",
        },
        expected={
            "site_id": "site-one",
            "display_name": "site-one",
            "relative_path": "sites/site-one",
        },
    )
    lifecycle.mark_site_replacement(journal, "APPLICATION_COMMITTED")

    result = lifecycle.recover_orphans()

    assert result.status == "PASS"
    assert result.completed_site_imports == 1
    assert (target / "site_meta.json").read_text(encoding="utf-8") == "committed"
    assert (backup / "site_meta.json").read_text(encoding="utf-8") == "original"
    assert not journal.exists()


def test_site_package_staging_rejects_committed_journal_after_target_tamper(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    lifecycle = SitePackageStagingLifecycle(paths)
    target = paths.sites_dir / "site-one"
    target.mkdir(parents=True)
    (target / "site_meta.json").write_text("committed", encoding="utf-8")
    backup = paths.archive_dir / f"site-import-{target.name}-{'f' * 32}"
    backup.mkdir(parents=True)
    (backup / "site_meta.json").write_text("original", encoding="utf-8")
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    (paths.config_dir / "site_registry.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "sites": [
                    {
                        "site_id": "site-one",
                        "display_name": "site-one",
                        "relative_path": "sites/site-one",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    journal = lifecycle.begin_site_replacement(target, backup)
    lifecycle.mark_site_replacement(journal, "TARGET_PUBLISHED")
    lifecycle.bind_site_replacement_registry(
        journal,
        site_id="site-one",
        preimage={
            "site_id": "site-one",
            "display_name": "site-one",
            "relative_path": "sites/site-one",
        },
        expected={
            "site_id": "site-one",
            "display_name": "site-one",
            "relative_path": "sites/site-one",
        },
    )
    lifecycle.mark_site_replacement(journal, "APPLICATION_COMMITTED")
    (target / "site_meta.json").write_text("tampered", encoding="utf-8")

    result = lifecycle.recover_orphans()

    assert result.status == "PASS"
    assert result.completed_site_imports == 0
    assert result.restored_site_imports == 1
    assert (target / "site_meta.json").read_text(encoding="utf-8") == "original"


def test_site_package_staging_requires_application_commit_state_for_recovery(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    lifecycle = SitePackageStagingLifecycle(paths)
    target = paths.sites_dir / "site-one"
    target.mkdir(parents=True)
    (target / "site_meta.json").write_text("published", encoding="utf-8")
    backup = paths.archive_dir / f"site-import-{target.name}-{'a' * 32}"
    backup.mkdir(parents=True)
    (backup / "site_meta.json").write_text("original", encoding="utf-8")
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    (paths.config_dir / "site_registry.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "sites": [
                    {
                        "site_id": "site-one",
                        "display_name": "site-one",
                        "relative_path": "sites/site-one",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    journal = lifecycle.begin_site_replacement(target, backup)
    lifecycle.mark_site_replacement(journal, "TARGET_PUBLISHED")
    lifecycle.bind_site_replacement_registry(
        journal,
        site_id="site-one",
        preimage={
            "site_id": "site-one",
            "display_name": "site-one",
            "relative_path": "sites/site-one",
        },
        expected={
            "site_id": "site-one",
            "display_name": "site-one",
            "relative_path": "sites/site-one",
        },
    )

    result = lifecycle.recover_orphans()

    assert result.status == "PASS"
    assert result.completed_site_imports == 0
    assert result.restored_site_imports == 1
    assert (target / "site_meta.json").read_text(encoding="utf-8") == "original"


def test_site_package_staging_removes_uncommitted_new_site(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    lifecycle = SitePackageStagingLifecycle(paths)
    target = paths.sites_dir / "new-site"
    journal = lifecycle.begin_site_replacement(target, None)
    target.mkdir(parents=True)
    (target / "site_meta.json").write_text("uncommitted", encoding="utf-8")
    lifecycle.mark_site_replacement(journal, "TARGET_PUBLISHED")

    result = lifecycle.recover_orphans()

    assert result.status == "PASS"
    assert result.restored_site_imports == 1
    assert not target.exists()
    assert not journal.exists()


def test_site_package_publish_journal_cleans_after_normal_completion(
    tmp_path: Path,
) -> None:
    lifecycle = SitePackageStagingLifecycle(_paths(tmp_path))
    destination = tmp_path / "exports" / "site.ncsite"
    destination.parent.mkdir(parents=True)

    with lifecycle.publish_path(destination) as staging:
        staging.write_bytes(b"package")
        assert len(list(lifecycle.journal_dir.glob("*.json"))) == 1

    assert not staging.exists()
    assert not list(lifecycle.journal_dir.glob("*.json"))


def test_site_package_recovery_waits_for_active_staging_operation(
    tmp_path: Path,
) -> None:
    lifecycle = SitePackageStagingLifecycle(_paths(tmp_path))
    active = lifecycle.paths.temp_dir / "netconsole-site-export-active"
    active.mkdir(parents=True)
    entered = threading.Event()

    def recover() -> object:
        entered.set()
        return lifecycle.recover_orphans()

    with ThreadPoolExecutor(max_workers=1) as executor:
        with lifecycle.operation_lease():
            future = executor.submit(recover)
            assert entered.wait(timeout=2)
            assert not future.done()
            assert active.is_dir()
        result = future.result(timeout=2)

    assert result.status == "PASS"
    assert not active.exists()


def test_site_creation_uses_stable_id_and_chinese_display_name(tmp_path: Path) -> None:
    service = SiteApplicationService(_paths(tmp_path))

    created = service.create_site("ningbo-line-12", "宁波地铁12号线")

    assert created["site_id"] == "ningbo-line-12"
    assert created["display_name"] == "宁波地铁12号线"
    assert (service.paths.sites_dir / "ningbo-line-12" / "db" / "devices.db").is_file()
    assert not any((service.paths.sites_dir / ".staging").glob("*"))


def test_legacy_chinese_site_directory_is_discovered_and_switchable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    legacy_name = "宁波地铁12号线"
    legacy_root = paths.sites_dir / legacy_name
    paths.ensure_site_dirs(legacy_name)
    Database(paths.site_db_path(legacy_name)).initialize()
    (legacy_root / "site_meta.json").write_text(
        json.dumps(
            {"display_name": legacy_name, "created_at": "2026-07-01T00:00:00"},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    service = SiteApplicationService(paths)
    first = next(
        item for item in service.list_sites() if item["display_name"] == legacy_name
    )
    second = next(
        item for item in service.list_sites() if item["display_name"] == legacy_name
    )

    assert str(first["site_id"]).startswith("legacy-")
    assert first["site_id"] == second["site_id"]
    assert Path(str(first["path"])) == legacy_root.resolve()
    assert json.loads(service.registry.path.read_text(encoding="utf-8"))["sites"]
    monkeypatch.setenv("NETCONSOLE_ACTIVE_SITE_ID", str(first["site_id"]))
    assert _current_site_name(paths) == legacy_name

    switched = service.switch_site(str(first["site_id"]))

    assert switched["site_id"] == first["site_id"]
    assert (
        json.loads(paths.app_config_path.read_text(encoding="utf-8"))["current_site"]
        == legacy_name
    )
    assert paths.site_db_path(legacy_name).is_file()


@pytest.mark.parametrize("value", ["../bad", "a.b", "a b", "a/b", "_"])
def test_site_id_rejects_unsafe_values(value: str) -> None:
    with pytest.raises(SiteStorageError, match="局点标识"):
        validate_site_id(value)


@pytest.mark.parametrize("value", ["CON", "bad/name", "name.", "name "])
def test_display_name_rejects_windows_unsafe_values(value: str) -> None:
    with pytest.raises(SiteStorageError):
        validate_display_name(value)


def test_duplicate_site_id_and_display_name_are_rejected(tmp_path: Path) -> None:
    service = SiteApplicationService(_paths(tmp_path))
    service.create_site("site-one", "一号线")

    with pytest.raises(SiteStorageError) as duplicate_id:
        service.create_site("site-one", "二号线")
    with pytest.raises(SiteStorageError) as duplicate_name:
        service.create_site("site-two", "一号线")

    assert duplicate_id.value.code == "SITE_ALREADY_EXISTS"
    assert duplicate_name.value.code == "SITE_ALREADY_EXISTS"


def test_site_info_update_persists_nullable_fields_without_renaming_directory(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    service = SiteApplicationService(paths)
    created = service.create_site("line-12", "十二号线")
    original_path = Path(str(created["path"]))

    updated = service.update_site_info(
        "line-12",
        display_name="  杭州地铁10号线  ",
        line_name=" 杭州地铁10号线 ",
        project_type=" PIS车地无线系统 ",
    )

    assert updated["site_id"] == "line-12"
    assert updated["display_name"] == "杭州地铁10号线"
    assert updated["line_name"] == "杭州地铁10号线"
    assert updated["project_type"] == "PIS车地无线系统"
    assert Path(str(updated["path"])) == original_path
    assert original_path.is_dir()
    reloaded = SiteApplicationService(paths).get_site("line-12")
    assert reloaded["display_name"] == "杭州地铁10号线"
    assert reloaded["line_name"] == "杭州地铁10号线"
    assert reloaded["project_type"] == "PIS车地无线系统"
    metadata = json.loads(
        (original_path / "site_meta.json").read_text(encoding="utf-8")
    )
    assert metadata["display_name"] == "杭州地铁10号线"
    assert metadata["line_name"] == "杭州地铁10号线"
    assert metadata["system_type"] == "PIS车地无线系统"

    cleared = service.update_site_info(
        "line-12",
        display_name="杭州地铁10号线",
        line_name="   ",
        project_type="",
    )
    assert cleared["line_name"] is None
    assert cleared["project_type"] is None


def test_site_info_duplicate_name_restores_original_manifest(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    service = SiteApplicationService(paths)
    service.create_site("line-1", "一号线")
    service.create_site("line-2", "二号线")
    metadata_path = paths.site_dir("line-2") / "site_meta.json"
    before = metadata_path.read_bytes()

    with pytest.raises(SiteStorageError) as conflict:
        service.update_site_info(
            "line-2",
            display_name="一号线",
            line_name="被回滚的线路",
            project_type="信号系统",
        )

    assert conflict.value.code == "SITE_NAME_CONFLICT"
    assert metadata_path.read_bytes() == before
    assert service.get_site("line-2")["display_name"] == "二号线"


def test_legacy_registry_without_site_info_fields_returns_null(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    service = SiteApplicationService(paths)
    service.create_site("line-1", "一号线")
    registry = json.loads(service.registry.path.read_text(encoding="utf-8"))
    registry["sites"][0].pop("line_name", None)
    registry["sites"][0].pop("project_type", None)
    service.registry.path.write_text(
        json.dumps(registry, ensure_ascii=False), encoding="utf-8"
    )
    metadata_path = paths.site_dir("line-1") / "site_meta.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata.pop("line_name", None)
    metadata.pop("system_type", None)
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    loaded = SiteApplicationService(paths).get_site("line-1")

    assert loaded["line_name"] is None
    assert loaded["project_type"] is None


def test_site_trash_moves_directory_and_unregisters_site(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    sites = SiteApplicationService(paths)
    if not paths.site_dir("demo").is_dir():
        sites.create_site("demo", "演示局点")
    created = sites.create_site("line-1", "一号线")
    source = Path(str(created["path"]))

    result = SiteCleanupApplicationService(paths, sites).trash_site(
        "line-1", confirm_display_name="一号线"
    )

    destination = paths.data_root / str(result["trash_path"])
    assert not source.exists()
    assert destination.is_dir()
    assert destination.parent == paths.trash_dir
    assert (destination / ".netconsole-trash.json").is_file()
    with pytest.raises(SiteStorageError) as missing:
        sites.get_site("line-1")
    assert missing.value.code == "SITE_NOT_FOUND"


def test_site_trash_catalog_failure_rolls_directory_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    sites = SiteApplicationService(paths)
    sites.create_site("demo", "演示局点")
    created = sites.create_site("line-1", "一号线")
    source = Path(str(created["path"]))
    cleanup = SiteCleanupApplicationService(paths, sites)
    monkeypatch.setattr(
        cleanup.registry,
        "unregister",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("catalog failed")),
    )

    with pytest.raises(SiteStorageError) as failed:
        cleanup.trash_site("line-1", confirm_display_name="一号线")

    assert failed.value.code == "SITE_TRASH_FAILED"
    assert source.is_dir()
    assert sites.get_site("line-1")["display_name"] == "一号线"


def test_site_trash_rejects_out_of_root_and_locked_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    sites = SiteApplicationService(paths)
    cleanup = SiteCleanupApplicationService(paths, sites)
    outside = tmp_path / "outside-site"
    outside.mkdir()
    unsafe = cleanup.registry.get
    monkeypatch.setattr(
        cleanup.registry,
        "get",
        lambda _site_id: SiteRecord("line-unsafe", "越界局点", outside),
    )
    with pytest.raises(SiteStorageError) as invalid:
        cleanup.trash_site("line-unsafe", confirm_display_name="越界局点")
    assert invalid.value.code == "SITE_TRASH_PATH_INVALID"

    monkeypatch.setattr(cleanup.registry, "get", unsafe)
    if not paths.site_dir("demo").is_dir():
        sites.create_site("demo", "演示局点")
    sites.create_site("line-locked", "锁定局点")
    original_replace = os.replace

    def locked_replace(source: object, destination: object) -> None:
        if Path(source) == paths.site_dir("line-locked"):
            raise PermissionError("locked")
        original_replace(source, destination)

    monkeypatch.setattr("netconsole.services.site_lifecycle.os.replace", locked_replace)
    with pytest.raises(SiteStorageError) as locked:
        cleanup.trash_site("line-locked", confirm_display_name="锁定局点")
    assert locked.value.code == "SITE_TRASH_LOCKED"
    assert paths.site_dir("line-locked").is_dir()


def test_site_trash_rejects_registry_symlink_alias(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    sites = SiteApplicationService(paths)
    sites.create_site("demo", "演示局点")
    sites.create_site("line-target", "目标局点")
    sites.create_site("line-link", "链接局点")
    link = paths.site_dir("line-link")
    displaced = tmp_path / "line-link-original"
    os.replace(link, displaced)
    try:
        link.symlink_to(paths.site_dir("line-target"), target_is_directory=True)
    except OSError as exc:
        os.replace(displaced, link)
        pytest.skip(f"当前 Windows 环境不允许创建目录符号链接：{exc}")

    cleanup = SiteCleanupApplicationService(paths, sites)
    with pytest.raises(SiteStorageError) as invalid:
        cleanup.trash_site("line-link", confirm_display_name="链接局点")

    assert invalid.value.code == "SITE_TRASH_PATH_INVALID"
    assert paths.site_dir("line-target").is_dir()
    assert not paths.trash_dir.exists()


def test_concurrent_site_trash_only_moves_once(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    sites = SiteApplicationService(paths)
    sites.create_site("demo", "演示局点")
    sites.create_site("line-1", "一号线")
    cleanup = SiteCleanupApplicationService(paths, sites)

    def run() -> str:
        try:
            cleanup.trash_site("line-1", confirm_display_name="一号线")
            return "moved"
        except SiteStorageError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: run(), range(2)))

    assert results.count("moved") == 1
    assert len(list(paths.trash_dir.glob("line-1-*"))) == 1


def test_data_root_rejects_project_and_nested_paths(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    service = DataRootApplicationService(paths)

    with pytest.raises(SiteStorageError) as project_error:
        service.validate(paths.app_root / "data")
    with pytest.raises(SiteStorageError) as nested_error:
        service.validate(paths.data_root / "nested")

    assert project_error.value.code == "DATA_ROOT_UNSAFE_LOCATION"
    assert nested_error.value.code == "DATA_ROOT_NESTED_PATH"


def test_data_root_migration_keeps_old_data_and_verifies_sqlite(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    sites = SiteApplicationService(paths)
    sites.create_site("site-one", "一号线")
    target = tmp_path / "migrated-root"

    result = DataRootApplicationService(paths, sites).migrate(target)

    assert result["old_data_root_retained"] is True
    assert paths.site_db_path("site-one").is_file()
    assert (target / "sites" / "site-one" / "db" / "devices.db").is_file()
    assert next((target / "migrations").glob("migration-*.json")).is_file()
    assert not list(tmp_path.glob("migrated-root.staging-*"))


def test_data_root_migration_rebinds_the_storage_manifest_to_the_published_root(
    tmp_path: Path,
) -> None:
    from netconsole.core.storage_manifest import prepare_storage_manifest

    paths = _paths(tmp_path)
    prepare_storage_manifest(paths)
    target = tmp_path / "migrated-root"

    DataRootApplicationService(paths).migrate(target)

    manifest = json.loads(
        (target / "config" / "storage-manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["data_root"] == str(target.resolve())


def test_site_package_sanitizes_credentials_and_has_checksums(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    sites = SiteApplicationService(paths)
    sites.create_site("site-one", "一号线")
    with sqlite3.connect(paths.site_db_path("site-one")) as connection:
        connection.execute(
            "INSERT INTO devices (device_uuid, name, primary_address, username, password, ssh_password, snmp_ro_community, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
            ("device-1", "SW1", "192.0.2.1", "admin", "plain", "ssh-secret", "public"),
        )
        connection.commit()
    package_path = tmp_path / "exports" / "site.ncsite"

    result = SitePackageService(paths, sites).export_site(
        "site-one", package_path, package_type="sanitized_share"
    )

    assert result["contains_credentials"] is False
    assert result["credential_reentry_count"] == 1
    with zipfile.ZipFile(package_path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["contains_credentials"] is False
        assert manifest["credential_reentry_count"] == 1
        archive.extract("site/db/devices.db", tmp_path / "inspect")
    with sqlite3.connect(
        tmp_path / "inspect" / "site" / "db" / "devices.db"
    ) as connection:
        row = connection.execute(
            "SELECT password, ssh_password, snmp_ro_community FROM devices WHERE name = 'SW1'"
        ).fetchone()
        states = connection.execute(
            "SELECT credential_field, status, source, error_code "
            "FROM device_credential_states WHERE device_uuid = 'device-1' "
            "ORDER BY credential_field"
        ).fetchall()
    assert row == (None, None, None)
    assert states == [
        (
            "snmp_ro_community",
            "needs_reentry",
            "imported_reference",
            "CREDENTIAL_REENTRY_REQUIRED",
        ),
        (
            "ssh_password",
            "needs_reentry",
            "imported_reference",
            "CREDENTIAL_REENTRY_REQUIRED",
        ),
    ]


def test_lightweight_package_round_trips_core_and_four_business_exports(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    sites = SiteApplicationService(paths)
    sites.create_site("site-one", "一号线")
    secret = "Lightweight-Device-Password-123"
    with sqlite3.connect(paths.site_db_path("site-one")) as connection:
        connection.execute(
            "INSERT INTO devices (device_uuid, name, primary_address, device_vendor, "
            "device_type, username, password, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
            ("device-1", "H3C-AC", "192.0.2.20", "H3C", "AC", "admin", secret),
        )
        connection.commit()
    for relative in (
        "history/device-history.json",
        "raw/capture.log",
        "artifacts/report.xlsx",
        "cache/render.json",
        "backup/old.sqlite",
        "staging/partial.part",
    ):
        path = paths.site_dir("site-one") / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("must not be packaged", encoding="utf-8")
    package = tmp_path / "exports" / "site-lightweight.zip"

    packages = SitePackageService(paths, sites)
    result = packages.export_site(
        "site-one", package, package_type="lightweight"
    )

    assert result["contains_credentials"] is True
    assert result["device_passwords_included"] is True
    with zipfile.ZipFile(package) as archive:
        names = set(archive.namelist())
        manifest_bytes = archive.read("manifest.json")
        manifest = json.loads(manifest_bytes)
        device_csv = archive.read("device-management/devices.csv").decode(
            "utf-8-sig"
        )
        assert "site/site_meta.json" in names
        assert "site/db/devices.db" in names
        assert "checksums.json" in names
        assert "README.txt" in names
    assert "device-management/devices.csv" in names
    assert "ac-management/fit-ap-resources.csv" in names
    assert any(name.startswith("trackside-ap-business/") for name in names)
    assert any(name.startswith("rail-transit-base-data/") for name in names)
    assert "manifest.json" in names
    assert secret in device_csv
    assert secret not in manifest_bytes.decode("utf-8")
    assert not any(
        any(part.casefold() in {"logs", "history", "raw", "artifact", "artifacts", "backup", "cache", "staging", "temp"}
            for part in name.split("/"))
        for name in names
    )
    assert manifest["format"] == "netconsole-site-package"
    assert manifest["format_version"] == 4
    assert manifest["package_type"] == "lightweight"
    assert manifest["package_profile"] == "lightweight"
    assert manifest["required_files"] == [
        "site/site_meta.json",
        "site/db/devices.db",
    ]
    assert manifest["component_paths"]["device_management"] == "device-management/devices.csv"
    assert manifest["contains_credentials"] is True
    assert manifest["device_passwords_included"] is True
    inspected = packages.inspect_package(package)
    assert inspected["can_import"] is True
    assert inspected["package_profile"] == "lightweight"

    target_paths = _paths(tmp_path / "target")
    target_sites = SiteApplicationService(target_paths)
    imported = SitePackageService(target_paths, target_sites).import_site(
        package,
        site_id="restored-site",
        display_name="恢复轻量局点",
    )
    restored = DeviceRepository(
        Database(target_paths.site_db_path("restored-site"))
    ).get_by_uuid("device-1")
    assert imported["package_type"] == "lightweight"
    assert imported["requires_credentials"] is False
    assert restored is not None
    assert restored.password == secret
    assert target_sites.get_site("restored-site")["display_name"] == "恢复轻量局点"


def test_lightweight_package_rejects_missing_required_file_and_checksum_mismatch(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path / "source")
    sites = SiteApplicationService(paths)
    sites.create_site("site-one", "一号线")
    package = tmp_path / "site-lightweight.zip"
    packages = SitePackageService(paths, sites)
    packages.export_site("site-one", package, package_type="lightweight")

    missing = tmp_path / "missing-core.zip"
    with zipfile.ZipFile(package) as source, zipfile.ZipFile(
        missing, "w", compression=zipfile.ZIP_DEFLATED
    ) as target:
        for info in source.infolist():
            if info.filename != "site/db/devices.db":
                target.writestr(info, source.read(info.filename))
    with pytest.raises(SiteStorageError) as missing_error:
        packages.inspect_package(missing)
    assert missing_error.value.code == "SITE_IMPORT_INVALID_PACKAGE"

    tampered = tmp_path / "tampered-lightweight.zip"
    with zipfile.ZipFile(package) as source, zipfile.ZipFile(
        tampered, "w", compression=zipfile.ZIP_DEFLATED
    ) as target:
        for info in source.infolist():
            value = (
                b"tampered"
                if info.filename == "device-management/devices.csv"
                else source.read(info.filename)
            )
            target.writestr(info, value)
    with pytest.raises(SiteStorageError) as checksum_error:
        packages.inspect_package(tampered)
    assert checksum_error.value.code == "SITE_IMPORT_CHECKSUM_FAILED"


@pytest.mark.parametrize("package_type", ["full_migration", "sanitized_share"])
def test_site_package_excludes_online_mr_transient_and_rollback_files(
    tmp_path: Path,
    package_type: str,
) -> None:
    paths = _paths(tmp_path)
    sites = SiteApplicationService(paths)
    sites.create_site("site-one", "一号线")
    session = (
        paths.site_dir("site-one")
        / "files"
        / "rail_transit"
        / "online_mr"
        / "profile-one"
        / "sessions"
        / "session-one"
    )
    current = session / "parsed" / "online_diagnosis.sqlite"
    candidate = session / "parsed" / "online_diagnosis.sqlite.upgrading"
    rollback = (
        session / "parsed" / "retired" / "online_diagnosis.previous.sqlite"
    )
    _create_auxiliary_sqlite(current, "current")
    _create_auxiliary_sqlite(candidate, "candidate")
    _create_auxiliary_sqlite(rollback, "rollback")
    (session / "parsed" / "online_diagnosis.upgrade.json").write_text(
        "{}", encoding="utf-8"
    )
    (session / "view").mkdir(parents=True)
    (session / "view" / "live.json").write_text("{}", encoding="utf-8")
    (session / "raw").mkdir(parents=True)
    (session / "raw" / "mesh.log").write_text("raw", encoding="utf-8")
    (session / "session_meta.json").write_text("{}", encoding="utf-8")
    package = tmp_path / f"{package_type}.ncsite"

    SitePackageService(paths, sites).export_site(
        "site-one", package, package_type=package_type
    )

    prefix = (
        "site/files/rail_transit/online_mr/profile-one/"
        "sessions/session-one/"
    )
    with zipfile.ZipFile(package) as archive:
        names = set(archive.namelist())
    assert prefix + "parsed/online_diagnosis.sqlite" in names
    assert prefix + "raw/mesh.log" in names
    assert prefix + "session_meta.json" in names
    assert prefix + "parsed/online_diagnosis.sqlite.upgrading" not in names
    assert prefix + "parsed/online_diagnosis.upgrade.json" not in names
    assert prefix + "parsed/retired/online_diagnosis.previous.sqlite" not in names
    assert prefix + "view/live.json" not in names


@pytest.mark.parametrize("package_type", ["full_migration", "sanitized_share"])
def test_site_package_round_trips_all_sqlite_suffixes_from_wal_snapshot(
    tmp_path: Path,
    package_type: str,
) -> None:
    source_paths = _paths(tmp_path / "source")
    source_sites = SiteApplicationService(source_paths)
    source_sites.create_site("source-site", "源局点")
    source_root = source_paths.site_dir("source-site")
    wal_database = (
        source_root / "files" / "rail_transit" / "ground_unattended" / "index.sqlite"
    )
    sqlite3_database = source_root / "files" / "analysis" / "result.sqlite3"
    wal_database.parent.mkdir(parents=True, exist_ok=True)
    wal_connection = sqlite3.connect(wal_database)
    try:
        assert wal_connection.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        wal_connection.execute("PRAGMA wal_autocheckpoint=0")
        wal_connection.execute("CREATE TABLE samples (value TEXT NOT NULL)")
        wal_connection.execute(
            "INSERT INTO samples (value) VALUES (?)", ("uncheckpointed",)
        )
        wal_connection.commit()
        assert Path(f"{wal_database}-wal").is_file()
        _create_auxiliary_sqlite(sqlite3_database, "sqlite3-snapshot")

        package = tmp_path / f"{package_type}.ncsite"
        SitePackageService(source_paths, source_sites).export_site(
            "source-site",
            package,
            package_type=package_type,
        )
    finally:
        wal_connection.close()

    wal_entry = "site/files/rail_transit/ground_unattended/index.sqlite"
    sqlite3_entry = "site/files/analysis/result.sqlite3"
    with zipfile.ZipFile(package) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert "site/db/devices.db" in manifest["databases"]
        assert wal_entry in manifest["databases"]
        assert sqlite3_entry in manifest["databases"]
        archive.extract(wal_entry, tmp_path / "inspect")
    with sqlite3.connect(tmp_path / "inspect" / wal_entry) as connection:
        assert connection.execute("PRAGMA quick_check").fetchone() == ("ok",)
        assert connection.execute("SELECT value FROM samples").fetchone() == (
            "uncheckpointed",
        )

    target_paths = _paths(tmp_path / "target")
    target_sites = SiteApplicationService(target_paths)
    SitePackageService(target_paths, target_sites).import_site(
        package,
        site_id="restored-site",
    )
    restored_wal = target_paths.site_dir("restored-site") / wal_entry.removeprefix(
        "site/"
    )
    restored_sqlite3 = target_paths.site_dir(
        "restored-site"
    ) / sqlite3_entry.removeprefix("site/")
    with sqlite3.connect(restored_wal) as connection:
        assert connection.execute("PRAGMA quick_check").fetchone() == ("ok",)
        assert connection.execute("SELECT value FROM samples").fetchone() == (
            "uncheckpointed",
        )
        assert connection.execute("PRAGMA journal_mode").fetchone() == ("delete",)
    with sqlite3.connect(restored_sqlite3) as connection:
        assert connection.execute("SELECT value FROM samples").fetchone() == (
            "sqlite3-snapshot",
        )
    assert not Path(f"{restored_wal}-wal").exists()
    assert not Path(f"{restored_wal}-shm").exists()
    assert not list(source_paths.temp_dir.glob("netconsole-site-export-*"))
    assert not list((target_paths.temp_dir / "site-import-staging").glob("*"))


def test_site_package_rejects_corrupt_sqlite3_and_cleans_import_staging(
    tmp_path: Path,
) -> None:
    source_paths = _paths(tmp_path / "source")
    source_sites = SiteApplicationService(source_paths)
    source_sites.create_site("source-site", "源局点")
    database = source_paths.site_dir("source-site") / "files" / "bad.sqlite3"
    _create_auxiliary_sqlite(database, "before-corruption")
    package = tmp_path / "source.ncsite"
    SitePackageService(source_paths, source_sites).export_site("source-site", package)

    corrupt_name = "site/files/bad.sqlite3"
    corrupt_value = b"not a sqlite database"
    rewritten = tmp_path / "corrupt.ncsite"
    with zipfile.ZipFile(package) as source:
        manifest = json.loads(source.read("manifest.json"))
        checksums = json.loads(source.read("checksums.json"))
        digest = hashlib.sha256(corrupt_value).hexdigest()
        manifest["checksums"][corrupt_name] = digest
        checksums[corrupt_name] = digest
        with zipfile.ZipFile(
            rewritten, "w", compression=zipfile.ZIP_DEFLATED
        ) as target:
            for info in source.infolist():
                value = source.read(info.filename)
                if info.filename == corrupt_name:
                    value = corrupt_value
                elif info.filename == "manifest.json":
                    value = json.dumps(manifest, ensure_ascii=False).encode("utf-8")
                elif info.filename == "checksums.json":
                    value = json.dumps(checksums, ensure_ascii=False).encode("utf-8")
                target.writestr(info, value)

    target_paths = _paths(tmp_path / "target")
    target_sites = SiteApplicationService(target_paths)
    with pytest.raises(SiteStorageError) as raised:
        SitePackageService(target_paths, target_sites).import_site(
            rewritten,
            site_id="corrupt-site",
        )

    assert raised.value.code == "SITE_MIGRATION_FAILED"
    assert not target_paths.site_dir("corrupt-site").exists()
    assert not list((target_paths.temp_dir / "site-import-staging").glob("*"))


def test_site_sync_staging_uses_managed_temp_and_cleans_success_and_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from netconsole.services import site_sync as site_sync_module

    paths = _paths(tmp_path)
    sites = SiteApplicationService(paths)
    sites.create_site("site-one", "一号线")
    packages = SitePackageService(paths, sites)
    original_temporary_directory = site_sync_module.tempfile.TemporaryDirectory
    temporary_roots: list[Path | None] = []

    def tracked_temporary_directory(*args: object, **kwargs: object):
        directory = kwargs.get("dir")
        temporary_roots.append(Path(directory).resolve() if directory else None)
        return original_temporary_directory(*args, **kwargs)

    monkeypatch.setattr(
        site_sync_module.tempfile,
        "TemporaryDirectory",
        tracked_temporary_directory,
    )
    packages.export_site(
        "site-one",
        tmp_path / "field-success.ncsite",
        package_type="field_collection",
    )

    original_replace = site_sync_module.os.replace
    failed_destination = (tmp_path / "field-failure.ncsite").resolve()

    def fail_destination_publish(source: object, destination: object) -> None:
        if Path(destination).resolve() == failed_destination:
            raise OSError("forced package publish failure")
        original_replace(source, destination)

    monkeypatch.setattr(site_sync_module.os, "replace", fail_destination_publish)
    with pytest.raises(OSError, match="forced package publish failure"):
        packages.export_site(
            "site-one",
            failed_destination,
            package_type="field_collection",
        )

    assert temporary_roots == [paths.temp_dir.resolve(), paths.temp_dir.resolve()]
    assert paths.temp_dir.is_dir()
    assert not list(paths.temp_dir.glob("netconsole-*"))
    assert not failed_destination.exists()
    assert not list(tmp_path.glob(".field-failure.ncsite.*.tmp"))


def test_full_migration_package_plainly_copies_and_restores_credentials(
    tmp_path: Path,
) -> None:
    source_paths = _paths(tmp_path / "source")
    source_sites = SiteApplicationService(source_paths)
    source_sites.create_site("source-site", "完整迁移局点")
    secret = "NetConsole-Test-Password-123"
    community = "private-test-community"
    tunnel_secret = "Tunnel-Test-Password-456"
    with sqlite3.connect(source_paths.site_db_path("source-site")) as connection:
        connection.execute(
            "INSERT INTO devices (device_uuid, name, primary_address, device_vendor, "
            "device_type, username, password, ssh_username, ssh_password, "
            "snmp_ro_community, tunnel1_enabled, tunnel1_host, tunnel1_username, "
            "tunnel1_password, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
            (
                "device-full",
                "H3C-AC",
                "192.0.2.20",
                "H3C",
                "AC",
                "admin",
                secret,
                "admin",
                secret,
                community,
                1,
                "192.0.2.21",
                "tunnel-admin",
                tunnel_secret,
            ),
        )
        connection.commit()
    package = tmp_path / "full.ncsite"
    packages = SitePackageService(source_paths, source_sites)

    exported = packages.export_site("source-site", package)

    assert exported["contains_credentials"] is True
    assert exported["encrypted"] is False
    with zipfile.ZipFile(package) as archive:
        assert "site/db/devices.db" in archive.namelist()
        assert "payload.enc" not in archive.namelist()
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["format_version"] == 4
        assert manifest["encrypted"] is False
        assert manifest["contains_credentials"] is True
        assert "完整迁移包包含设备用户名和密码" in archive.read("README.txt").decode(
            "utf-8"
        )
        archive.extract("site/db/devices.db", tmp_path / "inspect-full")
    with sqlite3.connect(
        tmp_path / "inspect-full" / "site" / "db" / "devices.db"
    ) as connection:
        unpacked = connection.execute(
            "SELECT username, password, ssh_username, ssh_password, "
            "snmp_ro_community, tunnel1_username, tunnel1_password "
            "FROM devices WHERE device_uuid = 'device-full'"
        ).fetchone()
    assert unpacked == (
        "admin",
        secret,
        "admin",
        secret,
        community,
        "tunnel-admin",
        tunnel_secret,
    )

    inspected = packages.inspect_package(package)
    assert inspected["encrypted"] is False
    assert inspected["contains_credentials"] is True

    target_paths = _paths(tmp_path / "target")
    target_sites = SiteApplicationService(target_paths)
    imported = SitePackageService(target_paths, target_sites).import_site(
        package,
        site_id="restored-site",
        display_name="恢复局点",
    )
    restored = DeviceRepository(
        Database(target_paths.site_db_path("restored-site"))
    ).get_by_uuid("device-full")
    identity_state = ApIdentityQueryService(
        Database(target_paths.site_db_path("restored-site"))
    ).index_state()

    assert imported["requires_credentials"] is False
    assert imported["credential_reentry_count"] == 0
    assert restored is not None
    assert identity_state is not None
    assert int(identity_state["revision"]) > 0
    assert restored.ssh_password == secret
    assert restored.snmp_ro_community == community
    assert restored.tunnel1_password == tunnel_secret
    assert restored.credential_status == "available"


def test_full_migration_round_trips_sync_authorities_without_plaintext_wps_token(
    tmp_path: Path,
) -> None:
    source_paths = _paths(tmp_path / "source")
    source_sites = SiteApplicationService(source_paths)
    source_sites.create_site("site-one", "源局点")
    source_repository = WpsSyncRepository(
        source_paths,
        "site-one",
        protect=_test_wps_protection,
        unprotect=_test_wps_protection,
    )
    secret = "WPS-site-package-secret"
    source_target = source_repository.upsert_target(
        business_key=TRACKSIDE_AP_WPS_BUSINESS_KEY,
        target_code="wps_standard_sheet",
        target_type=WpsTargetType.STANDARD_SPREADSHEET,
        target_name="WPS 普通表格",
        document_open_url="https://example.test/document",
        webhook_url="https://example.test/webhook",
        expected_document_id="document-one",
        token=secret,
    )
    source_sync = source_paths.site_sync_dir("site-one")
    baseline = source_sync / "baselines" / "11111111-1111-1111-1111-111111111111"
    _create_auxiliary_sqlite(baseline / "devices.db", "baseline-device")
    baseline_manifest = baseline / "manifest.json"
    baseline_manifest.write_text(
        json.dumps({"baseline_id": baseline.name, "base_revision": 7}),
        encoding="utf-8",
    )
    import_audit = source_sync / "imports" / "return-one.json"
    import_audit.parent.mkdir(parents=True)
    import_audit.write_text(
        json.dumps({"package_id": "return-one", "applied_revision": 8}),
        encoding="utf-8",
    )
    (source_sync / "imports" / "interrupted.part").write_bytes(b"transient")

    sanitized_package = tmp_path / "sanitized.ncsite"
    SitePackageService(source_paths, source_sites).export_site(
        "site-one",
        sanitized_package,
        package_type="sanitized_share",
    )
    with zipfile.ZipFile(sanitized_package) as archive:
        assert not any(name.startswith("site/sync/") for name in archive.namelist())

    package = tmp_path / "full.ncsite"
    SitePackageService(source_paths, source_sites).export_site("site-one", package)
    with zipfile.ZipFile(package) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read("manifest.json"))
        wps_payload = archive.read("site/sync/wps_sync.sqlite")
    assert {
        "site/sync/wps_sync.sqlite",
        "site/sync/baselines/11111111-1111-1111-1111-111111111111/devices.db",
        "site/sync/baselines/11111111-1111-1111-1111-111111111111/manifest.json",
        "site/sync/imports/return-one.json",
    } <= names
    assert "site/sync/imports/interrupted.part" not in names
    assert "site/sync/wps_sync.sqlite" in manifest["databases"]
    assert secret.encode("utf-8") not in wps_payload

    target_paths = _paths(tmp_path / "target")
    target_sites = SiteApplicationService(target_paths)
    target_sites.create_site("site-one", "原目标局点")
    SitePackageService(target_paths, target_sites).import_site(
        package,
        replace_site_id="site-one",
        display_name="恢复局点",
    )

    del target_sites
    restarted_sites = SiteApplicationService(target_paths)
    restored_root = restarted_sites.registry.get("site-one").root_path
    restored_repository = WpsSyncRepository(
        target_paths,
        "site-one",
        protect=_test_wps_protection,
        unprotect=_test_wps_protection,
    )
    restored_target = restored_repository.get_target(
        TRACKSIDE_AP_WPS_BUSINESS_KEY,
        "wps_standard_sheet",
    )
    assert restored_target.credential_id == source_target.credential_id
    assert restored_repository.resolve_token(restored_target) == secret
    assert json.loads(
        (restored_root / import_audit.relative_to(source_paths.site_dir("site-one"))).read_text(
            encoding="utf-8"
        )
    ) == {"package_id": "return-one", "applied_revision": 8}
    assert json.loads(
        (
            restored_root
            / baseline_manifest.relative_to(source_paths.site_dir("site-one"))
        ).read_text(encoding="utf-8")
    )["base_revision"] == 7
    with sqlite3.connect(
        restored_root / baseline.relative_to(source_paths.site_dir("site-one")) / "devices.db"
    ) as connection:
        assert connection.execute("SELECT value FROM samples").fetchone() == (
            "baseline-device",
        )
    with sqlite3.connect(restored_repository.path) as connection:
        encrypted_token = connection.execute(
            "SELECT encrypted_token FROM wps_credentials WHERE credential_id = ?",
            (restored_target.credential_id,),
        ).fetchone()[0]
    assert bytes(encrypted_token) != secret.encode("utf-8")


def test_full_migration_round_trip_preserves_device_group_contract(
    tmp_path: Path,
) -> None:
    source_paths = _paths(tmp_path / "source")
    source_sites = SiteApplicationService(source_paths)
    source_sites.create_site("source-site", "源局点")
    source_database = Database(source_paths.site_db_path("source-site"))
    groups = DeviceGroupRepository(source_database, "source-site")
    chinese_group = groups.create("车站通信设备", sort_order=71)
    empty_group = groups.create("暂未投运设备", sort_order=72)
    assert chinese_group.id is not None
    assert empty_group.id is not None
    with sqlite3.connect(source_database.path) as connection:
        connection.executemany(
            "INSERT INTO devices (device_uuid, name, station, group_id, device_vendor, "
            "device_type, project_phase, work_scope_status, primary_address, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
            [
                (
                    "device-h3c",
                    "H3C-AC",
                    "同一站点",
                    int(chinese_group.id),
                    "H3C",
                    "AC",
                    "phase_2",
                    "included",
                    "192.0.2.41",
                ),
                (
                    "device-zte",
                    "ZTE-SW",
                    "同一站点",
                    int(chinese_group.id),
                    "ZTE",
                    "SW",
                    "phase_1",
                    "excluded",
                    "192.0.2.42",
                ),
                (
                    "device-other",
                    "OTHER-MR",
                    "另一站点",
                    None,
                    "Other",
                    "MR",
                    "other",
                    "included",
                    "192.0.2.43",
                ),
            ],
        )
        source_groups = connection.execute(
            "SELECT id, name, sort_order FROM device_groups ORDER BY id"
        ).fetchall()
        source_memberships = connection.execute(
            "SELECT device_uuid, group_id FROM devices ORDER BY device_uuid"
        ).fetchall()
        connection.commit()

    package = tmp_path / "group-round-trip.ncsite"
    SitePackageService(source_paths, source_sites).export_site("source-site", package)
    with zipfile.ZipFile(package) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    group_summary = manifest["relation_summary"]["device_groups"]
    assert group_summary["schema_version"] == 1
    assert group_summary["group_count"] == len(source_groups)
    assert group_summary["grouped_device_count"] == 2
    assert group_summary["orphan_group_reference_count"] == 0

    target_paths = _paths(tmp_path / "target")
    target_sites = SiteApplicationService(target_paths)
    SitePackageService(target_paths, target_sites).import_site(
        package,
        site_id="restored-site",
        display_name="恢复局点",
    )
    with sqlite3.connect(target_paths.site_db_path("restored-site")) as connection:
        target_groups = connection.execute(
            "SELECT id, name, sort_order FROM device_groups ORDER BY id"
        ).fetchall()
        target_memberships = connection.execute(
            "SELECT device_uuid, group_id FROM devices ORDER BY device_uuid"
        ).fetchall()
        target_scopes = connection.execute(
            "SELECT DISTINCT site_id FROM device_groups ORDER BY site_id"
        ).fetchall()

    assert target_groups == source_groups
    assert target_memberships == source_memberships
    assert target_scopes == [("restored-site",)]
    assert any(row[1] == "暂未投运设备" for row in target_groups)


def test_legacy_v4_package_without_group_metadata_rebinds_unique_scope(
    tmp_path: Path,
) -> None:
    source_paths = _paths(tmp_path / "source")
    source_sites = SiteApplicationService(source_paths)
    source_sites.create_site("legacy-source", "旧完整包")
    database = Database(source_paths.site_db_path("legacy-source"))
    group = DeviceGroupRepository(database, "legacy-source").create("旧包中文组")
    assert group.id is not None
    with sqlite3.connect(database.path) as connection:
        connection.execute(
            "INSERT INTO devices (device_uuid, name, group_id, primary_address, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))",
            ("legacy-device", "旧包设备", int(group.id), "192.0.2.51"),
        )
        connection.commit()
    package = tmp_path / "legacy-v4.ncsite"
    SitePackageService(source_paths, source_sites).export_site("legacy-source", package)
    rewritten = tmp_path / "legacy-v4-without-relation-metadata.ncsite"
    with zipfile.ZipFile(package) as source, zipfile.ZipFile(
        rewritten, "w", compression=zipfile.ZIP_DEFLATED
    ) as target:
        for info in source.infolist():
            value = source.read(info.filename)
            if info.filename == "manifest.json":
                manifest = json.loads(value)
                manifest.pop("site_scope", None)
                manifest.pop("relation_summary", None)
                value = json.dumps(manifest, ensure_ascii=False).encode("utf-8")
            target.writestr(info, value)

    target_paths = _paths(tmp_path / "target")
    target_sites = SiteApplicationService(target_paths)
    SitePackageService(target_paths, target_sites).import_site(
        rewritten,
        site_id="legacy-target",
    )

    restored_groups = DeviceGroupRepository(
        Database(target_paths.site_db_path("legacy-target")), "legacy-target"
    ).list()
    restored = DeviceRepository(
        Database(target_paths.site_db_path("legacy-target"))
    ).get_by_uuid("legacy-device")
    assert any(item.name == "旧包中文组" for item in restored_groups)
    assert restored is not None
    assert restored.group_id == group.id


def test_full_package_import_rebinds_legacy_blank_group_scope(
    tmp_path: Path,
) -> None:
    source_paths = _paths(tmp_path / "source")
    source_sites = SiteApplicationService(source_paths)
    source_sites.create_site("legacy-source", "旧空作用域局点")
    database = Database(source_paths.site_db_path("legacy-source"))
    group = DeviceGroupRepository(database, "legacy-source").create("旧空作用域组")
    assert group.id is not None
    with sqlite3.connect(database.path) as connection:
        connection.execute(
            "UPDATE device_groups SET site_id=''",
        )
        connection.execute(
            "INSERT INTO devices (device_uuid, name, group_id, primary_address, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))",
            ("legacy-blank-device", "旧设备", int(group.id), "192.0.2.52"),
        )
        connection.commit()
    package = tmp_path / "legacy-blank-scope.ncsite"
    SitePackageService(source_paths, source_sites).export_site("legacy-source", package)

    target_paths = _paths(tmp_path / "target")
    target_sites = SiteApplicationService(target_paths)
    SitePackageService(target_paths, target_sites).import_site(
        package,
        site_id="legacy-target",
    )

    restored_groups = DeviceGroupRepository(
        Database(target_paths.site_db_path("legacy-target")), "legacy-target"
    ).list()
    assert restored_groups
    assert {item.site_id for item in restored_groups} == {"legacy-target"}
    assert any(item.name == "旧空作用域组" for item in restored_groups)


def test_full_package_import_rejects_mixed_group_scopes(tmp_path: Path) -> None:
    source_paths = _paths(tmp_path / "source")
    source_sites = SiteApplicationService(source_paths)
    source_sites.create_site("mixed-source", "混合作用域局点")
    database = Database(source_paths.site_db_path("mixed-source"))
    groups = DeviceGroupRepository(database, "mixed-source")
    first = groups.create("正常组")
    second = groups.create("空作用域组")
    assert first.id is not None and second.id is not None
    with sqlite3.connect(database.path) as connection:
        connection.execute(
            "UPDATE device_groups SET site_id='' WHERE id=?",
            (int(second.id),),
        )
        connection.commit()
    package = tmp_path / "mixed-scope.ncsite"
    SitePackageService(source_paths, source_sites).export_site("mixed-source", package)

    target_paths = _paths(tmp_path / "target")
    with pytest.raises(SiteStorageError) as raised:
        SitePackageService(
            target_paths,
            SiteApplicationService(target_paths),
        ).import_site(package, site_id="mixed-target")

    assert raised.value.code == "SITE_IMPORT_RELATION_SCOPE_CONFLICT"
    assert not target_paths.site_dir("mixed-target").exists()


@pytest.mark.parametrize("schema_version", [2, True, 1.0])
def test_full_package_import_rejects_unknown_group_relation_schema(
    tmp_path: Path,
    schema_version: object,
) -> None:
    source_paths = _paths(tmp_path / "source")
    source_sites = SiteApplicationService(source_paths)
    source_sites.create_site("source-site", "源局点")
    database = Database(source_paths.site_db_path("source-site"))
    DeviceGroupRepository(database, "source-site").create("分组")
    package = tmp_path / "source.ncsite"
    SitePackageService(source_paths, source_sites).export_site("source-site", package)
    rewritten = tmp_path / "unknown-relation-schema.ncsite"
    with zipfile.ZipFile(package) as source, zipfile.ZipFile(
        rewritten, "w", compression=zipfile.ZIP_DEFLATED
    ) as target:
        for info in source.infolist():
            value = source.read(info.filename)
            if info.filename == "manifest.json":
                manifest = json.loads(value)
                manifest["relation_summary"]["device_groups"][
                    "schema_version"
                ] = schema_version
                value = json.dumps(manifest, ensure_ascii=False).encode("utf-8")
            target.writestr(info, value)

    target_paths = _paths(tmp_path / "target")
    with pytest.raises(SiteStorageError) as raised:
        SitePackageService(
            target_paths,
            SiteApplicationService(target_paths),
        ).import_site(rewritten, site_id="target-site")

    assert raised.value.code == "SITE_IMPORT_RELATION_SCHEMA_UNSUPPORTED"
    assert not target_paths.site_dir("target-site").exists()


def test_import_migrates_database_in_staging_before_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_paths = _paths(tmp_path / "source")
    source_sites = SiteApplicationService(source_paths)
    source_sites.create_site("legacy-source", "旧局点")
    package = tmp_path / "legacy.ncsite"
    SitePackageService(source_paths, source_sites).export_site("legacy-source", package)

    target_paths = _paths(tmp_path / "target")
    target_sites = SiteApplicationService(target_paths)
    initialized_staging: list[Path] = []
    original_initialize = Database.initialize

    def fail_staging_initialize(database: Database) -> None:
        if "site-import-staging" in database.path.parts:
            initialized_staging.append(database.path)
            raise sqlite3.OperationalError("forced staging migration failure")
        original_initialize(database)

    monkeypatch.setattr(Database, "initialize", fail_staging_initialize)

    with pytest.raises(SiteStorageError, match="局点导入失败"):
        SitePackageService(target_paths, target_sites).import_site(
            package,
            site_id="legacy-target",
            display_name="迁移失败局点",
        )

    assert initialized_staging
    assert not target_paths.site_dir("legacy-target").exists()
    assert not any(
        record.site_id == "legacy-target" for record in target_sites.registry.list()
    )


def test_full_migration_checksum_tampering_publishes_nothing(
    tmp_path: Path,
) -> None:
    source_paths = _paths(tmp_path / "source")
    source_sites = SiteApplicationService(source_paths)
    source_sites.create_site("source-site", "源局点")
    package = tmp_path / "full.ncsite"
    SitePackageService(source_paths, source_sites).export_site("source-site", package)
    target_paths = _paths(tmp_path / "target")
    target_sites = SiteApplicationService(target_paths)
    target_packages = SitePackageService(target_paths, target_sites)

    tampered = tmp_path / "tampered.ncsite"
    with zipfile.ZipFile(package) as source, zipfile.ZipFile(tampered, "w") as target:
        for info in source.infolist():
            value = source.read(info.filename)
            if info.filename == "site/site_meta.json":
                value = b"tampered"
            target.writestr(info, value)
    with pytest.raises(SiteStorageError) as changed:
        target_packages.import_site(
            tampered,
            site_id="tampered-site",
        )
    assert changed.value.code == "SITE_IMPORT_CHECKSUM_FAILED"
    assert not (target_paths.sites_dir / "tampered-site").exists()
    assert not list((target_paths.temp_dir / "site-import-staging").glob("*"))


def test_v4_full_migration_must_be_plain_and_contain_credentials(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    sites = SiteApplicationService(paths)
    sites.create_site("site-one", "一号线")
    sanitized = tmp_path / "sanitized.ncsite"
    SitePackageService(paths, sites).export_site(
        "site-one", sanitized, package_type="sanitized_share"
    )
    disguised = tmp_path / "disguised-full.ncsite"
    with (
        zipfile.ZipFile(sanitized) as source,
        zipfile.ZipFile(disguised, "w") as target,
    ):
        for info in source.infolist():
            value = source.read(info.filename)
            if info.filename == "manifest.json":
                manifest = json.loads(value)
                manifest["package_type"] = "full_migration"
                value = json.dumps(manifest, ensure_ascii=False).encode("utf-8")
            target.writestr(info, value)

    with pytest.raises(SiteStorageError) as invalid:
        SitePackageService(paths, sites).inspect_package(disguised)

    assert invalid.value.code == "SITE_IMPORT_INVALID_PACKAGE"


def test_full_migration_replace_uses_package_credentials(tmp_path: Path) -> None:
    source_paths = _paths(tmp_path / "source")
    source_sites = SiteApplicationService(source_paths)
    source_sites.create_site("source-site", "源局点")
    with sqlite3.connect(source_paths.site_db_path("source-site")) as connection:
        connection.execute(
            "INSERT INTO devices (device_uuid, name, primary_address, ssh_username, "
            "password, ssh_password, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
            (
                "shared-device",
                "包内设备",
                "192.0.2.31",
                "package-user",
                "package-secret",
                "package-secret",
            ),
        )
        connection.commit()
    package = tmp_path / "replace.ncsite"
    SitePackageService(source_paths, source_sites).export_site("source-site", package)

    target_paths = _paths(tmp_path / "target")
    target_sites = SiteApplicationService(target_paths)
    target_sites.create_site("target-site", "目标局点")
    with sqlite3.connect(target_paths.site_db_path("target-site")) as connection:
        connection.execute(
            "INSERT INTO devices (device_uuid, name, primary_address, ssh_username, "
            "password, ssh_password, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
            (
                "shared-device",
                "本地设备",
                "192.0.2.32",
                "local-user",
                "local-secret",
                "local-secret",
            ),
        )
        connection.commit()
    connection.close()

    SitePackageService(target_paths, target_sites).import_site(
        package,
        replace_site_id="target-site",
    )
    restored = DeviceRepository(
        Database(target_paths.site_db_path("target-site"))
    ).get_by_uuid("shared-device")

    assert restored is not None
    assert restored.ssh_password == "package-secret"


def test_site_package_detects_checksum_tampering(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    sites = SiteApplicationService(paths)
    sites.create_site("site-one", "一号线")
    package = tmp_path / "site.ncsite"
    packages = SitePackageService(paths, sites)
    packages.export_site("site-one", package, package_type="sanitized_share")
    tampered = tmp_path / "tampered.ncsite"
    with zipfile.ZipFile(package) as source, zipfile.ZipFile(tampered, "w") as target:
        for info in source.infolist():
            value = (
                b"tampered"
                if info.filename == "site/site_meta.json"
                else source.read(info.filename)
            )
            target.writestr(info, value)
    package.unlink()
    tampered.replace(package)

    with pytest.raises(SiteStorageError) as error:
        packages.inspect_package(package)

    assert error.value.code == "SITE_IMPORT_CHECKSUM_FAILED"


def test_site_package_rejects_path_traversal(tmp_path: Path) -> None:
    package = tmp_path / "unsafe.ncsite"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("../escape.txt", "bad")

    with pytest.raises(SiteStorageError) as error:
        SitePackageService(_paths(tmp_path / "case")).inspect_package(package)

    assert error.value.code == "SITE_IMPORT_INVALID_PACKAGE"


def test_import_as_new_site_is_staged_and_registered(tmp_path: Path) -> None:
    source_paths = _paths(tmp_path / "source")
    source_sites = SiteApplicationService(source_paths)
    source_sites.create_site("source-site", "源局点")
    package = tmp_path / "source.ncsite"
    SitePackageService(source_paths, source_sites).export_site("source-site", package)
    target_paths = _paths(tmp_path / "target")
    target_sites = SiteApplicationService(target_paths)

    result = SitePackageService(target_paths, target_sites).import_site(
        package,
        site_id="imported-site",
        display_name="导入局点",
    )

    assert result["requires_credentials"] is False
    assert result["credential_reentry_count"] == 0
    assert target_sites.get_site("imported-site")["display_name"] == "导入局点"
    assert target_paths.site_db_path("imported-site").is_file()


def test_imported_site_marks_credentials_for_reentry_and_new_secret_clears_marker(
    tmp_path: Path,
) -> None:
    source_paths = _paths(tmp_path / "source")
    source_sites = SiteApplicationService(source_paths)
    source_sites.create_site("source-site", "宁波地铁1号线")
    with sqlite3.connect(source_paths.site_db_path("source-site")) as connection:
        connection.execute(
            "INSERT INTO devices (device_uuid, name, primary_address, ssh_username, "
            "ssh_password, created_at, updated_at) VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
            ("device-imported", "中文设备", "192.0.2.11", "admin", "secret"),
        )
        connection.commit()
    package = tmp_path / "source.ncsite"
    SitePackageService(source_paths, source_sites).export_site(
        "source-site", package, package_type="sanitized_share"
    )
    target_paths = _paths(tmp_path / "target")
    target_sites = SiteApplicationService(target_paths)

    result = SitePackageService(target_paths, target_sites).import_site(
        package,
        site_id="imported-site",
        display_name="导入局点",
    )
    repository = DeviceRepository(Database(target_paths.site_db_path("imported-site")))
    imported = repository.get_by_uuid("device-imported")

    assert result["requires_credentials"] is True
    assert result["credential_reentry_count"] == 1
    assert imported is not None
    assert imported.ssh_password is None
    assert imported.credential_status == "needs_reentry"
    assert imported.credential_source == "imported_reference"
    assert imported.credential_error_code == "CREDENTIAL_REENTRY_REQUIRED"

    imported.ssh_password = "new-local-secret"
    saved = repository.update(imported)

    assert saved.ssh_password == "new-local-secret"
    assert saved.credential_status == "available"
    assert saved.credential_source == "local_database"


def test_import_replace_uses_legacy_directory_path(tmp_path: Path) -> None:
    source_paths = _paths(tmp_path / "source")
    source_sites = SiteApplicationService(source_paths)
    source_sites.create_site("source-site", "源局点")
    source_database = Database(source_paths.site_db_path("source-site"))
    source_group = DeviceGroupRepository(source_database, "source-site").create(
        "保留分组"
    )
    assert source_group.id is not None
    with sqlite3.connect(source_database.path) as connection:
        connection.execute(
            "INSERT INTO devices (device_uuid, name, group_id, primary_address, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))",
            ("legacy-replace-device", "分组设备", int(source_group.id), "192.0.2.61"),
        )
        connection.commit()
    package = tmp_path / "source.ncsite"
    SitePackageService(source_paths, source_sites).export_site("source-site", package)

    target_paths = _paths(tmp_path / "target")
    legacy_name = "宁波地铁12号线"
    target_paths.ensure_site_dirs(legacy_name)
    Database(target_paths.site_db_path(legacy_name)).initialize()
    target_sites = SiteApplicationService(target_paths)
    legacy = next(
        item
        for item in target_sites.list_sites()
        if item["display_name"] == legacy_name
    )

    result = SitePackageService(target_paths, target_sites).import_site(
        package,
        replace_site_id=str(legacy["site_id"]),
        display_name="替换后的局点",
    )

    assert result["backup_created"] is True
    assert target_paths.site_db_path(legacy_name).is_file()
    assert not (target_paths.sites_dir / str(legacy["site_id"])).exists()
    assert (
        target_sites.get_site(str(legacy["site_id"]))["display_name"] == "替换后的局点"
    )
    with sqlite3.connect(target_paths.site_db_path(legacy_name)) as connection:
        scopes = connection.execute(
            "SELECT DISTINCT site_id FROM device_groups ORDER BY site_id"
        ).fetchall()
        restored = connection.execute(
            "SELECT group_id FROM devices WHERE device_uuid='legacy-replace-device'"
        ).fetchone()
    assert scopes == [(legacy_name,)]
    assert restored == (int(source_group.id),)


def test_full_migration_replace_restores_original_site_when_publish_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_paths = _paths(tmp_path / "source")
    source_sites = SiteApplicationService(source_paths)
    source_sites.create_site("source-site", "源局点")
    source_sync = source_paths.site_sync_dir("source-site")
    _create_auxiliary_sqlite(source_sync / "wps_sync.sqlite", "replacement-sync")
    (source_sync / "baselines" / "replacement").mkdir(parents=True)
    (source_sync / "baselines" / "replacement" / "manifest.json").write_text(
        "replacement-baseline",
        encoding="utf-8",
    )
    (source_sync / "imports").mkdir(parents=True)
    (source_sync / "imports" / "replacement.json").write_text(
        "replacement-import",
        encoding="utf-8",
    )
    package = tmp_path / "source.ncsite"
    SitePackageService(source_paths, source_sites).export_site("source-site", package)

    target_paths = _paths(tmp_path / "target")
    target_sites = SiteApplicationService(target_paths)
    target_sites.create_site("target-site", "原局点")
    target_sync = target_paths.site_sync_dir("target-site")
    _create_auxiliary_sqlite(target_sync / "wps_sync.sqlite", "original-sync")
    original_baseline = target_sync / "baselines" / "original" / "manifest.json"
    original_baseline.parent.mkdir(parents=True)
    original_baseline.write_text("original-baseline", encoding="utf-8")
    original_import = target_sync / "imports" / "original.json"
    original_import.parent.mkdir(parents=True)
    original_import.write_text("original-import", encoding="utf-8")
    marker = target_paths.site_files_dir("target-site") / "original.txt"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("original-site-data", encoding="utf-8")

    def fail_register(_record: object) -> None:
        raise RuntimeError("simulated registry failure")

    monkeypatch.setattr(target_sites.registry, "register", fail_register)
    with pytest.raises(SiteStorageError) as failed:
        SitePackageService(target_paths, target_sites).import_site(
            package,
            replace_site_id="target-site",
        )

    assert failed.value.code == "SITE_IMPORT_FAILED"
    assert marker.read_text(encoding="utf-8") == "original-site-data"
    with sqlite3.connect(target_paths.site_db_path("target-site")) as connection:
        assert connection.execute("PRAGMA quick_check").fetchone() == ("ok",)
    restarted_sites = SiteApplicationService(target_paths)
    restarted_root = restarted_sites.registry.get("target-site").root_path
    with sqlite3.connect(restarted_root / "sync" / "wps_sync.sqlite") as connection:
        assert connection.execute("SELECT value FROM samples").fetchone() == (
            "original-sync",
        )
    assert original_baseline.read_text(encoding="utf-8") == "original-baseline"
    assert original_import.read_text(encoding="utf-8") == "original-import"


def test_full_migration_replace_failure_restores_chinese_physical_site_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_paths = _paths(tmp_path / "source")
    source_sites = SiteApplicationService(source_paths)
    source_sites.create_site("source-site", "源局点")
    package = tmp_path / "source.ncsite"
    SitePackageService(source_paths, source_sites).export_site("source-site", package)

    target_paths = _paths(tmp_path / "target")
    physical_name = "宁波地铁12号线"
    target_paths.ensure_site_dirs(physical_name)
    target_database = Database(target_paths.site_db_path(physical_name))
    target_database.initialize()
    target_sites = SiteApplicationService(target_paths)
    target_record = next(
        item for item in target_sites.list_sites() if item["display_name"] == physical_name
    )
    marker = target_paths.site_files_dir(physical_name) / "original.txt"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("original-site-data", encoding="utf-8")

    def fail_register(_record: object) -> None:
        raise RuntimeError("simulated registry failure")

    monkeypatch.setattr(target_sites.registry, "register", fail_register)
    with pytest.raises(SiteStorageError) as failed:
        SitePackageService(target_paths, target_sites).import_site(
            package,
            replace_site_id=str(target_record["site_id"]),
        )

    assert failed.value.code == "SITE_IMPORT_FAILED"
    assert marker.read_text(encoding="utf-8") == "original-site-data"
    assert target_paths.site_db_path(physical_name).is_file()
    assert not list(
        (target_paths.temp_dir / "site-import-replacement-journal").glob("*.json")
    )


def test_full_migration_new_site_failure_removes_unregistered_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_paths = _paths(tmp_path / "source")
    source_sites = SiteApplicationService(source_paths)
    source_sites.create_site("source-site", "源局点")
    package = tmp_path / "source.ncsite"
    SitePackageService(source_paths, source_sites).export_site("source-site", package)

    target_paths = _paths(tmp_path / "target")
    target_sites = SiteApplicationService(target_paths)

    def fail_register(_record: object) -> None:
        raise RuntimeError("simulated registry failure")

    monkeypatch.setattr(target_sites.registry, "register", fail_register)
    with pytest.raises(SiteStorageError) as failed:
        SitePackageService(target_paths, target_sites).import_site(
            package,
            site_id="new-site",
        )

    assert failed.value.code == "SITE_IMPORT_FAILED"
    assert not target_paths.site_dir("new-site").exists()
    assert not list(
        (
            target_paths.temp_dir / "site-import-replacement-journal"
        ).glob("*.json")
    )


def test_full_migration_create_preserves_commit_when_register_raises_after_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_paths = _paths(tmp_path / "source")
    source_sites = SiteApplicationService(source_paths)
    source_sites.create_site("source-site", "源局点")
    package = tmp_path / "source.ncsite"
    SitePackageService(source_paths, source_sites).export_site("source-site", package)

    target_paths = _paths(tmp_path / "target")
    target_sites = SiteApplicationService(target_paths)
    original_register = target_sites.registry.register

    def persist_then_fail(record: SiteRecord) -> None:
        original_register(record)
        raise RuntimeError("simulated crash after Registry persistence")

    monkeypatch.setattr(target_sites.registry, "register", persist_then_fail)
    result = SitePackageService(target_paths, target_sites).import_site(
        package,
        site_id="new-site",
        display_name="已提交局点",
    )

    assert result["site_id"] == "new-site"
    assert target_sites.get_site("new-site")["display_name"] == "已提交局点"
    assert target_paths.site_db_path("new-site").is_file()
    assert not list(
        (target_paths.temp_dir / "site-import-replacement-journal").glob("*.json")
    )


def test_full_migration_replace_preserves_commit_when_register_raises_after_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_paths = _paths(tmp_path / "source")
    source_sites = SiteApplicationService(source_paths)
    source_sites.create_site("source-site", "源局点")
    source_marker = source_paths.site_files_dir("source-site") / "new.txt"
    source_marker.parent.mkdir(parents=True, exist_ok=True)
    source_marker.write_text("new", encoding="utf-8")
    package = tmp_path / "source.ncsite"
    SitePackageService(source_paths, source_sites).export_site("source-site", package)

    target_paths = _paths(tmp_path / "target")
    target_sites = SiteApplicationService(target_paths)
    target_sites.create_site("target-site", "原局点")
    old_marker = target_paths.site_files_dir("target-site") / "old.txt"
    old_marker.parent.mkdir(parents=True, exist_ok=True)
    old_marker.write_text("old", encoding="utf-8")
    original_register = target_sites.registry.register

    def persist_then_fail(record: SiteRecord) -> None:
        original_register(record)
        raise RuntimeError("simulated crash after Registry persistence")

    monkeypatch.setattr(target_sites.registry, "register", persist_then_fail)
    result = SitePackageService(target_paths, target_sites).import_site(
        package,
        replace_site_id="target-site",
        display_name="替换后局点",
    )

    assert result["backup_created"] is True
    assert target_sites.get_site("target-site")["display_name"] == "替换后局点"
    assert (target_paths.site_files_dir("target-site") / "new.txt").is_file()
    assert not old_marker.exists()


def test_field_package_baseline_failure_rolls_back_files_and_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_paths = _paths(tmp_path / "source")
    source_sites = SiteApplicationService(source_paths)
    source_sites.create_site("line-one", "源局点")
    package = tmp_path / "field.ncsite"
    SitePackageService(source_paths, source_sites).export_site(
        "line-one", package, package_type="field_collection"
    )

    target_paths = _paths(tmp_path / "target")
    target_sites = SiteApplicationService(target_paths)

    def fail_baseline(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("simulated baseline failure")

    monkeypatch.setattr(
        "netconsole.services.site_sync.SiteSyncService.record_field_baseline",
        fail_baseline,
    )
    with pytest.raises(SiteStorageError) as failed:
        SitePackageService(target_paths, target_sites).import_site(
            package,
            site_id="line-one",
        )

    assert failed.value.code == "SITE_IMPORT_FAILED"
    assert target_sites.registry.raw_record("line-one") is None
    assert not target_paths.site_dir("line-one").exists()


def test_field_return_package_previews_and_applies_three_way_merge(
    tmp_path: Path,
) -> None:
    source_paths = _paths(tmp_path / "source")
    source_sites = SiteApplicationService(source_paths)
    source_sites.create_site("line-one", "一号线")
    with sqlite3.connect(source_paths.site_db_path("line-one")) as connection:
        connection.execute(
            """
            INSERT INTO devices (
                device_uuid, name, primary_address, station, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "device-1",
                "AP-0102",
                "192.0.2.10",
                "东门口站",
                "2026-07-24T08:00:00",
                "2026-07-24T08:00:00",
            ),
        )
        connection.commit()
    config_template = source_paths.config_center_root("line-one") / "templates.json"
    config_template.parent.mkdir(parents=True)
    config_template.write_text('{"template":"现场采集"}', encoding="utf-8")

    field_package = tmp_path / "line-one-field.ncsite"
    source_packages = SitePackageService(source_paths, source_sites)
    field_result = source_packages.export_site(
        "line-one",
        field_package,
        package_type="field_collection",
    )

    assert field_result["package_type"] == "field_collection"
    with zipfile.ZipFile(field_package) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["package_type"] == "field_collection"
        assert manifest["site_uuid"].startswith("site-")
        assert "site/db/tasks.db" not in archive.namelist()
        assert "site/files/config_center/templates.json" in archive.namelist()

    field_paths = _paths(tmp_path / "field")
    field_sites = SiteApplicationService(field_paths)
    field_packages = SitePackageService(field_paths, field_sites)
    imported = field_packages.import_site(field_package, site_id="line-one")
    assert imported["package_type"] == "field_collection"

    with sqlite3.connect(field_paths.site_db_path("line-one")) as connection:
        connection.execute(
            "UPDATE devices SET station = ?, updated_at = ? WHERE device_uuid = ?",
            ("东门口站至江厦桥东区间", "2026-07-24T10:00:00", "device-1"),
        )
        connection.commit()
    raw_file = (
        field_paths.site_dir("line-one")
        / "files"
        / "rail_transit"
        / "online_mr"
        / "MR-01"
        / "sessions"
        / "task-return-1"
        / "raw"
        / "mesh.log"
    )
    raw_file.parent.mkdir(parents=True)
    raw_file.write_text("mesh sample", encoding="utf-8")

    return_package = tmp_path / "line-one-return.ncresult"
    return_result = field_packages.export_site(
        "line-one",
        return_package,
        package_type="collection_return",
    )
    assert return_result["new_or_changed_files"] == 1

    with sqlite3.connect(source_paths.site_db_path("line-one")) as connection:
        connection.execute(
            "UPDATE devices SET station = ?, updated_at = ? WHERE device_uuid = ?",
            ("江厦桥东站", "2026-07-24T09:00:00", "device-1"),
        )
        connection.commit()

    preview = source_packages.inspect_package(
        return_package,
        target_site_id="line-one",
    )

    assert preview["package_type"] == "collection_return"
    assert preview["site_identity_match"] is True
    assert preview["new_files"] == 1
    assert preview["conflict_count"] >= 1
    station_conflict = next(
        item for item in preview["conflicts"] if item["field"] == "station"
    )
    assert station_conflict["base_value"] == "东门口站"
    assert station_conflict["local_value"] == "江厦桥东站"
    assert station_conflict["returned_value"] == "东门口站至江厦桥东区间"

    with pytest.raises(SiteStorageError) as unresolved:
        source_packages.import_site(return_package, site_id="line-one")
    assert unresolved.value.code == "SITE_IMPORT_CONFLICT"

    resolutions = [
        {"conflict_id": item["conflict_id"], "choice": "returned"}
        for item in preview["conflicts"]
    ]
    merged = source_packages.import_site(
        return_package,
        site_id="line-one",
        conflict_resolutions=resolutions,
    )

    assert merged["backup_created"] is True
    assert merged["new_files"] == 1
    assert raw_file.relative_to(field_paths.site_dir("line-one")).as_posix()
    imported_raw = source_paths.site_dir("line-one") / raw_file.relative_to(
        field_paths.site_dir("line-one")
    )
    assert imported_raw.read_text(encoding="utf-8") == "mesh sample"
    with sqlite3.connect(source_paths.site_db_path("line-one")) as connection:
        row = connection.execute(
            "SELECT station FROM devices WHERE device_uuid = ?",
            ("device-1",),
        ).fetchone()
    assert row == ("东门口站至江厦桥东区间",)
    assert next(
        source_paths.site_backups_dir("line-one").glob("sync-import-*")
    ).is_dir()
    metadata_before_replay = json.loads(
        (source_paths.site_dir("line-one") / "site_meta.json").read_text(
            encoding="utf-8"
        )
    )
    backups_before_replay = sorted(
        source_paths.site_backups_dir("line-one").glob("sync-import-*")
    )

    repeated = source_packages.import_site(
        return_package,
        site_id="line-one",
        conflict_resolutions=resolutions,
    )

    assert repeated["idempotent_replay"] is True
    assert repeated["backup_created"] is False
    assert repeated["import_id"] == merged["import_id"]
    assert json.loads(
        (source_paths.site_dir("line-one") / "site_meta.json").read_text(
            encoding="utf-8"
        )
    )["revision"] == metadata_before_replay["revision"]
    assert sorted(source_paths.site_backups_dir("line-one").glob("sync-import-*")) == backups_before_replay


def test_legacy_site_requires_audit_before_exporting_field_collection_package(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    legacy_name = "宁波地铁1号线"
    paths.ensure_site_dirs(legacy_name)
    Database(paths.site_db_path(legacy_name)).initialize()
    sites = SiteApplicationService(paths)
    legacy = next(
        item for item in sites.list_sites() if item["display_name"] == legacy_name
    )

    with pytest.raises(SiteStorageError) as error:
        SitePackageService(paths, sites).export_site(
            str(legacy["site_id"]),
            tmp_path / "legacy.ncsite",
            package_type="field_collection",
        )

    assert error.value.code == "SITE_SYNC_AUDIT_REQUIRED"
