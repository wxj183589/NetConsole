# NetConsole DEV GUI / Export 最终验收报告

日期：2026-08-26
执行角色：主机 `codex-A`  线程：`01a03a12-10a0-7de1-90df-bdfe1220c0c4`

## 结论

本轮完成了 `D:\NetConsoleData-dev` 上的桌面启动、真实局点切换、FIT-AP/Radio/LLDP/Optical、轨旁 AP Snapshot/Export Process、Task Center、Update All 并发、重启恢复、SQLite 完整性和测试基线对比。

最终结论为 **PARTIAL，不具备主线 Push 条件**：

- 工程态 Current/Recent10 DEV 数据门禁、桌面启动、Renderer/Electron 自动化测试、导出任务和文件完整性通过。
- Update All 任务实际执行到 AC 采集，但因 DEV 中的设备 `10.122.100.10:22` TCP 不可达而失败；这是外部设备可达性问题，但按验收门禁不能记为 PASS。
- GUI 有 Electron 启动/渲染/路由/API/生命周期证据，但没有独立的鼠标点击录制工具，因此各 GUI 功能项保守标记为 PARTIAL。
- DEV `demo` 站点仍有 5 条同资源、同指纹、同时间戳的相邻历史记录；未现场修补，记录为数据遗留风险。
- 源码保留 Legacy HistoryStore 的迁移/兼容/TaskHistoryStore 符号；本次 DEV 运行未重建 `db/history`、未观察到工程态回退事件，但不能宣称源码层面完全删除兼容层。

## 环境

| 项目 | 结果 |
|---|---|
| 当前分支 | `main` |
| 本轮验收代码基线 / `MAIN_SHA` | `3610cd3e8825778058b04dc9ed53edf3fcc8df05` |
| 工程态实现提交 | `afa35c06` |
| 验收基线 | `538db1c3` |
| `github/main` | `e8b826b9`，本地领先 3 个提交 |
| `MAIN_PUSHED` | `NO` |
| `data_root` | `D:\NetConsoleData-dev` |
| `PRODUCTION_DATA_TOUCHED` | `NO` |
| DEV 站点数 | 11 |
| 活动站点数据库 | 34 个 `sites/*/db/*.db`，约 1.05 GiB |
| 数据库类型 | `devices.db`、`tasks.db`、`agents.db`、`snmp.db`、`global_mib.db` |
| 活动站点数据库 `PRAGMA quick_check` | 34/34 `ok` |

本轮没有读取、复制、写入、删除或迁移 `D:\NetConsoleData`。Update All 和导出产生的运行数据、任务、Artifact、XLSX 均在 DEV 根下。

## 验收关键字段

```text
MAIN_SHA=3610cd3e8825778058b04dc9ed53edf3fcc8df05
REMOTE_MAIN_SHA=e8b826b9
DATA_ROOT=D:\NetConsoleData-dev
PRODUCTION_DATA_TOUCHED=NO

DEV_ENGINEERING_DATA_CUTOVER=PASS
CURRENT_STATE_PARITY=PASS
FIT_AP_GUI=PARTIAL
RADIO_GUI=PARTIAL
LLDP_GUI=PARTIAL
OPTICAL_GUI=PARTIAL
TRACKSIDE_GUI=PARTIAL
GUI_ACCEPTANCE=PARTIAL
RADIO_CURRENT_RECENT10=PASS
LLDP_CURRENT_RECENT10=PASS
INTERFACE_CURRENT_RECENT10=PASS
OPTICAL_CURRENT_RECENT10=PASS
AP_OPTICAL_TREATMENT_UNIQUE=PASS
SITE_AP_COUNT=3366
TREATMENT_ROWS=322
TREATMENT_DUPLICATES=0
LLDP_MAX_RECENT=10
RADIO_MAX_RECENT=10
INTERFACE_MAX_RECENT=10
OPTICAL_MAX_RECENT=10
RESOURCE_OVER_10=0
NO_CHANGE_DUPLICATE_STORAGE=FAIL (demo adjacent same-state legacy rows=5)
LEGACY_HISTORYSTORE_RECREATED=NO
LEGACY_LLDP_EVENTS=0
LEGACY_RADIO_EVENTS=0
LEGACY_INTERFACE_EVENTS=0
LEGACY_OPTICAL_EVENTS=0
LEGACY_ENGINEERING_FALLBACK=0 (runtime)
TRACKSIDE_COLD_LOAD_MS=260.64
TRACKSIDE_WARM_LOAD_MS=267.66
TRACKSIDE_EXPORT_TOTAL_MS=6755
UPDATE_ALL_TOTAL_MS=9221
CONCURRENT_LOAD_EXPORT_UPDATE=FAIL (Update All external TCP failure)
DATABASE_LOCK_ERRORS=0
SQLITE_BUSY_COUNT=0
API_500_COUNT=0
DB_WRITE_TRANSACTION_MAX_MS=NOT_INSTRUMENTED
EXPORT_PROCESS=PASS
EXPORT_ACCEPTANCE=PASS
TRACKSIDE_EXPORT_PARITY=PASS
AP_OPTICAL_TREATMENT_EXPORT_UNIQUE=PASS
RESTART_RECOVERY=PASS
SQLITE_QUICK_CHECK=PASS
TARGETED_TESTS=PASS
RENDERER=PASS
ELECTRON=PASS
PYTHON_FULL=PARTIAL (4480 passed, 26 failed, 2 skipped)
NEW_TEST_FAILURES=0
PRODUCTION_CUTOVER_READY=NO
MAIN_PUSHED=NO
```

