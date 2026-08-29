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

## 2026-08-26 Desktop 真实启动验收（本轮实际运行）

本节只记录本轮从启动到退出、重启和最终 DEV 只读检查取得的证据，不复用上一轮“设备不可达”结论，也不把 API/数据库检查替代 GUI 点击证据。

### 机器可读硬证据

```text
CODE_BASELINE_SHA=bdf7491bdedbe32dca981585142e7f0e9b83ca43
REMOTE_MAIN_SHA=e8b826b9
MAIN_PUSHED=NO
DATA_ROOT=D:\NetConsoleData-dev
PRODUCTION_DATA_TOUCHED=NO
ELECTRON_STARTED=YES
ELECTRON_PID=17816 (first run); 51596 (restart run)
BACKEND_STARTED=YES
BACKEND_PID=41808/42020 (first run); 48056/42380 (restart run)
VITE_PID=48868 (first run); 39404 (restart run)
WINDOW_VISIBLE=YES
WINDOW_RESPONDING=YES
ACTIVE_SITE=宁波地铁12号线
RUNTIME_DATA_ROOT=D:\NetConsoleData-dev
GUI_SCREENSHOT_COUNT=29
TCP_10.122.100.10_22=PASS
SSH_AUTH=PASS
SSH_COMMAND=PASS
GUI_CLICK_ACCEPTANCE=PARTIAL
REAL_UPDATE_ALL_STARTED=YES
REAL_UPDATE_ALL=FAIL
UPDATE_ALL_TOTAL_MS=213947,208733,8905
REAL_EXPORT_GUI_CLICK=YES
REAL_EXPORT=PASS
EXPORT_TOTAL_MS=6930,6886,6277
CONCURRENCY_ROUNDS=3
CONCURRENT_LOAD_EXPORT_UPDATE=PARTIAL
DATABASE_LOCK_ERRORS=0
SQLITE_BUSY_COUNT=0
API_500_COUNT=0
API_TIMEOUT_COUNT=0
UI_FREEZE_COUNT=0
LLDP_MAX_RECENT=10
RADIO_MAX_RECENT=10
INTERFACE_MAX_RECENT=10
OPTICAL_MAX_RECENT=10
SITE_AP_COUNT=993
TREATMENT_ROWS=109
TREATMENT_DUPLICATES=0
LEGACY_HISTORYSTORE_RECREATED=NO
LEGACY_ENGINEERING_FALLBACK=PARTIAL (runtime bounded_v1; source compatibility branches remain)
DEMO_RECENT10_PARITY=FAIL
RESTART_RECOVERY=PASS
ALL_SQLITE_QUICK_CHECK=PASS (34 active site databases)
NEW_TEST_FAILURES=NOT_RERUN (no code change in this run)
DEV_ENGINEERING_DATA_CUTOVER=NO
```

本轮第一次启动时间约为 `2026-08-26 21:52:17`，重启进程启动时间为 `2026-08-26 22:24:13`。两次启动均由标准 `pnpm dev:codex` 完成；Vite ready、warmup ready、Electron starting、Backend health `ok` 均有终端/API证据。第一次正常退出和重启前第二次正常退出均先停止启动器并确认 `Terminate batch job (Y/N)?`，随后对应 Electron/Backend PID 清零、5173/8000 无监听，未使用 kill -9。

### GUI Runtime Evidence

- 本轮真实 GUI 先进入 FIT-AP 资源，再进入轨旁 AP 业务；截图 `19-fitap-after-tab.png` 显示宁波 12 号线 `993 AP / 939 在线 / 54 离线 / 1 未认证 / 1986 Radio`。
- 真实点击 AP `bc5a-3457-a5c0` 的“详情”，截图 `20-fitap-detail-click.png` 显示型号、AC 连接、Mesh Radio 1/2、LLDP/端口和当前光衰。
- 真实点击 Radio 历史，截图 `21-mesh-history-click.png` 打开 `Radio 历史` 面板；本 AP 当前没有历史记录，因此 Radio 历史实际显示 `0` 条，不能宣称已有历史数据通过。
- 真实点击 LLDP 历史，截图 `23-lldp-history-click.png` 打开 LLDP 历史并显示 `10` 条，来源、邻居接口和邻居设备字段可见。
- 真实查看详情中的光衰区域，截图 `20-fitap-detail-click.png` 显示 AP 侧 `-7.55 dBm`、交换机侧 `-7.14 dBm`、综合判定正常；光衰历史链接本轮未成功打开，记为 `MANUAL_REQUIRED/PARTIAL`。
- 真实进入轨旁 AP 业务，截图 `29-restart-trackside-page.png` 显示当前局点宁波 12 号线、`1247` 行、`993` 个 AP、`939` 在线；本轮完成筛选/查询点击、刷新点击、页面切换和返回页面，窗口始终 Responding，无白屏。
- AP 光衰处理记录专门入口未在本轮 GUI 中成功打开，因此 GUI 总验收为 `PARTIAL`；DEV 数据库只读检查仍确认 `(site_id, ap_identity)` treatment 重复为 `0`。
- 截图均来自本轮运行并保存在 `D:\study\diagnostic\NetConsole\desktop-acceptance-20260826`，未加入 Git。

