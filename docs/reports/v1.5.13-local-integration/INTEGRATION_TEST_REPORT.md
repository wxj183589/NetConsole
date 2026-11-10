# v1.5.13 集成回归报告

日期：2026-11-10

## 通过项

| 范围 | 命令/证据 | 结果 |
| --- | --- | --- |
| MESH Renderer | 30 个 MESH test files | 335 passed；合并后再次 335 passed |
| MESH Python/API/raw/cache | `test_mesh_*.py` 与 export identity | 450 passed，3 warnings |
| AC-MESH | `test_ac_mesh_link_*.py` | 42 passed，1 warning |
| 合并后 MESH 核心 | raw sample、sampling、nearest、API、business statistics、query、report、web contract | 229 passed，3 warnings |
| Python MESH 扩展组合 | 所有文件名含 mesh 及 rebuild_mesh | 494 passed、1 次 Windows 文件锁时序失败；失败测试隔离复跑 1 passed |
| Renderer TypeScript/build | `pnpm run build`（含 `vue-tsc -b`、Vite） | PASS；有常规 >500 kB chunk warning |
| Electron Main | `pnpm run build:main` | PASS |
| Python lint/compile | Ruff、`compileall -q src tests` | PASS |
| Git | `git diff --check` | PASS |

## 全量 Renderer 限制

`pnpm test -- --runInBand`：210 files、1538 tests 中 209 files/1537 tests 通过。唯一失败是 `tracksideSeriesColors` 的机器相关性能阈值：实测 `112.3534ms`，要求 `<100ms`。测试中出现的 `localhost:3000` connection refused 是已有测试环境探测日志，未形成额外失败。

## 失败归因

AC-MESH 组合运行的唯一失败为 `test_interval_update_and_immediate_refresh_do_not_reconnect` 在 Windows 上读取/清理测试 SQLite/status 文件时出现 `PermissionError/WinError 32`；同一测试单独复跑通过，AC-MESH 文件集合随后 `42 passed`。没有将其改写为产品代码通过。

## 未执行或沿用的门禁

- 本轮没有重新启动 30 分钟 MESH 长稳；沿用 Phase 11.10 已有证据，但不冒充本轮结果。
- Excel 可执行文件缺失，未新增 Excel GUI 验收；既有 WPS 打开证据仍在 Phase 11.10 报告中。
- 未执行真实设备/现场网络验收，也未生成安装包或 Release。
- Workspace layout 检查复现既有 `D:/study/NetConsole-Workspace/docs` 顶层 blocker；未删除目录、未放宽规则。

## 数据边界

测试使用 Workspace 隔离根；未以 Production 或 `D:/NetConsoleData-dev` 作为运行根，未复制完整真实数据、未改真实数据库、设备或 fping。