## 工程态数据门禁

| 门禁 | 证据 | 状态 |
|---|---|---|
| Current + Recent10 | Radio、Interface、Device LLDP、Device Optical、AP LLDP、AP Optical 各资源最大 Recent 为 10 | PASS |
| AP Optical Treatment 唯一性 | 11 个站点汇总 `TREATMENT_ROWS=322`；`(site_id, ap_identity)` 重复组为 0 | PASS |
| AP 覆盖关系 | `SITE_AP_COUNT=3366`；`TREATMENT_ROWS=322 <= SITE_AP_COUNT` | PASS |
| Legacy `db/history` | DEV 审计 `history_bytes=0`，本轮运行后仍未创建 `sites/*/db/history` | PASS |
| Legacy runtime fallback | bounded authority 已启用；本轮日志未发现工程态回退事件 | PASS（运行时） |
| Legacy source compatibility | `HistoryStore`、迁移 helper、`TaskHistoryStore` 和未启用 authority 的兼容分支仍在源码中 | PARTIAL（源码层） |
| 无变化不重复写入 | 定向 Recent10 测试通过；DEV `demo` 发现 5 条同资源同指纹同时间戳相邻遗留记录 | PARTIAL |
| SQLite 完整性 | 34 个活动站点数据库 `quick_check=ok` | PASS |

同指纹遗留记录集中在 `demo`：`device_interfaces_history` 2 条、`device_lldp_neighbors_history` 1 条、`device_optical_modules_history` 2 条，时间戳均为 `2026-06-13T09:00:30`。未删除、未改写真实/DEV历史数据；后续应建立单独的数据清理/语义确认任务。

## Electron Desktop 验收

| 项目 | 真实证据 | 状态 |
|---|---|---|
| 冷启动 | `backend.health_ready=3387.6ms`；`renderer.dom_ready=6370.0ms`；`renderer.mounted=6524.5ms`；`desktop.interactive=6591.0ms` | PASS |
| 重启启动 | `backend_health_ms=2996.3ms`；`renderer_ready_ms=6037.1ms`；窗口可见、Renderer 加载完成 | PASS |
| Backend ready | `/api/v1/health` 返回 `status=ok`、`runtime_services_ready=true`、`data_root=D:\NetConsoleData-dev` | PASS |
| Migration/schema mismatch | 本轮启动日志未发现迁移执行或 schema mismatch | PASS |
| Site switch | API 切换 Nbo12/Nbo10 约 409ms、342ms、226ms；Electron 日志记录 `SITE_SWITCH_BACKEND_HANDOFF_READY`、`renderer_reloaded=1`，Backend 正常停止 | PASS（运行时） |
| Site switch GUI 点击轨迹 | 无独立 GUI 自动点击/屏幕录制工具；使用 Electron 生命周期和 API/Renderer 路由证据替代 | PARTIAL |
| Backend restart | 发生在 site handoff 的设计路径，非异常崩溃；重启后 health、活动站点、页面数据均恢复 | PASS（受控 handoff） |

本轮的 `backend restart` 不能解释为完全消失：API 仍返回 `restart_required=true`，桌面端实际执行了受控 warm handoff；验收重点是 handoff 后窗口、Renderer、数据和任务状态可恢复。

## 真实功能结果