### Network Evidence

- 本轮新执行 TCP 连接测试：`2026-08-26T22:39:19.886+08:00`，目标 `10.122.100.10:22`，`TCP_REACHABLE=True`；这覆盖并取代上一轮的失败结论。
- 本轮 AC 只读采集命令日志包含 `screen-length disable`、`display wlan ap all`、Radio、connection-record、unauthenticated、LLDP 等 9 条命令；最近的有效 commands JSONL 为 `9/9 success, 0 failed`。因此 `SSH_AUTH=PASS`、`SSH_COMMAND=PASS`。
- 采集任务使用真实 AC 设备链路；未发现写设备命令。命令和原始回显只留在 DEV 数据根，未提交。

### Real Update All / concurrency

三轮均从轨旁 AP 页面右上角真实点击“更新全部光衰”，再通过 Job Center 读取任务状态；Job Center 查询只是监控，不是替代 GUI 触发。

| Round | GUI click / task | 结果 | 设备/任务耗时 | 证据 |
|---|---|---|---:|---|
| 1 | `rail-web-21711745244e4186b5a51a48011bf8d9` | `COMPLETED/PARTIAL_SUCCESS`，`success=965`，`skipped=54`，`primary_failure_reason=connection_incomplete` | `213.947s / 213947ms` | `11-after-updateall-click.png`、Job Center 详情 |
| 2 | `rail-web-194fe2157e1c46acbbbe60a5171fd35c` | `COMPLETED/PARTIAL_SUCCESS`，`success=965`，`skipped=54`，`primary_failure_reason=connection_incomplete` | `208.733s / 208733ms` | `13-after-concurrent-export-click.png`、Job Center 详情 |
| 3 | `rail-web-3635237564c64b56a3fa6b45a43e980a` | `FAILED`，`failed=26/27`，`skipped=1`，`primary_failure_reason=device_collection_failed` | `8.905s / 8905ms` | FIT-AP 失败通知、Job Center 详情 |

第一、第二轮 Update All 运行期间均真实点击了页面操作和轨旁 AP 导出：

- Round 1 导出 `rail-export-5c44b8b37584419c9f7402d254814aff`：`COMPLETED/SUCCESS`，`1247/1247`，`6.930s`，Artifact 290,279 bytes，SHA-256 `b84c55a24460ae90b797b0ea6297b0ac7c1a649e7830f70d9f793bac24153b21`。
- Round 2 导出 `rail-export-a882d3fc4f0c4d5bbaec1cea43a700c9`：`COMPLETED/SUCCESS`，`1247/1247`，`6.886s`，Artifact 290,400 bytes，SHA-256 `55dad37bc734ba2dc0e3cb73e24c7aadd8b2dccaf310927ec0d502bb4e3565a5`。
- Round 3 Update All 在约 8.9 秒内失败，未把失败后的非重叠导出冒充第三个并发成功轮；因此 `CONCURRENCY_ROUNDS=3`，但整体门禁为 `PARTIAL`，不是 `PASS`。

三轮页面/导出/Update All 期间没有观察到 `database is locked`、`SQLITE_BUSY`、HTTP 500、API timeout 或无响应窗口；运行时目录检索相应错误为 `0`。导出任务均通过独立 Export Process 生成 Artifact，没有 UI 冻结证据。

### Restart recovery evidence

