from __future__ import annotations

import json
import os
import sqlite3
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from netconsole.core.paths import PathResolver
from netconsole.core.database import Database
from netconsole.repositories.device_repository import DeviceRepository
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


def _paths(tmp_path: Path) -> PathResolver:
    app = tmp_path / "app"
    app.mkdir(parents=True)
    return PathResolver(app_root=app, data_root=tmp_path / "data-root")


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


def test_full_migration_replace_restores_original_site_when_publish_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_paths = _paths(tmp_path / "source")
    source_sites = SiteApplicationService(source_paths)
    source_sites.create_site("source-site", "源局点")
    package = tmp_path / "source.ncsite"
    SitePackageService(source_paths, source_sites).export_site("source-site", package)

    target_paths = _paths(tmp_path / "target")
    target_sites = SiteApplicationService(target_paths)
    target_sites.create_site("target-site", "原局点")
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