| 功能 | 真实数据证据 | 状态 |
|---|---|---|
| FIT-AP GUI | Nbo12 992 个 AP；page1 约 471ms、page2 约 382ms；Nbo10 page1 约 322ms；批量资源和详情接口 200 | PARTIAL（GUI 点击证据不足） |
| RADIO_GUI | 采样 AP 的 2 个 Radio 详情 200；重启后 history/radio 200 | PARTIAL |
| LLDP_GUI | 采样 AP detail/LLDP 200；Nbo12 history/lldp 200，返回 10 条边界内记录 | PARTIAL |
| OPTICAL_GUI | 采样 AP detail/optical 200；history/optical 200 | PARTIAL |
| TRACKSIDE_GUI | Nbo12 Snapshot 1,247 行，`partial_data=false`，unresolved 302、ambiguous 0；服务/API/Renderer 路由正常 | PARTIAL |
| Task Center | 历史中可读 2 个完成导出任务、2 个失败 Update All 任务，Artifact 元数据和失败原因可恢复 | PASS |
| Restart recovery | 重启后活动站点、FIT-AP、Trackside、History API、Task Center 均可读 | PASS |

## 性能数据

| 功能 | 优化前/历史基线 | 当前 DEV 证据 | 结果 |
|---|---:|---:|---|
| Site Switch | 历史 8.5–14.4s，原因是 Backend restart | API 226–409ms；Electron warm handoff ready 约 6.6s，Renderer reload 后恢复 | PARTIAL |
| FIT-AP | 旧验收为批量加载热点 | Nbo12 page1 约 471ms、page2 约 382ms；Nbo10 page1 约 322ms | PASS（服务路径） |
| Trackside snapshot | 历史约 72.4s/全量 build 风险 | 普通读取约 261–268ms；并发/导出中的 snapshot build 约 0.85–1.13s；`partial_data=false` | PASS（服务/快照） |
| Trackside export | 历史约 77.4s | Job Center 约 6.755s；snapshot build 1,132ms；render 3,817ms；XLSX 277,578 bytes | PASS |
| MESH table | 历史 11.59s、heap 3.22GB | 本任务未执行 MESH GUI 验收；不宣称已改善 | N/A |
| MESH chart | 本任务未覆盖 | 未执行 | N/A |
| Update All | 需要完整设备采集 | 约 9.221s，26/26 failed，原因 `TCP connection to device failed ... 10.122.100.10:22` | PARTIAL/FAIL |

### Snapshot / Export 证据

- 导出任务 `rail-export-e3e96d9e5a0f4142b0641970225c0f7c`：COMPLETED，行数 1,247，artifact `e6c63bfc-710c-4db9-bb1b-eed788c3e007`，应用层 content/export hash 稳定。
- 并发导出任务 `rail-export-09a1e7a5f58b4549a8ba67379f356a6b`：COMPLETED，artifact `657ce8b9-895e-4a1b-adfc-dfa39f99a2c3`，行数 1,247，`partial_data=false`。
- 两个 XLSX 均可由 `openpyxl` 只读打开；`AP光衰处理记录` 均为 102 行（含表头），完全重复行 0。
- 物理 XLSX SHA-256 因工作簿生成元数据/序列化不同而不同；应用层 snapshot/content/export 一致性字段正常。

## Update All 与并发

Update All 在 DEV 发起两次，均返回 202 并进入 Job Center。实际 AC 采集只使用只读命令，日志显示在 `display ...` 命令后因 `10.122.100.10:22` 不可达失败；没有发现写设备命令、HTTP 500、SQLite lock 或 `SQLITE_BUSY`。

并发场景同时执行 Update All、Trackside rows 查询和 Export：

- rows 请求全部 HTTP 200；Export 202 后 COMPLETED；Update All 202 后以外部 TCP 失败结束。
- `DATABASE_LOCK_ERRORS=0`、`SQLITE_BUSY_COUNT=0`、`API_500_COUNT=0`。
- Snapshot 结果均为完整快照，未观察到 `partial_data=true` 或半成品导出。
- 精确的数据库事务 `N/N+1` revision 边界和读写事务最大耗时没有单独埋点，本项不宣称完整 PASS。

因此 `CONCURRENT_LOAD_EXPORT_UPDATE` 的并发稳定性为 PASS，但包含真实 Update All 的整体场景为 PARTIAL。

## Legacy HistoryStore 退役验证

本次验收只对工程态运行结果作结论：