重启后新窗口截图 `25-restart-window.png` 显示 Dashboard、`Backend Online` 和构建标识；真实点击 FIT-AP、展开轨道交通、进入轨旁 AP 业务后，截图 `26-restart-fitap-click.png`、`29-restart-trackside-page.png` 显示数据仍可读。重启后再次从轨旁 AP 页面真实点击导出，任务 `rail-export-dd3b22b70cf84e31a2f3ec700329d040` 为 `COMPLETED/SUCCESS`，`1247/1247`，`6.277s`，Artifact 275,043 bytes，SHA-256 `72071b7ebf9421b9846de9a1ee2b9074048ad2645001a923176dc2224805a777`。因此 `RESTART_RECOVERY=PASS`。

### Database / retention / legacy evidence

- 关闭应用后只读扫描 `D:\NetConsoleData-dev\sites`：实际 `11` 个 Site、`34` 个 SQLite；全部 `PRAGMA quick_check=ok`。
- 活动宁波 12 号线 `devices.db`：`ac_fit_ap_resources=993`、`fit_ap_radio_current=1986`、`fit_ap_lldp_current=993`、`optical_current=1894`、`ap_optical_treatment=109`。
- 所有活动 Site 的 Radio、FIT-AP LLDP、Interface、Optical history 按资源分组的最大 Recent 均不超过 `10`；本轮各机器可读门禁取值为 `10`。
- `TREATMENT_ROWS=109`、`SITE_AP_COUNT=993`、`TREATMENT_DUPLICATES=0`。
- `sites/*/db/history` 目录数为 `0`，未发现 `catalog.db` 或 `devices-YYYY-MM.db`，所以 `LEGACY_HISTORYSTORE_RECREATED=NO`。
- 普通 `demo` fixture 仍有同 fingerprint 重复：Device LLDP 1 组、Interface 2 组、Device Optical 2 组，共 5 条重复行；这不是本轮删除数据的授权，故 `DEMO_RECENT10_PARITY=FAIL`，后续须单独定义 DEV-only 清理/迁移任务。
- 源码扫描发现 `ac_repository.py` 在 authority 未启用时仍保留 LLDP legacy 查询分支（例如行 1980、2106、2174、2350、2456、2480、2544），`device_fact_repository.py` 仍有 `query_legacy_rows` 路径。当前 11 个 Site 的 bounded authority/Current 路径均为 `bounded_v1`，本轮运行未产生回退事件；但源码门禁不能写为 `0`，记为 `LEGACY_ENGINEERING_FALLBACK=PARTIAL`。

### 本轮问题与结论

#### PASS

- Electron、Backend、Vite 实际启动；窗口可见、可响应，DataRoot 明确为 DEV。
- 当前 TCP/SSH/只读 AC 命令链路通过；本轮不沿用旧网络失败。
- FIT-AP 列表、AP 详情、LLDP 历史、轨旁 AP 页面、两轮并发 Export 和重启后 Export 通过。
- 11 Site/34 DB quick check、Current/Recent10 上限、Treatment 唯一性和 Legacy HistoryStore 目录不复生通过。
- 三轮并发没有 SQLite lock、`SQLITE_BUSY`、HTTP 500、API timeout 或 UI freeze。

#### PARTIAL / FAIL

- Update All 没有一轮完整成功：两轮 `PARTIAL_SUCCESS`，一轮 `FAILED`；因此 `REAL_UPDATE_ALL=FAIL`、`CONCURRENT_LOAD_EXPORT_UPDATE=PARTIAL`，不满足 Push Gate。
- Radio 历史本 AP 显示 0 条、光衰历史和 Treatment 入口未完成 GUI 点击，GUI 总验收为 `PARTIAL`。
- 普通 demo 存在 5 条同 fingerprint 历史重复；源码仍保留 Legacy engineering compatibility 分支。
- MESH GUI 首屏/滚动/long-task/heap/chart/report export 不在本轮范围，不能宣称 MESH GUI 已验收。

该节 Desktop 真实启动验收结论：`MAIN_PUSHED=NO`，`DEV_ENGINEERING_DATA_CUTOVER=NO`。其结论不包含下方新增的 tasks.db candidate maintenance 与工程态 Recent UI 补充；生产数据仍未访问或修改。

## 2026-08-27 tasks.db 空间审计与候选瘦身补充

