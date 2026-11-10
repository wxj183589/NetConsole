# 第四轮测试报告

日期：2026-11-10
Branch：`codex-A/global-dataroot-disk-policy`

## 最终通过项

| 范围 | 命令/内容 | 结果 |
|---|---|---|
| Renderer MESH | `pnpm exec vitest run src/components/mesh-analysis` | 26 files / 244 passed |
| Renderer 类型 | `pnpm exec vue-tsc -b --pretty false` | PASS |
| Python MESH 后端组合 | `test_mesh_analysis_query_service.py`、`test_mesh_analysis_web_api.py`、`test_mesh_web_contract.py` | 131 passed / 2 warnings |
| raw/采样/nearest | `test_mesh_raw_sample_query.py`、`test_mesh_monitor_sampling.py`、`test_mesh_monitor_nearest.py` | 29 passed / 1 warning |
| Python 静态检查 | 修改范围 Ruff | PASS |
| Python 编译 | 修改范围 `py_compile` | PASS |

警告均为既有依赖/Starlette deprecation warning；没有测试失败。

## 新增/修改测试覆盖

- `meshRawSampleCache.test.ts`：scope/identity 隔离、重复时间戳、毫秒 gap、incomplete response、LRU、context predecessor、counter delta/per-second、reset、role change、long gap 和 raw immutability。
- `MeshPhase11Workbench.test.ts`：兼容旧 response 的 fallback，以及单个完整 raw response 被多个图表、历史和时间定位共享。
- `test_mesh_raw_sample_query.py`：真实 SQLite fixture raw context、截断完整性、role filter 与真实 FastAPI route DTO/SQL trace。

## 测试解释

上述 Python 命令使用仓库 `.venv\Scripts\pytest.exe`，并把仓库根目录及 `src` 置于本次进程的 `PYTHONPATH`，以避免 Windows 环境中第三方 `tests` 包遮蔽仓库 `tests` namespace。没有修改测试包结构或业务代码来绕过该环境问题。

## 未执行/不宣称

- 未执行 Python 全仓库全量套件、Electron 原生 GUI、截图、Windows DPI、Excel/WPS GUI。
- 未执行 100 次交互、30 分钟长稳、JS Heap/RSS 观测。
- 未把真实 HTTP query duration 当成图表绘制完成时间。
- 未把 fixture 对照写成真实 Renderer 业务字段逐条对照通过。

因此自动化 MESH 回归通过，但本轮最终验收仍为 `PHASE_11_9_FOURTH_ROUND=PARTIAL`。
