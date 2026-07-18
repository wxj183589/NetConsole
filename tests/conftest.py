from __future__ import annotations

import os
import tempfile

# conftest 会在测试模块收集前加载。这里先隔离数据根，避免测试模块在
# fixture 生效前构造 Repository/Service 并读取开发态用户数据目录。
_TEST_DATA_ROOT = tempfile.TemporaryDirectory(prefix="netconsole-pytest-")
os.environ["NETCONSOLE_DATA_ROOT"] = _TEST_DATA_ROOT.name
