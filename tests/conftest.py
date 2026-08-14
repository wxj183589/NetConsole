from __future__ import annotations

import os
import shutil
import tempfile
import uuid
import atexit
from pathlib import Path

import pytest

# conftest 会在测试模块收集前加载。测试根固定在 D 盘，并在会话结束时清理。
_TEST_BASE_ROOT = Path(r"D:\study\test-data\NetConsole")
_TEST_RUN_ROOT = _TEST_BASE_ROOT / f"pytest-{uuid.uuid4().hex}"
_TEST_BASETEMP_ROOT: Path | None = None
_TEST_RUN_ROOT.mkdir(parents=True, exist_ok=False)
(_TEST_RUN_ROOT / "temp").mkdir()
tempfile.tempdir = str(_TEST_RUN_ROOT / "temp")
os.environ["NETCONSOLE_RUNTIME_MODE"] = "test"
os.environ["NETCONSOLE_STORAGE_MODE"] = "persistent"
os.environ["NETCONSOLE_DATA_ROOT"] = str(_TEST_RUN_ROOT / "session")


def _cleanup_test_run_root() -> None:
    for target in (_TEST_BASETEMP_ROOT, _TEST_RUN_ROOT):
        _cleanup_owned_test_path(target)


def _cleanup_owned_test_path(target: Path | None) -> None:
    if target is None:
        return
    target = target.resolve()
    base = _TEST_BASE_ROOT.resolve()
    if target != base and target.is_relative_to(base):
        shutil.rmtree(target, ignore_errors=True)


atexit.register(_cleanup_test_run_root)


def pytest_configure(config):
    global _TEST_BASETEMP_ROOT
    configured = Path(config.option.basetemp).resolve() if config.option.basetemp else _TEST_RUN_ROOT / "pytest"
    base = _TEST_BASE_ROOT.resolve()
    if configured == base or not configured.is_relative_to(base):
        raise pytest.UsageError("pytest --basetemp 必须位于 D:\\study\\test-data\\NetConsole\\<run-id>")
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
