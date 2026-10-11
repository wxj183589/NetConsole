from __future__ import annotations

from collections import namedtuple
import json
import os
import sqlite3
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from uuid import UUID

import pytest

from netconsole.core import data_root_configuration
from netconsole.core.sites import SiteManager
from netconsole.core.data_root_configuration import (
    DataRootConfigurationError,
    prepare_installation_data_root,
    validate_existing_installation_data_root,
    validate_installation_data_root,
)
from netconsole.core import runtime_environment
from netconsole.services import site_storage
from netconsole.services.site_storage import SiteRegistryRepository, SiteStorageError


ROOT = Path(__file__).resolve().parents[1]


def _allow_non_production_test_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    application = tmp_path / "application"
    application.mkdir()
    monkeypatch.setattr(
        runtime_environment,
        "validate_data_root",
        lambda value, mode=None: Path(value).resolve(),
    )
    monkeypatch.setattr(runtime_environment, "app_root", lambda: application)
    monkeypatch.setattr(data_root_configuration.sys, "platform", "linux")
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(
        data_root_configuration.shutil,
        "disk_usage",
        lambda _path: usage(200 * 1024**3, 0, 120 * 1024**3),
    )


def test_installation_validation_accepts_an_empty_writable_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _allow_non_production_test_root(monkeypatch, tmp_path)
    target = tmp_path / "NetConsoleData"

    assert validate_installation_data_root(target) == target.resolve()
    assert (
        validate_installation_data_root(Path(f"{target}{os.sep}")) == target.resolve()
    )
    assert list(target.iterdir()) == []


def test_installation_preparation_initializes_a_manifest_before_first_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_non_production_test_root(monkeypatch, tmp_path)
    target = tmp_path / "NetConsoleData"

    assert prepare_installation_data_root(target) == target.resolve()

    manifest = target / "config" / "storage-manifest.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert Path(payload["data_root"]).resolve() == target.resolve()
    assert payload["schema_version"] == 1
    assert (target / "sites").is_dir()
    assert not list(target.glob(".netconsole-install-probe-*"))


def test_installation_preparation_initializes_one_empty_registered_site_idempotently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_non_production_test_root(monkeypatch, tmp_path)
    target = tmp_path / "NetConsoleData"

    assert prepare_installation_data_root(target) == target.resolve()
    registry = json.loads(
        (target / "config" / "site_registry.json").read_text(encoding="utf-8")
    )
    assert [item["site_id"] for item in registry["sites"]] == ["demo"]
    application = json.loads(
        (target / "config" / "application.json").read_text(encoding="utf-8")
    )
    assert application["current_site"] == "demo"
    assert application["active_site_id"] == "demo"
    database = target / "sites" / "demo" / "db" / "devices.db"
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM devices").fetchone() == (0,)
    before = {
        path: path.read_bytes()
        for path in (database, target / "config" / "site_registry.json")
    }

    assert prepare_installation_data_root(target) == target.resolve()
    assert {path: path.read_bytes() for path in before} == before


def test_first_run_failure_after_site_database_return_rolls_back_owned_site_and_retries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_non_production_test_root(monkeypatch, tmp_path)
    target = tmp_path / "failure-after-init"
    original_init = SiteManager.init_site_database

    def fail_after_database_init(
        manager: SiteManager, site_name: str, with_demo_data: bool = False
    ):
        original_init(manager, site_name, with_demo_data=with_demo_data)
        raise OSError("injected failure after database initialization")

    monkeypatch.setattr(SiteManager, "init_site_database", fail_after_database_init)
    with pytest.raises(SiteStorageError, match="首次启动初始化失败"):
        prepare_installation_data_root(target)

    assert not (target / "sites" / "demo").exists()
    assert not (target / "config" / "site_registry.json").exists()
    assert not (target / "config" / "application.json").exists()
    assert not list((target / "sites").glob(".netconsole-first-run-owned-*.marker"))

    monkeypatch.setattr(SiteManager, "init_site_database", original_init)
    prepare_installation_data_root(target)
    assert (target / "sites" / "demo" / "db" / "devices.db").is_file()
    assert json.loads(
        (target / "config" / "site_registry.json").read_text(encoding="utf-8")
    )["sites"]


