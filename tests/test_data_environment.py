from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from netconsole.core.paths import PathResolver
from netconsole.core.runtime_environment import (
    ProductionWriteBlockedError,
    data_environment,
    prepare_startup_environment,
    require_production_write_allowed,
    write_data_environment,
)
from netconsole.core.runtime_mode import DataEnvironmentInfo, DataEnvironmentMode


def test_persistent_root_requires_an_explicit_marker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NETCONSOLE_RUNTIME_MODE", "desktop-development")
    with pytest.raises(RuntimeError, match="可验证的持久化存储清单"):
        data_environment(tmp_path)


def test_unmarked_persistent_root_with_verified_storage_manifest_is_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NETCONSOLE_RUNTIME_MODE", "desktop-development")
    for name in ("config", "sites", "runtime"):
        (tmp_path / name).mkdir()
    (tmp_path / "config" / "storage-manifest.json").write_text(
        json.dumps({"data_root": str(tmp_path.resolve())}), encoding="utf-8"
    )

    info = data_environment(tmp_path)

    assert info.mode is DataEnvironmentMode.PRODUCTION
    assert info.readonly_warning is True


def test_environment_marker_round_trip_and_path_resolver_view(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NETCONSOLE_RUNTIME_MODE", "desktop-development")
    write_data_environment(
        tmp_path,
        DataEnvironmentInfo(
            DataEnvironmentMode.DEVELOPMENT,
            created_from=r"D:\NetConsoleData",
            created_time="2026-08-21T00:00:00+00:00",
        ),
    )

    info = PathResolver(app_root=tmp_path / "app", data_root=tmp_path).data_environment
    assert info.mode is DataEnvironmentMode.DEVELOPMENT
    assert info.label == "DEVELOPMENT"
    assert info.readonly_warning is False
    assert json.loads((tmp_path / "runtime_mode.json").read_text(encoding="utf-8"))["created_from"] == r"D:\NetConsoleData"


def test_production_marker_preserves_readonly_warning(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NETCONSOLE_RUNTIME_MODE", "desktop-development")
    write_data_environment(
        tmp_path,
        DataEnvironmentInfo(DataEnvironmentMode.PRODUCTION, readonly_warning=True),
    )

    info = data_environment(tmp_path)
    assert info.mode is DataEnvironmentMode.PRODUCTION
    assert info.readonly_warning is True


def test_production_write_requires_explicit_process_authorization(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NETCONSOLE_RUNTIME_MODE", "desktop-development")
    write_data_environment(
        tmp_path,
        DataEnvironmentInfo(DataEnvironmentMode.PRODUCTION, readonly_warning=True),
    )
    monkeypatch.delenv("NETCONSOLE_ALLOW_PRODUCTION_WRITE", raising=False)
    with pytest.raises(ProductionWriteBlockedError, match="allow-production-write"):
        require_production_write_allowed(tmp_path, "test-maintenance")

    monkeypatch.setenv("NETCONSOLE_ALLOW_PRODUCTION_WRITE", "1")
    require_production_write_allowed(tmp_path, "test-maintenance")


def test_development_environment_allows_maintenance_without_production_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NETCONSOLE_RUNTIME_MODE", "desktop-development")
    write_data_environment(
        tmp_path,
        DataEnvironmentInfo(DataEnvironmentMode.DEVELOPMENT, created_from=r"D:\NetConsoleData"),
    )
    monkeypatch.delenv("NETCONSOLE_ALLOW_PRODUCTION_WRITE", raising=False)
    require_production_write_allowed(tmp_path, "test-maintenance")


def test_test_environment_is_process_bound_and_does_not_require_marker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NETCONSOLE_RUNTIME_MODE", "test")
    assert data_environment(tmp_path).mode is DataEnvironmentMode.TEST


def test_source_startup_recovers_missing_metadata_without_creating_a_site(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NETCONSOLE_RUNTIME_MODE", "desktop-development")
    monkeypatch.setenv("NETCONSOLE_DATA_ROOT", str(tmp_path))

    info = prepare_startup_environment(tmp_path)

    assert info.mode is DataEnvironmentMode.DEVELOPMENT
    marker = json.loads((tmp_path / "runtime_mode.json").read_text(encoding="utf-8"))
    assert marker["mode"] == "development"
    assert not (tmp_path / "config" / "storage-manifest.json").exists()
    assert not (tmp_path / "sites").exists()


def test_source_startup_rejects_unknown_root_content_before_metadata_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NETCONSOLE_RUNTIME_MODE", "desktop-development")
    monkeypatch.setenv("NETCONSOLE_DATA_ROOT", str(tmp_path))
    (tmp_path / "old-backup.zip").write_bytes(b"user data")

    with pytest.raises(RuntimeError, match="拒绝猜测数据环境"):
        prepare_startup_environment(tmp_path)
    assert not (tmp_path / "runtime_mode.json").exists()


def test_packaged_startup_still_rejects_missing_environment_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NETCONSOLE_RUNTIME_MODE", "desktop-packaged")
    monkeypatch.setenv("NETCONSOLE_DATA_ROOT", str(tmp_path))

    with pytest.raises(RuntimeError, match="可验证的持久化存储清单"):
        prepare_startup_environment(tmp_path)


def test_source_startup_recovers_metadata_only_after_existing_site_integrity_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NETCONSOLE_RUNTIME_MODE", "desktop-development")
    monkeypatch.setenv("NETCONSOLE_DATA_ROOT", str(tmp_path))
    database = tmp_path / "sites" / "line-a" / "db" / "devices.db"
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE schema_metadata (key TEXT PRIMARY KEY, value TEXT)")
        connection.commit()

    info = prepare_startup_environment(tmp_path)

    assert info.mode is DataEnvironmentMode.DEVELOPMENT
    assert (tmp_path / "runtime_mode.json").is_file()
    assert not (tmp_path / "config" / "storage-manifest.json").exists()


def test_source_startup_rejects_existing_site_without_supported_schema_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NETCONSOLE_RUNTIME_MODE", "desktop-development")
    monkeypatch.setenv("NETCONSOLE_DATA_ROOT", str(tmp_path))
    database = tmp_path / "sites" / "line-a" / "db" / "devices.db"
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")
        connection.commit()

    with pytest.raises(RuntimeError, match="schema 不兼容"):
        prepare_startup_environment(tmp_path)
    assert not (tmp_path / "runtime_mode.json").exists()


def test_source_startup_rejects_invalid_existing_site_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NETCONSOLE_RUNTIME_MODE", "desktop-development")
    monkeypatch.setenv("NETCONSOLE_DATA_ROOT", str(tmp_path))
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "site_registry.json").write_text(
        json.dumps({"sites": [{"site_id": "line-a", "relative_path": "../outside"}]}),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="SiteRegistry"):
        prepare_startup_environment(tmp_path)
    assert not (tmp_path / "runtime_mode.json").exists()