本节为同一轮 Engineering Data Cutover Closure 的 tasks.db 补充证据。所有 destructive candidate 验证仅针对 `D:\NetConsoleData-dev`；`D:\NetConsoleData` 未访问、未修改。完整表级 JSON/Markdown 报告见 `D:\study\diagnostic\NetConsole\tasks-db-20260827-final\TASKS_DB_SPACE_AUDIT.json` 和 `TASKS_DB_SPACE_AUDIT.md`。

### 机器可读指标

```text
TASKS_DB_BEFORE_BYTES=457744384
TASKS_DB_AFTER_BYTES=416567296
TASKS_DB_RECLAIMED_BYTES=41177088
TASKS_DB_RECLAIM_PERCENT=8.995651%
SITE_TOTAL_BEFORE=8269204955
SITE_TOTAL_AFTER=8227700187
SITE_TOTAL_RECLAIMED_BYTES=41504768
EXTERNAL_BYTES_CREATED=1291091968
TASKS_TOP_TABLE_BEFORE=宁波地铁12号线:task_results,宁波地铁12号线:task_events,hzl10:task_events
TASKS_TOP_TABLE_AFTER=宁波地铁12号线:task_results,宁波地铁12号线:task_events,hzl10:task_events
TASK_EVENTS_ROWS_BEFORE=339779
TASK_EVENTS_ROWS_AFTER=339779
TASK_SNAPSHOTS_ROWS_BEFORE=6070
TASK_SNAPSHOTS_ROWS_AFTER=6070
DUPLICATE_PAYLOAD_ROWS_REMOVED=2173
OBSOLETE_SNAPSHOT_ROWS_REMOVED=0
TASK_LIST_PARITY=PASS
TASK_DETAIL_PARITY=PASS
TASK_RESTART_RECOVERY=PASS
TASKS_DB_QUICK_CHECK=PASS
TASKS_DB_SIZE_REDUCTION=PASS (aggregate; individual demo/legacy equal, sxl1 +20480 bytes)
TASKS_DB_CANONICAL_RESULT_AUTHORITY=PASS
TASKS_DB_DUPLICATE_PAYLOAD_REMOVED=PASS
TASKS_DB_OBSOLETE_SNAPSHOT_RETIREMENT=PASS
PRODUCTION_DATA_TOUCHED=NO
```

`task_results.canonical_json` 是唯一任务结果 authority；snapshot/event full result projection 从 `4653` 行、`66088709` 字节降至 `184` 行、`220198` 字节。task、event、snapshot 行本身未删除；重复 progress `52626` 行仅审计、未按 Recent10 删除。Online MR current session 9 行和 Ground current mapping 均保留并通过 parity。

本机 Python SQLite 未提供 `dbstat` 虚表，因此报告中的 `table_bytes/index_bytes` 是逻辑字段/key 权重归一化估算，payload 字段长度/总字节为 SQL 精确统计；未将估算冒充物理精确值。各次候选替换保留 rollback 副本，累计 `EXTERNAL_BYTES_CREATED=1291091968`，该空间没有计入回收；临时 staging/candidate 已清理。

tasks.db 相关实现与回归：新增 `scripts/maintenance/tasks_db_compaction.py` 及 `tests/test_tasks_db_compaction.py`；compaction 测试 `5 passed`，Task Center/结果 authority/Online MR/Job Center/存储治理定向回归 `139 passed`，Renderer 定向测试 `35 passed`，Renderer build 成功。真实安装包、设备现场、并发 Update All/Export GUI 点击和完整主线 Push Gate 仍沿用上文 `PARTIAL/UNVERIFIED` 结论，不因数据库候选 parity 自动升级。

## 2026-08-27 Engineering Current/Recent10 与 Update All Closure

本节是本轮“剩余三个阻塞项”收口结果，覆盖 Legacy engineering fallback/writer、demo Recent10 重复和 Update All partial/current/snapshot 语义。它不执行数据库迁移，不进入 Production；本节结论覆盖并更新上文相同阻塞项的旧状态。

### Scope / data boundary

```text
DATA_ROOT=D:\NetConsoleData-dev
PRODUCTION_DATA_TOUCHED=NO
PRODUCTION_MIGRATION=NOT_RUN
PRODUCTION_VALIDATION=NOT_RUN
DEV_DATA_REPAIR=DEV_ONLY
```