def test_first_run_failure_after_sites_directory_creation_does_not_publish_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_non_production_test_root(monkeypatch, tmp_path)
    target = tmp_path / "failure-after-site-dirs"
    original_init = SiteManager.init_site_database

    def fail_after_site_dirs(
        manager: SiteManager, site_name: str, with_demo_data: bool = False
    ):
        manager.ensure_site_dirs(site_name)
        raise OSError("injected failure after site directory creation")

    monkeypatch.setattr(SiteManager, "init_site_database", fail_after_site_dirs)
    with pytest.raises(SiteStorageError, match="首次启动初始化失败"):
        prepare_installation_data_root(target)

    assert not (target / "sites" / "demo").exists()
    assert not (target / "config" / "site_registry.json").exists()
    assert not (target / "config" / "application.json").exists()
    assert not list((target / "sites").glob(".netconsole-first-run-owned-*.marker"))

    monkeypatch.setattr(SiteManager, "init_site_database", original_init)
    prepare_installation_data_root(target)
    assert (target / "sites" / "demo" / "db" / "devices.db").is_file()


def test_first_run_failure_after_registry_write_removes_only_owned_site(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_non_production_test_root(monkeypatch, tmp_path)
    target = tmp_path / "failure-after-registry"
    original_register = SiteRegistryRepository.register

    def fail_after_registry_write(repository, record):
        original_register(repository, record)
        raise OSError("injected failure after registry write")

    monkeypatch.setattr(SiteRegistryRepository, "register", fail_after_registry_write)
    with pytest.raises(SiteStorageError, match="首次启动初始化失败"):
        prepare_installation_data_root(target)

    assert not (target / "sites" / "demo").exists()
    assert not (target / "config" / "site_registry.json").exists()
    assert not (target / "config" / "application.json").exists()


def test_first_run_failure_after_application_write_rolls_back_registry_and_site(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_non_production_test_root(monkeypatch, tmp_path)
    target = tmp_path / "failure-after-application"
    original_set_current = SiteManager.set_current_site_reference

    def fail_after_application_write(manager, site_name: str, *, site_id: str = ""):
        original_set_current(manager, site_name, site_id=site_id)
        raise OSError("injected failure after application write")

    monkeypatch.setattr(SiteManager, "set_current_site_reference", fail_after_application_write)
    with pytest.raises(SiteStorageError, match="首次启动初始化失败"):
        prepare_installation_data_root(target)

    assert not (target / "sites" / "demo").exists()
    assert not (target / "config" / "site_registry.json").exists()
    assert not (target / "config" / "application.json").exists()


def test_first_run_rollback_failure_is_logged_and_retry_stays_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_non_production_test_root(monkeypatch, tmp_path)
    target = tmp_path / "rollback-failure"
    events: list[str] = []

    def fail_after_site_dirs(
        manager: SiteManager, site_name: str, with_demo_data: bool = False
    ):
        manager.ensure_site_dirs(site_name)
        raise OSError("injected failure before database initialization")

    def fail_cleanup(*args, **kwargs):
        raise OSError("injected cleanup failure")

    monkeypatch.setattr(SiteManager, "init_site_database", fail_after_site_dirs)
    monkeypatch.setattr(site_storage, "_remove_owned_first_run_site", fail_cleanup)
    monkeypatch.setattr(
        site_storage.app_logger,
        "log_error",
        lambda event, detail="", **kwargs: events.append(event),
    )

    with pytest.raises(SiteStorageError, match="首次启动初始化失败"):
        prepare_installation_data_root(target)

    assert "FIRST_RUN_INITIALIZATION_SITE_CLEANUP_FAILED" in events
    assert (target / "sites" / "demo").is_dir()
    assert not (target / "config" / "site_registry.json").exists()
    assert not (target / "config" / "application.json").exists()

    with pytest.raises(SiteStorageError, match="缺少可验证的应用配置"):
        prepare_installation_data_root(target)


def test_first_run_does_not_touch_preexisting_site_when_initialization_is_skipped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_non_production_test_root(monkeypatch, tmp_path)
    target = tmp_path / "failure-with-existing-site"
    site_root = target / "sites" / "site-a"
    sentinel = site_root / "user-data.txt"
    sentinel.parent.mkdir(parents=True)
    sentinel.write_text("keep", encoding="utf-8")

    original_init = SiteManager.init_site_database
    called = False

    def fail_if_initialized(
        manager: SiteManager, site_name: str, with_demo_data: bool = False
    ):
        nonlocal called
        called = True
        return original_init(manager, site_name, with_demo_data=with_demo_data)

    monkeypatch.setattr(SiteManager, "init_site_database", fail_if_initialized)
    prepare_installation_data_root(target)

    assert called is False
    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert not (target / "config" / "site_registry.json").exists()
    assert not (target / "config" / "application.json").exists()


def test_first_run_rejects_incomplete_demo_site_instead_of_silent_retry_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_non_production_test_root(monkeypatch, tmp_path)
    target = tmp_path / "incomplete-demo"
    partial = target / "sites" / "demo" / "partial.marker"
    partial.parent.mkdir(parents=True)
    partial.write_text("incomplete", encoding="utf-8")

    with pytest.raises(SiteStorageError, match="缺少可验证的应用配置"):
        prepare_installation_data_root(target)

    assert partial.read_text(encoding="utf-8") == "incomplete"
    assert not (target / "config" / "site_registry.json").exists()
    assert not (target / "config" / "application.json").exists()


def test_installation_preparation_does_not_replace_an_invalid_existing_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_non_production_test_root(monkeypatch, tmp_path)
    target = tmp_path / "NetConsoleData"
    manifest = target / "config" / "storage-manifest.json"
    (target / "sites").mkdir(parents=True)
    manifest.parent.mkdir(parents=True)
    manifest.write_bytes(b"not-json")

    with pytest.raises(RuntimeError, match="storage-manifest.json"):
        prepare_installation_data_root(target)

    assert manifest.read_bytes() == b"not-json"


def test_installation_validation_accepts_existing_netconsole_data_without_modifying_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_non_production_test_root(monkeypatch, tmp_path)
    target = tmp_path / "现有 NetConsole 数据"
    manifest = target / "config" / "storage-manifest.json"
    database = target / "sites" / "site-a" / "db" / "devices.db"
    capture = (
        target
        / "sites"
        / "site-a"
        / "files"
        / "rail_transit"
        / "online_mr"
        / "MR-01"
        / "capture.log"
    )
    manifest.parent.mkdir(parents=True)
    database.parent.mkdir(parents=True)
    capture.parent.mkdir(parents=True)
    manifest.write_text('{"format_version": 1}', encoding="utf-8")
    database.write_bytes(b"existing-sqlite-bytes")
    capture.write_bytes(b"existing-capture-bytes")
    before = {
        path: (path.read_bytes(), path.stat().st_size, path.stat().st_mtime_ns)
        for path in (manifest, database, capture)
    }

    assert (
        validate_installation_data_root(Path(f"{target}{os.sep}")) == target.resolve()
    )

    after = {
        path: (path.read_bytes(), path.stat().st_size, path.stat().st_mtime_ns)
        for path in (manifest, database, capture)
    }
    assert after == before
    assert not list(target.glob(".netconsole-install-probe-*"))


def test_installation_validation_uses_unique_probe_names_and_ignores_legacy_probe_residue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_non_production_test_root(monkeypatch, tmp_path)
    target = tmp_path / "NetConsoleData"
    (target / "config").mkdir(parents=True)
    (target / "sites").mkdir()
    legacy_probe = target / ".netconsole-installer-rename-test.tmp"
    legacy_probe.write_bytes(b"legacy-probe")
    original = (legacy_probe.read_bytes(), legacy_probe.stat().st_mtime_ns)
    generated_ids: list[str] = []

    def next_uuid():
        value = UUID(int=len(generated_ids) + 1)
        generated_ids.append(value.hex)
        return value

    monkeypatch.setattr(data_root_configuration.uuid, "uuid4", next_uuid)

    assert validate_installation_data_root(target) == target.resolve()
    assert generated_ids
    assert (legacy_probe.read_bytes(), legacy_probe.stat().st_mtime_ns) == original
    assert not list(target.glob(".netconsole-install-probe-*"))


def test_installation_validation_reports_probe_rename_error_and_cleans_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_non_production_test_root(monkeypatch, tmp_path)
    target = tmp_path / "NetConsoleData"
    original_rename = data_root_configuration.os.rename

    def reject_probe_rename(source: Path, destination: Path) -> None:
        if Path(source).name.startswith(".netconsole-install-probe-"):
            error = OSError("probe rename rejected")
            error.winerror = 5
            raise error
        original_rename(source, destination)

    monkeypatch.setattr(data_root_configuration.os, "rename", reject_probe_rename)

    with pytest.raises(DataRootConfigurationError, match="同目录临时文件重命名失败.*5"):
        validate_installation_data_root(target)

    assert not list(target.glob(".netconsole-install-probe-*"))


def test_installation_probe_reports_an_unwritable_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "NetConsoleData"
    target.mkdir()
    original_open = Path.open

    def reject_probe_create(path: Path, *args, **kwargs):
        if path.name.startswith(".netconsole-install-probe-"):
            error = PermissionError("probe create rejected")
            error.winerror = 5
            raise error
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", reject_probe_create)

    with pytest.raises(DataRootConfigurationError, match="临时探测文件创建失败.*5"):
        data_root_configuration._verify_writable_and_renamable(target)

    assert not list(target.glob(".netconsole-install-probe-*"))


def test_installation_probe_does_not_overwrite_a_colliding_probe_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "NetConsoleData"
    target.mkdir()
    source = target / ".netconsole-install-probe-collision.tmp"
    renamed = target / ".netconsole-install-probe-collision.tmp.renamed"
    source.write_bytes(b"existing-source")
    renamed.write_bytes(b"existing-target")
    unique_id = UUID(int=1)
    ids = iter((SimpleNamespace(hex="collision"), unique_id))
    monkeypatch.setattr(data_root_configuration.uuid, "uuid4", lambda: next(ids))

    data_root_configuration._verify_writable_and_renamable(target)

    assert source.read_bytes() == b"existing-source"
    assert renamed.read_bytes() == b"existing-target"
    assert not (target / f".netconsole-install-probe-{unique_id.hex}.tmp").exists()
    assert not (
        target / f".netconsole-install-probe-{unique_id.hex}.tmp.renamed"
    ).exists()


def test_installation_probe_reports_cleanup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "NetConsoleData"
    target.mkdir()
    probe_id = UUID(int=2)
    probe_target = target / f".netconsole-install-probe-{probe_id.hex}.tmp.renamed"
    original_unlink = Path.unlink
    monkeypatch.setattr(data_root_configuration.uuid, "uuid4", lambda: probe_id)

    def fail_probe_cleanup(path: Path, *args, **kwargs) -> None:
        if path == probe_target:
            error = OSError("probe cleanup rejected")
            error.winerror = 5
            raise error
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_probe_cleanup)

    with pytest.raises(DataRootConfigurationError, match="临时探测文件清理失败.*5"):
        data_root_configuration._verify_writable_and_renamable(target)

    assert probe_target.exists()


def test_installation_validation_reports_when_the_selected_path_cannot_be_created(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_non_production_test_root(monkeypatch, tmp_path)
    target = tmp_path / "not-a-directory"
    target.write_text("keep", encoding="utf-8")

    with pytest.raises(DataRootConfigurationError, match="数据目录无法创建"):
        validate_installation_data_root(target)

    assert target.read_text(encoding="utf-8") == "keep"


def test_installation_preparation_preserves_unrelated_files_in_a_nonempty_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _allow_non_production_test_root(monkeypatch, tmp_path)
    target = tmp_path / "existing"
    target.mkdir()
    unrelated = target / "unrelated.txt"
    unrelated.write_text("keep", encoding="utf-8")
    before = (unrelated.read_bytes(), unrelated.stat().st_mtime_ns)

    assert prepare_installation_data_root(target) == target.resolve()

    assert (unrelated.read_bytes(), unrelated.stat().st_mtime_ns) == before
    assert (target / "config" / "storage-manifest.json").is_file()
    assert (target / "sites").is_dir()
    assert not (target / "config" / "site_registry.json").exists()


def test_clean_install_rejects_existing_netconsole_business_data_without_touching_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _allow_non_production_test_root(monkeypatch, tmp_path)
    target = tmp_path / "existing"
    (target / "config").mkdir(parents=True)
    manifest = target / "config" / "storage-manifest.json"
    manifest.write_text('{"keep": true}\n', encoding="utf-8")

    with pytest.raises(DataRootConfigurationError, match="清洁安装目标包含"):
        prepare_installation_data_root(target, clean_install=True)

    assert manifest.read_text(encoding="utf-8") == '{"keep": true}\n'


def test_clean_install_preserves_unrelated_files_and_creates_a_new_installation_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _allow_non_production_test_root(monkeypatch, tmp_path)
    target = tmp_path / "fresh"
    unrelated = target / "operator-notes.txt"
    target.mkdir()
    unrelated.write_text("keep", encoding="utf-8")

    prepare_installation_data_root(target, clean_install=True)

    manifest = json.loads(
        (target / "config" / "storage-manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["installation_id"]
    assert unrelated.read_text(encoding="utf-8") == "keep"
    assert json.loads(
        (target / "config" / "site_registry.json").read_text(encoding="utf-8")
    )["sites"]


def test_existing_root_validation_does_not_create_a_missing_historical_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _allow_non_production_test_root(monkeypatch, tmp_path)
    target = tmp_path / "missing-old-root"

    with pytest.raises(DataRootConfigurationError, match="历史数据目录不可访问"):
        validate_existing_installation_data_root(target)

    assert not target.exists()


def test_existing_root_validation_reuses_the_persisted_production_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if os.name != "nt":
        pytest.skip("需要 Windows Backend 依赖执行 Production startup 校验")
    _allow_non_production_test_root(monkeypatch, tmp_path)
    target = tmp_path / "existing"
    prepare_installation_data_root(target)
    monkeypatch.setattr(data_root_configuration.sys, "platform", "win32")

    assert validate_existing_installation_data_root(target) == target.resolve()


@pytest.mark.parametrize(
    "conflict",
    ("config", "sites", "runtime", "agents", "migrations", "staging"),
)
def test_installation_validation_rejects_real_required_path_conflicts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, conflict: str
) -> None:
    _allow_non_production_test_root(monkeypatch, tmp_path)
    target = tmp_path / "existing"
    target.mkdir()
    collision = target / conflict
    collision.write_text("keep", encoding="utf-8")

    with pytest.raises(DataRootConfigurationError, match=f"路径发生冲突：{conflict}"):
        validate_installation_data_root(target)

    assert collision.read_text(encoding="utf-8") == "keep"


def test_installation_validation_rejects_the_program_installation_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _allow_non_production_test_root(monkeypatch, tmp_path)
    installation = tmp_path / "program-files" / "NetConsole"

    with pytest.raises(DataRootConfigurationError, match="程序安装目录"):
        validate_installation_data_root(
            installation / "data", installation_root=installation
        )


def test_installer_entrypoint_import_has_no_configured_data_root_side_effect() -> None:
    environment = os.environ.copy()
    environment.pop("NETCONSOLE_DATA_ROOT", None)
    environment.pop("NETCONSOLE_RUNTIME_MODE", None)
    command = (
        "import sys; import netconsole.entrypoint; "
        "assert 'netconsole.core.app_logger' not in sys.modules; "
        "assert 'netconsole.core.paths' not in sys.modules"
    )

    result = subprocess.run(
        [sys.executable, "-c", command],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
