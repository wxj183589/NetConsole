# MESH Full Regression

## 自动化结果

| 检查 | 结果 |
|---|---|
| Renderer MESH/Vue tests | 30 files, 330 passed |
| Python MESH/ac-mesh regression | 491 passed, 3 warnings |
| Electron TypeScript | PASS |
| Vue TypeScript | PASS |
| Electron `build:main` | PASS |
| Ruff `check src tests` | PASS |
| Python `compileall -q src tests` | PASS |
| `git diff --check` | PASS |
| `scripts.check_workspace_layout --repo-only` | FAIL: existing Workspace top-level `docs` |
| `scripts.check_workspace_layout` | FAIL: same existing top-level `docs` |

## Python 命令

使用仓库 `.venv\Scripts\python.exe` 执行 MESH 文件集合；系统 Python 没有 pytest，不作为项目回归解释器。3 个 warnings 是 Starlette/httpx 与 HTTP 422 常量 deprecation，不是测试失败。

## 范围说明

本报告覆盖 MESH analysis、raw sample/cache、MESH web API、catalog/source/parsed data、AC MESH link 和 identity 相关测试。Excel/WPS、真实设备和现场采集不属于本轮自动化 gate。
