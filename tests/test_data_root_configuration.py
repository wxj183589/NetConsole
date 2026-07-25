from __future__ import annotations

from collections import namedtuple
import os
from pathlib import Path
import subprocess
import sys

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
    assert list(target.iterdir()) == []


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