- 未读取、复制、写入、删除或迁移 `D:\NetConsoleData`。
- 没有重复整套数据库迁移；没有新增 `db/history`、catalog 或月分片。
- `demo` 精确去重前创建了 DEV 备份：`D:\study\backup\NetConsole\dev-demo-dedupe-20260827-devices.db`。仅删除 5 条由同一 `demo-collect-run-0001`、同一时间戳和同一 fingerprint 共同证明为重复的历史行；没有 VACUUM、迁移或跨站点清理。

### Legacy engineering authority

```text
ENGINEERING_TARGET_LEGACY_READERS=0
ENGINEERING_TARGET_LEGACY_WRITERS=0
LEGACY_ENGINEERING_FALLBACK=0
LEGACY_HISTORYSTORE_RECREATED=NO
NON_TARGET_HISTORYSTORE=RETAINED
```

- Interface、Device LLDP、Device Optical、FIT-AP Radio/LLDP/Optical 的运行时读写统一落在 bounded Current + Recent10 表；首次 Current 建立不创建 Recent，只有语义变化才写入 Recent。
- Trackside Snapshot/Export/Update All 只消费 Current/active snapshot；四类工程事实不再向 `HistoryStore` 回退或写入 `history_outbox`。
- `HistoryStore` 仍保留给非本次四类范围的既有 owner（例如 device fact、资源/未认证历史）；本轮没有扩大删除范围。
- 静态 cutover guard、Legacy compatibility 回归和运行后 `db/history` 扫描通过；活动 DEV 数据库没有重新生成 Legacy 文件。

### Demo Recent10 parity

```text
DEMO_RECENT10_PARITY=PASS
DEMO_DUPLICATE_GROUPS=0
DEMO_DUPLICATE_ROWS_REMOVED=5
RECENT_MAX_VIOLATIONS=0
```

Demo fixture 已改为稳定身份字段和明确的状态变化序列；相同状态重放不产生 Recent。DEV 仅对可证明的 5 条历史重复行做了精确删除。收口后的 34 个活动站点数据库中，LLDP/Radio/Interface/Device Optical/AP Optical 每资源 Recent 最大值均不超过 10，实际最大值为 10。

### Real DEV Update All

后端源码以显式 `NETCONSOLE_DATA_ROOT=D:\NetConsoleData-dev` 启动；活动局点为 DEV 现有宁波 12 号线数据。每轮均由真实 Update All 任务执行并从 Job Center 读取最终业务结果：

| Round | Task | Duration | Result counts | Business result |
|---|---|---:|---|---|
| 1 | `rail-web-2014f79382b7419989c273987b0ffc76` | 201.1s | target 1019 / success 965 / skipped 54 / failed 0 | `PARTIAL_SUCCESS` |
| 2 | `rail-web-6e5a16940ffd48da823a2b6442544443` | 201.7s | target 1019 / success 965 / skipped 54 / failed 0 | `PARTIAL_SUCCESS` |
| 3 | `rail-web-a490944a09454e81a0d965813b9949ac` | 171.1s | target 1019 / success 965 / skipped 53 / failed 0 | `PARTIAL_SUCCESS` |
| 4 | `rail-web-0f8b6aaa028440e6a7281dea112d61c4` | 176.5s | target 1019 / success 965 / skipped 54 / failed 0 | `PARTIAL_SUCCESS` |

```text
REAL_UPDATE_ALL_RUNS=4
REAL_UPDATE_ALL_SOFTWARE_FAILURES=0
REAL_UPDATE_ALL_FAILED_DEVICE_COUNT=0
REAL_UPDATE_ALL_FAILURE_REASON_COUNTS={}
REAL_UPDATE_ALL_SKIPS=EXTERNAL_CONNECTION_INCOMPLETE
CONCURRENCY_ROUNDS=3
DATABASE_LOCK_ERRORS=0
SQLITE_BUSY_COUNT=0
API_500_COUNT=0
API_TIMEOUT_COUNT=0
```

Round 2/3/4 同时执行 Trackside rows 查询和 Export；rows 请求均 HTTP 200，Export 均约 2.1s 完成并生成可读 Artifact（Round 3 Artifact 293057 bytes）。没有观察到 SQLite lock、`SQLITE_BUSY`、HTTP 500 或超时。DEV 设备没有产生真实 failed-device 样本，因此“失败设备保留旧 Current”由自动化测试覆盖，而不冒充真实设备证据；失败/无效快照测试已通过。

