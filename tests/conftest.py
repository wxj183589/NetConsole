from __future__ import annotations

import gc
import os
import shutil
import stat
import tempfile
import uuid
import atexit
from pathlib import Path

import pytest

from netconsole.core.runtime_environment import test_data_root_base

# conftest 会在测试模块收集前加载。测试根固定在仓库工作区父目录的
# test-data/NetConsole 下，并在会话结束时清理。本机 canonical checkout
# 仍解析为当前源码检出目录父级的 test-data/NetConsole；GitHub Actions
# 则解析到 runner checkout 对应的隔离工作区，不依赖固定盘符或机器路径。
_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_TEST_BASE_ROOT = test_data_root_base(repository_root=_REPOSITORY_ROOT)
_TEST_RUN_ROOT = _TEST_BASE_ROOT / f"pytest-{uuid.uuid4().hex}"
_TEST_BASETEMP_ROOT: Path | None = None
_TEST_RUN_ROOT.mkdir(parents=True, exist_ok=False)
(_TEST_RUN_ROOT / "temp").mkdir()
tempfile.tempdir = str(_TEST_RUN_ROOT / "temp")
os.environ["NETCONSOLE_RUNTIME_MODE"] = "test"
os.environ["NETCONSOLE_STORAGE_MODE"] = "persistent"
os.environ["NETCONSOLE_DATA_ROOT"] = str(_TEST_RUN_ROOT / "session")


def _cleanup_test_run_root() -> None:
    # Tests may retain a short-lived SQLite connection through a local object
    # after the test body returns. Collect those objects before fail-closed
    # cleanup so a Windows file lock is not mistaken for an owned-path escape.
    gc.collect()
    if os.environ.get("NETCONSOLE_PRESERVE_TEST_BASETEMP") != "1":
        _cleanup_owned_test_path(_TEST_BASETEMP_ROOT)
    _cleanup_owned_test_path(_TEST_RUN_ROOT)


def _cleanup_owned_test_path(target: Path | None) -> None:
    if target is None:
        return
    candidate = Path(target)
    if candidate.is_symlink():
        raise RuntimeError(f"refusing to clean symlinked pytest path: {candidate}")
    target = candidate.resolve()
    base = _TEST_BASE_ROOT.resolve()
    if target == base or not target.is_relative_to(base):
        raise RuntimeError(f"pytest cleanup path escapes the owned test root: {target}")
    if not target.exists():
        return
    if not target.is_dir():
        raise RuntimeError(f"pytest cleanup target is not a directory: {target}")

    def clear_readonly_and_retry(function, path, error):
        if not isinstance(error, PermissionError):
            raise error
        os.chmod(path, stat.S_IWRITE)
        function(path)

    shutil.rmtree(target, onexc=clear_readonly_and_retry)
    if target.exists():
        raise RuntimeError(f"pytest cleanup did not remove its owned path: {target}")


atexit.register(_cleanup_test_run_root)


def pytest_configure(config):
    global _TEST_BASETEMP_ROOT
    configured = Path(config.option.basetemp).resolve() if config.option.basetemp else _TEST_RUN_ROOT / "pytest"
    base = _TEST_BASE_ROOT.resolve()
    if configured == base or not configured.is_relative_to(base):
        raise pytest.UsageError(
            f"pytest --basetemp 必须位于 {base}{os.sep}<run-id>"
        )
    _TEST_BASETEMP_ROOT = configured
    config.option.basetemp = str(configured)


def pytest_unconfigure(config):
    del config
    _cleanup_test_run_root()


@pytest.fixture(autouse=True)
def _isolate_test_data_root(tmp_path, monkeypatch):
    """每个测试使用独立数据根，避免旧 PathResolver(app_root) 调用共享状态。"""

    monkeypatch.setenv("NETCONSOLE_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("NETCONSOLE_RUNTIME_MODE", "test")
