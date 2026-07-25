from __future__ import annotations

from collections import namedtuple
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from uuid import UUID

import pytest

from netconsole.core import data_root_configuration
from netconsole.core.data_root_configuration import DataRootConfigurationError, validate_installation_data_root
from netconsole.core import runtime_environment


ROOT = Path(__file__).resolve().parents[1]


def _allow_non_production_test_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    application = tmp_path / "application"
    application.mkdir()
    monkeypatch.setattr(runtime_environment, "validate_data_root", lambda value, mode: Path(value).resolve())
    monkeypatch.setattr(runtime_environment, "app_root", lambda: application)
    monkeypatch.setattr(data_root_configuration.sys, "platform", "linux")
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(data_root_configuration.shutil, "disk_usage", lambda _path: usage(200 * 1024**3, 0, 120 * 1024**3))


def test_installation_validation_accepts_an_empty_writable_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _allow_non_production_test_root(monkeypatch, tmp_path)
    target = tmp_path / "NetConsoleData"

    assert validate_installation_data_root(target) == target.resolve()
    assert validate_installation_data_root(Path(f"{target}{os.sep}")) == target.resolve()
    assert list(target.iterdir()) == []


def test_installation_validation_accepts_existing_netconsole_data_without_modifying_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_non_production_test_root(monkeypatch, tmp_path)
    target = tmp_path / "现有 NetConsole 数据"
    manifest = target / "config" / "storage-manifest.json"
    database = target / "sites" / "site-a" / "db" / "devices.db"
    capture = target / "sites" / "site-a" / "files" / "rail_transit" / "online_mr" / "MR-01" / "capture.log"
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

    assert validate_installation_data_root(Path(f"{target}{os.sep}")) == target.resolve()

    after = {
        path: (path.read_bytes(), path.stat().st_size, path.stat().st_mtime_ns)
        for path in (manifest, database, capture)
    }
    assert after == before
    assert not list(target.glob(".netconsole-install-probe-*"))


def test_installation_validation_uses_unique_probe_names_and_ignores_legacy_probe_residue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
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
    assert not (target / f".netconsole-install-probe-{unique_id.hex}.tmp.renamed").exists()


def test_installation_probe_reports_cleanup_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_non_production_test_root(monkeypatch, tmp_path)
    target = tmp_path / "not-a-directory"
    target.write_text("keep", encoding="utf-8")

    with pytest.raises(DataRootConfigurationError, match="数据目录无法创建"):
        validate_installation_data_root(target)

    assert target.read_text(encoding="utf-8") == "keep"


def test_installation_validation_rejects_a_non_netconsole_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _allow_non_production_test_root(monkeypatch, tmp_path)
    target = tmp_path / "existing"
    target.mkdir()
    (target / "unrelated.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(DataRootConfigurationError, match="非空"):
        validate_installation_data_root(target)

    assert (target / "unrelated.txt").read_text(encoding="utf-8") == "keep"


def test_installation_validation_rejects_the_program_installation_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _allow_non_production_test_root(monkeypatch, tmp_path)
    installation = tmp_path / "program-files" / "NetConsole"

    with pytest.raises(DataRootConfigurationError, match="程序安装目录"):
        validate_installation_data_root(installation / "data", installation_root=installation)


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
