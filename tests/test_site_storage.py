from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from netconsole.core.paths import PathResolver
from netconsole.services.site_storage import (
    DataRootApplicationService,
    SiteApplicationService,
    SitePackageService,
    SiteStorageError,
    validate_display_name,
    validate_site_id,
)


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
    assert (target / "data" / "sites" / "site-one" / "db" / "devices.db").is_file()
    assert next((target / "migrations").glob("migration-*.json")).is_file()


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

    result = SitePackageService(paths, sites).export_site("site-one", package_path)

    assert result["contains_credentials"] is False
    with zipfile.ZipFile(package_path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["contains_credentials"] is False
        archive.extract("site/db/devices.db", tmp_path / "inspect")
    with sqlite3.connect(tmp_path / "inspect" / "site" / "db" / "devices.db") as connection:
        row = connection.execute(
            "SELECT password, ssh_password, snmp_ro_community FROM devices WHERE name = 'SW1'"
        ).fetchone()
    assert row == (None, None, None)


def test_site_package_detects_checksum_tampering(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    sites = SiteApplicationService(paths)
    sites.create_site("site-one", "一号线")
    package = tmp_path / "site.ncsite"
    packages = SitePackageService(paths, sites)
    packages.export_site("site-one", package)
    with zipfile.ZipFile(package, "a") as archive:
        archive.writestr("site/site_meta.json", "tampered")

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
        package, site_id="imported-site", display_name="导入局点"
    )

    assert result["requires_credentials"] is True
    assert target_sites.get_site("imported-site")["display_name"] == "导入局点"
    assert target_paths.site_db_path("imported-site").is_file()