- `LEGACY_HISTORYSTORE_RECREATED=NO`：DEV 没有新增 `db/history`、catalog、monthly shard、outbox/state。
- `LEGACY_RUNTIME_FALLBACK_EVENTS=0`：当前 bounded authority 路径使用 Current/Recent10，Trackside page/export 使用 Current/active snapshot。
- `LEGACY_SOURCE_COMPATIBILITY=REMAINING`：源码仍保留迁移、兼容查询和 TaskHistoryStore，未在本轮删除；这不是新的运行时数据写入。
- 不把 TaskHistoryStore 的任务归档能力误判为工程态 Radio/LLDP/Interface/Optical 历史回退。

## Python / Renderer / Electron 测试门禁

### Full Python baseline comparison

使用同一 `.venv`、同一命令 `pytest -q --tb=no --capture=no`，并设置 UTF-8 环境：

| 集合 | 结果 |
|---|---|
| 基线 `538db1c3` | `4473 passed, 30 failed, 2 skipped, 32 warnings` |
| 当前 `414737ac` | `4480 passed, 26 failed, 2 skipped, 32 warnings` |
| `FAILURE_SET_ADDED` | `0` |
| `NEW_TEST_FAILURES` | `0` |
| 已解决基线失败 | 4 个：TypeScript AST guard、两个 release clean-build、web/electron AST guard |

当前保留的 26 个失败来自既有 architecture/README、光衰 fixture/兼容、MESH/持久化、Ground、Site lifecycle 等集合；没有把它们写成 Full Gate PASS，也没有现场修改。

### 其他自动验证

- 定向 Python 回归：`429 passed`。
- `python -m compileall -q src tests`：通过。
- Renderer：175 files，`1209 passed`；`pnpm build` 通过。
- Electron：35 files，`282 passed`；`build:main` typecheck/build 通过。
- `git diff --check`：通过。
- Renderer 测试中的 `ECONNREFUSED :3000` 为最终计数通过的探针噪声；关闭窗口期间的网络错误和一个陈旧设备 UUID 测试日志不作为本轮工程态数据失败。

## 问题列表

### PASS

- DEV 数据根隔离、生产根未触碰。
- 活动站点数据库 quick_check 全通过。
- Current/Recent10 上限、Treatment 唯一键、Snapshot 完整性。
- Electron Backend/Renderer 启动和重启恢复。
- FIT-AP/Radio/LLDP/Optical 服务路径和 Trackside API。
- Export Process、Artifact、XLSX 可读性和 Task Center 历史恢复。
- 并发期间无 SQLite lock、`SQLITE_BUSY` 或 HTTP 500。
- 当前相对基线没有新增 Python 失败。

### PARTIAL

- GUI 各页面缺少独立自动点击/屏幕录制证据。
- Update All 因设备 TCP 不可达失败，不能作为业务成功验收。
- Legacy HistoryStore 源码兼容层仍存在，但 DEV 运行时未回退。
- demo 站点 5 条同资源同指纹相邻历史遗留记录。
- 精确 revision N/N+1 原子边界和事务耗时未单独埋点。
- Python Full Gate 仍有 26 个与本轮无新增关系的失败。

### FAIL

- 本轮没有发现需要现场打补丁的代码回归；Update All 业务结果本身为失败，但证据指向外部设备连接，不指向数据库锁或本轮代码异常。

## 交付与主线状态

- 本轮没有修改业务代码、业务模型、AP Identity、LLDP 规则或生产数据。
- 必需报告为本文件；旧的未跟踪审计报告保持原样，未混入本次提交。
- `MAIN_PUSHED=NO`：由于 Update All、GUI 自动点击和 Full Gate 尚未全部通过，不执行 push。
- 若后续需要代码修复，应单独建立任务，不混入本验收报告提交。

## 下一步建议

1. 先恢复/确认 DEV AC `10.122.100.10:22` 的受控可达性，只重跑 Update All 验收，不修改采集命令和业务模型。
2. 使用独立 GUI 自动化或人工录屏补齐 FIT-AP、Radio、LLDP、Optical、Trackside、Site Switch 的点击级证据。
3. 单独处理 `demo` 站点 5 条同指纹遗留记录：先定义导入/重复语义，再做可回滚的 DEV-only 清理；本轮不删除。
4. 单独清理或收敛 Legacy HistoryStore 源码兼容层，必须先做 Change Impact 和回归，不把 TaskHistoryStore 一并删除。
5. 在独立 MESH 任务中继续 GUI 首屏、滚动、long-task、heap、chart/report export 验收；本报告不把 MESH GUI 标记为已完成。
