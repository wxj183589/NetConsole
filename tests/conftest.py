from __future__ import annotations

import os
import tempfile

import pytest

# conftest 会在测试模块收集前加载。这里先隔离数据根，避免测试模块在
# fixture 生效前构造 Repository/Service 并读取开发态用户数据目录。
_TEST_DATA_ROOT = tempfile.TemporaryDirectory(prefix="netconsole-pytest-")
os.environ["NETCONSOLE_DATA_ROOT"] = _TEST_DATA_ROOT.name


@pytest.fixture(autouse=True)
def _isolate_test_data_root(tmp_path, monkeypatch):
    """每个测试使用独立数据根，避免旧 PathResolver(app_root) 调用共享状态。"""

    monkeypatch.setenv("NETCONSOLE_DATA_ROOT", str(tmp_path))