Update All 的业务状态保持 `PARTIAL_SUCCESS`，因为 DEV 现有 AP 资源存在不可连接目标；没有把“跳过”伪装为成功，也没有覆盖失败或无效采集对应的既有 Current。AC resource、switch、FIT-AP、persistence 失败均使用结构化 `target/device/ip/stage/exception/message/duration` 明细，当前四轮真实运行的 software failure count 为 0。

### DEV invariants

```text
DEV_SITE_COUNT=11
DEV_ACTIVE_DATABASE_COUNT=34
ALL_SQLITE_QUICK_CHECK=PASS (34/34)
RECENT10_MAX=10
TREATMENT_ROWS=330
TREATMENT_DUPLICATES=0
ACTIVE_SITE_AP_COUNT=3367
```

活动数据库范围为各站点的 `agents.db`、`devices.db`、`snmp.db` 和 `tasks.db`；不把旧备份或原始采集数据库混入活动库统计。运行后 Legacy audit 报告为 `history_bytes=0`、`history_files=0`、`events=0`、`history_dirs=0`。

### Final automated verification

```text
CLOSURE_TARGETED_PYTHON=PASS (303 passed)
PYTHON_FULL=4491 passed, 27 failed, 2 skipped
BASELINE_FAILURE_SET=28 failures (one TypeScript AST environment failure)
NEW_TEST_FAILURES=0
RENDERER=175 files / 1218 tests passed
ELECTRON=35 files / 282 tests passed
RENDERER_BUILD=PASS
ELECTRON_TYPECHECK=PASS
RUFF=PASS
PY_COMPILE=PASS
GIT_DIFF_CHECK=PASS
CHANGE_IMPACT=L3
```

Python Full 的 27 个失败均可在独立 baseline failure set 中复现，集中于既有 architecture/direct-SQL/README、AC optical 旧 fixture、Ground/Site lifecycle 和其他未纳入本轮的存量门禁；不包含本轮新增失败。`local_gate --mode full` 的最终组合结果另在交付回复中如实报告，不将 baseline failure 写成全量 PASS。

`local_gate --mode full` 实际结果为 `FAIL`：Renderer/Electron/Ruff 通过；`python-full` 复现上述 27 个 baseline failures；`architecture-guards` 受既有 `storage_audit_router`、未分类 direct SQL 以及工作区未跟踪 tasks.db compaction 文件影响；`main-contract-smoke` 复现 AC optical 旧 fixture；`docs-path-guards` 复现 `tests/storage/README.md` 缺失；`git-diff-check` 仅报告既有 dirty 文件的行尾/EOF 问题。没有通过放宽断言、删测或 skip 隐藏这些结果。

### Closure / push fields

```text
LOCAL_MAIN_SHA=d5c6c4a163aaa14f86b4c8eda1a69cb522935bf1
REMOTE_MAIN_SHA=d5c6c4a163aaa14f86b4c8eda1a69cb522935bf1
MAIN_PUSHED=YES
PRODUCTION_CUTOVER_READY=NO
MESH_GUI_SCOPE=NOT_IN_THIS_TASK
```

代码收口提交 `d5c6c4a163aaa14f86b4c8eda1a69cb522935bf1` 已推送到 `github/main`；本节报告元数据提交晚于该代码 SHA。Production cutover 仍需另行授权和另行任务，本报告不宣称 Production 已验证或可自动迁移。

## 2026-08-27 Recent Change UI 真实 Electron 终验

本节更新此前 GUI `UNVERIFIED` 状态，仅针对源码 Electron + DEV 数据根，未操作已安装生产实例。

```text
GUI_REAL_ACCEPTANCE=PASS
ELECTRON_SOURCE_PID=31324
BACKEND_PID=31020 (child=31504)
VITE=http://127.0.0.1:5173
ACTIVE_SITE=宁波地铁12号线
WINDOW_VISIBLE=YES
WINDOW_RESPONSIVE=YES
DATA_ROOT=D:\NetConsoleData-dev
PRODUCTION_DATA_TOUCHED=NO
```

### GUI acceptance matrix

| 证据 | 结果 |
| --- | --- |
| AP A `30f5-277a-1ac0` Radio Recent=0 | PASS；Current 保留，显示“最近变化：暂无”，无空弹窗 |
| AP B `30f5-277a-1680` Radio/LLDP | PASS；4/7，实际弹窗行数与总数一致 |
| AP C `30f5-277a-25a0` | PASS；重启后 Radio/LLDP=10，Radio 弹窗 10 行 |
| Radio 1/2 | PASS；Current 行独立 |
| LLDP | PASS；source、local/neighbor interface、neighbor MAC/device 可见 |
| FIT-AP Optical | PASS；AP-side/SWITCH-side Current 台账，无独立 Treatment History 入口 |
| Device Interface/Optical/LLDP | PASS；Current 首屏，Recent 点击后读取；Interface 实际弹窗 2 行 |
| FIT-AP 列表与详情请求 | PASS；列表无 Recent N+1，详情初始只取计数，明细仅点击后请求 |
| Trackside AP | PASS；rows 请求存在，Recent/History 请求 0 |

截图证据保存在 `D:\study\diagnostic\NetConsole\recent-change-ui-20260827`：`17-zero-detail.png`、`11-radio-recent.png`、`12-lldp-recent.png`、`23-c-detail-capped.png`、`24-c-radio-recent-10.png`、`29-device-detail-open.png`、`32-interface-recent-dialog.png`、`03-task-closed.png`。

### API and DEV storage closure

```text
API_200_EMPTY_SEMANTICS=PASS
API_500_ERROR_SEMANTICS=PASS (automated error-state contract; no production call)
FIT_AP_LIST_RECENT_N_PLUS_ONE=0
FIT_AP_DETAIL_RECENT_BEFORE_CLICK=0 (history endpoint)
TRACKSIDE_RECENT_REQUESTS=0
LEGACY_HISTORYSTORE_RECREATED=NO
DB_HISTORY_BEFORE_STOP=0 files / 0 bytes
DB_HISTORY_AFTER_STOP=0 files / 0 bytes
DEV_SITE_COUNT=11
DEV_ACTIVE_DATABASE_COUNT=34
ALL_SQLITE_QUICK_CHECK=PASS (34/34)
RECENT10_MAX_BY_RESOURCE_SLOT=10
TREATMENT_ROWS=330
TREATMENT_DUPLICATE_GROUPS=0
DATABASE_LOCK_ERRORS=0
SQLITE_BUSY_COUNT=0
API_5XX_COUNT=0
API_TIMEOUT_COUNT=0
```

`db\history` 只发现旧 migration 目录中的空占位路径，无 runtime HistoryStore 文件；非本任务范围的长期 HistoryStore owner 及 legacy resource/unauthenticated 表保留。AP A/B/C 直接 DEV 证据为 Radio 0、4、有效窗口 10，LLDP 1、7、10；AP C 原始 Radio 聚合 16 是两个 Radio 槽位的旧行总和，按 `ap_identity+radio_id` 每槽不超过 10，API/UI 返回窗口封顶为 10。

### Code and test gate

本轮新增最小修复：FIT-AP 与设备详情的 Recent 计数/明细总数均在 API 层封顶 10，避免旧数据聚合计数被 UI 显示成可继续翻页的永久 History。定向 Python、Renderer、Electron 测试均通过；Renderer `vue-tsc`/build、Electron typecheck/build main、Ruff、compile、Change Impact(`L2`) 通过。

```text
PYTHON_FULL=4493 passed, 26 failed, 2 skipped
BASELINE_FAILURES=26 (architecture/direct-SQL, missing tests/storage/README.md, AC optical fixture, Ground archive, Site lifecycle)
NEW_TEST_FAILURES=0
RENDERER_TARGETED=35 passed
ELECTRON=282 passed
RENDERER_BUILD=PASS
ELECTRON_TYPECHECK=PASS
ELECTRON_BUILD_MAIN=PASS
RUFF=PASS
PY_COMPILE=PASS
GIT_DIFF_CHECK=PASS
CHANGE_IMPACT=L2
LOCAL_GATE_FULL=FAIL (既有 baseline；不删测、不弱化断言)
```

```text
PRODUCTION_CUTOVER_READY=NO
MESH_GUI_SCOPE=NOT_IN_THIS_TASK
```
