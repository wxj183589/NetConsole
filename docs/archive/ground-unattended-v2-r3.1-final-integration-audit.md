# Ground Unattended V2 R3.1 最终集成验收

日期：2026-11-08。Branch：`codex-A/ground-unattended-v2-20261107`。
HEAD：`7063d85dfe09c3f436c30b19ce8c03a241998062`，验收包含当前未提交增量。

## 验收结论与范围

当前结论：**PASS_WITH_LIMITATIONS / REAL_DEVICE_PENDING**（核心隔离验收与真实 Electron 窗口验收）。
Python全量原始运行有4项失败，修复后相关消费者复验通过；另有退出清理目录占用异常，不能宣称全量一次全绿。
真实设备与现场 AP 数据为 `REAL_DEVICE_PENDING`。不提交、不推送、不合并、不发布。

本轮延续 [R3 心跳界面报告](ground-unattended-v2-heartbeat-ui-r3.md)，修复集成暴露的缺陷；
没有重建设备管理、站点表、Supervisor 或通用调度器，没有修改真实数据或连接真实设备。
实际 Ping 仅针对 `127.0.0.0/8` 回环地址，UDP 使用本机隔离监听端口。

证据根相对 Workspace 为 `reports/tests/ground-r3.1-final-20261108/`，下文日志和截图文件名均相对于此目录。
正式开发入口运行根为 `test-data/NetConsole/ground-r31-official-c-20261108/`；
修复前短压根为 `test-data/NetConsole/ground-r31-dtofix-20261108/`；
修复后短压根为 `test-data/NetConsole/ground-r31-indexfix-20261108/`。
这些均为本轮独立 Fixture，不是 Production/Dev Authority 的复制品。

## 功能与数据来源

设备身份来自设备管理车载 MR 的稳定 UUID、列车和 CT/CW 端位，现有 Ground inventory 持久投影保存同步关系。
首次进入、重复同步和进程恢复均重新消费持久事实；设备列表不依赖活动任务、采样记录或前端缓存。
采样、计数、事件和运行快照继续使用 Ground 原有存储，常驻身份与动态状态分离。
正式删除或不再符合资格的 MR 从当前投影移除，已有运行/历史关联保留。

接入区间 AP 来源为 `AcMeshLinkQueryService.list_mrs()` 的 `peer_aps`，接入站点来自 AP 的既有 FIT-AP 归属。
运行中验证变更 FIT-AP 站点为“验收站点C”，同步后出现对应站点，再恢复车站A/B。
没有通过 IP、MR 名称或列车编号推断站点，没有改动 AP Identity 解析器。
隔离库中的四个 AP 走真实 Service/Repository/API 投影；没有把 Fixture 注入真实业务页面或生产数据。

主列表保留“列车 / CT 端 / CW 端 / 整车状态”四列，CT/CW 两列均分空间。
卡片与 MR 抽屉使用“接入区间 AP”“接入站点”，不展示管理 IP；底层管理地址和终端/Ping 关联保留。
首三个 AP 标签和 `+1` 展开可进入完整详情；抽屉显示四个 AP 的 BSSID、RSSI、连接状态、观测时间与所属站点。
无关联时分别显示“暂无关联 AP”“未关联站点”。旧 `resolved_ap_name/station/section` DTO 字段保留兼容。

无采样时保留 21 辆车 / 42 MR；可达/离线统计为 `—`，UNKNOWN 不等于离线。
加载期间不显示 Total 0，错误展示消息与刷新入口；失败退避和在途防重保留。
停止态新增明确 `STOPPED` 展示，并保留最近累计统计；无有效 RTT 用 `—`，不制造 0ms。

## 缺陷根因与修复

| 问题 | 根因与最终处理 | 直接证据 |
| --- | --- | --- |
| 停止后快照与累计值丢失 | 默认只找活动运行；改为活动/最近运行解析，STOPPED 只影响展示，保留库存与统计 | `official-final-stopped-current-code.json` |
| 清空后同日重启旧计数复活 | 同一日 run ID 重用而内存状态未失效；以持久 `data_cleared_at` 重置引擎、聚合、签名、dirty 与 tracker | `clear-restart-regression-v2.log`；`official-clear-restart-fixed.log` |
| 清空后旧丢包事件继续显示或恢复 | 页面/抽屉及 open-loss 恢复均使用逻辑清空边界；`julianday` 比较时间，保留共享历史，不复活清空前事件 | `clear-loss-restore-final-v2.log`；`ground-after-loss-restore-final.log` |
| 多次丢包覆盖上一事件 | 每个 outage 使用独立 UUID，恢复沿用同一 episode key；AP/站点开始快照不随当前关联切换 | `tests/test_ground_unattended_ping_loss_tracker.py` |
| 事件队列积压/并发确认丢更新 | 4096 有界队列，交错目标累积更新合并；按对象身份确认已提交批次，保留写入期间替换的新事件；失败 enqueue 回退 tracker | 同上；队列满保留健康错误 |
| 重配目标丢失连续状态 | 保留有效目标 tracker，裁剪移除目标，仅为缺失目标恢复/创建；停止后的迟到回调不得写事件 | `ground-after-loss-restore-final.log` |
| Quick Ping status/stop HTTP 500 | 统计 DTO 漏 `current_rtt_ms`；补字段而不改变采样语义，兼容旧/UUID open-loss 恢复 | `additional-regression.log`；短压 status/stop |
| SQLite 锁竞争与停止超时 | 每桶连接/事务及 Syslog raw 去重扫描退化；批量原子保存 dirty buckets，提交成功后清 dirty；增加非唯一 raw-line 组合索引 | `targeted-batch.log`；`syslog-index-regression-v3.log` |
| 初次快速切页运行日期为空 | tab 切换取消父级共享 runs 请求且没有补发；保留 status/operation/runs/profile 请求，页面专属请求仍可取消 | `renderer-run-context-fixed.log` |
| CommandReference locale 超时 | 异步 locale 与组件生命周期未正确收口；nextTick 与 afterEach 自动卸载，使用默认超时，不 skip、不减弱断言 | `locale-default-timeout.log`；Renderer 全量 |
| Full/Customer 模板不完整 | Registry 已有 heartbeat_inventory_manage，但两个模板漏登记；仅补既有 Registry 默认值，不改变其它能力策略 | `feature-profiles-failure-repro.log`；`feature-edition-consumers-final.log` |
| 验收脚本误判停止完成 | FINALIZING 尚有资源；等待 active_run_id 清空，检查 Ping/UDP 清零，Electron 退出超时必须 FAIL | `stress-index-fixed.log` |

## 常驻库存逐项验收

以下均由正式 Electron 开发入口、隔离 SQLite 和真实 API 验证；最新清空恢复边界另由最终 Ground 回归覆盖。

| 场景 | 结果 | 证据/观测 |
| --- | --- | --- |
| 1 首次进入 | PASS | `official-not-started.json`：21 车/42 MR，UNKNOWN42，lost0 |
| 2 不启动监测 | PASS | `electron-not-started-{1920,2048,1672}.png`，库存可见且无虚构失败 |
| 3 启动且不重复创建 | PASS | `official-running.json`，UUID 集合稳定，CT/CW 正确 |
| 4 暂停 | PASS（库存）；暂停 Ping 非现有语义 | `official-paused.json`，42 MR 保留；心跳继续，见下文限制 |
| 5 恢复 | PASS | `official-resumed.json`，身份与统计延续 |
| 6 停止 | PASS | `official-final-stopped-current-code.json`：21/42、84 成功保留；Ping0、UDP关 |
| 7 清空动态数据 | PASS | `official-data-cleared.json` 库存42；清空后重启 0→70→84，停止后3秒84不变 |
| 8 切换运行日期 | PASS | `electron-historical-date-inventory-2048.png`；无样本历史运行仍显示42设备 |
| 9 切换历史归档再返回 | PASS | `official-inventory-association-final.json`：archive_return_cards42 |
| 10 Electron 关闭重启 | PASS | `official-electron-restarted-verified.json`：42 UUID不变，1134成功保留 |
| 11 Backend 正常/异常重启 | PASS | 正常3948→3990，异常恢复4267；42 UUID稳定，integrity ok，无旧树残留 |
| 12 新增 MR | PASS | 新列车22 CT加入：22车/43MR；不覆盖84次已有采样 |
| 13 停用/删除 MR | PASS | 资格移除42、恢复43、正式删除42；历史身份保留 |
| 14 重复同步 | PASS | 无重复 UUID/设备；AP/站点更新同步，恢复原 Fixture |

运行中页面刷新、三次快速启停、同 IP 去重、主备地址及单端独立检测由
`official-page-reloaded.json`、`official-rapid-*-{running,stopped}.json` 和最终 Ground 套件覆盖。
正式入口新增/删除/资格/AP归属的最终记录为 `official-inventory-final-v4.log`。
此前 v1/v2/v3 失败记录保留，分别暴露日期加载缺陷或验收脚本假设问题，不以最新结果覆盖。

## 生命周期边界

Canonical [Ground 规则](../rail-transit/ground-unattended/README.md) 明确“暂停调度不停止心跳和 Syslog”。
本轮实际验证了这个行为：暂停保留库存与历史，深采调度暂停，Heartbeat/AC/Syslog 继续。
因此“暂停后 Ping 零采样”没有通过，不能把“已暂停”显示解释为 Ping worker 停止。
没有为满足这一不同预期而重写已完成的调度/并发策略。

Backend 重启遵循现有冻结活动运行恢复策略；不强制把所有运行自动变成停止，也不另建一套任务恢复政策。
停止动作等待 operation 完成与 active_run_id 清空后才断言资源释放；停止后采样计数不再增长。
正常/异常重启均检查库存、UUID、计数、Backend health 与旧进程树。
正式入口最终 `official-final-owned-after-close.json=[]`，管理的 Electron/Backend 树正常退出。

## 真实 Electron 与截图

正式入口：在 `apps/desktop_electron` 运行 `pnpm dev:codex --isolated-test-data <本轮绝对隔离根>`。
确认 Backend Online、Renderer warmup、真实 Electron 主窗口及 PID；通过现有 main inspector 控制窗口和导航，
没有替换生产 bridge、伪造 HTTP API 或用静态 HTML 冒充应用。
截图使用原生窗口 PrintWindow，记录实际窗口尺寸；这不同于 R3 的 Chromium Renderer 视觉截图。

| 证据 | 文件 |
| --- | --- |
| 未启动 / CT-CW 主界面 | `electron-not-started-1920.png`、`electron-not-started-2048.png`、`electron-not-started-1672.png` |
| 正常监测 | `electron-running-1920.png` |
| 暂停调度 | `electron-paused-2048.png` |
| 停止后主界面，最终版本 | `electron-final-stopped-main-1920.png`、`electron-final-stopped-main-2048.png`、`electron-final-stopped-main-1672.png` |
| 多 AP / 站点 / MR 完整抽屉 | `electron-multi-ap-stations-final-1920.png` |
| 清空数据 | `electron-data-cleared-2048.png` |
| Electron 重启 | `electron-electron-restarted-stopped-1672.png` |
| Backend 正常重启 | `electron-backend-restarted-v2-1920.png` |
| Backend 异常退出恢复 | `electron-backend-crash-recovered-v2-1920.png` |
| 历史运行库存常驻 | `electron-historical-date-inventory-2048.png` |

实际检查 1920×1080、2048×1091、1672×941：列布局不重复 CT/CW，卡片和整车操作可用，内容通过既有滚动容器访问。
本轮没有增加原生 DPI 专项。截图/UI 验收完成于最后一项 backend open-loss 清空边界修复之前；
该修复不改变 UI，最终 Ground 回归覆盖其持久恢复语义。模板补漏由独立 Feature/edition 回归覆盖，未重新制作安装包。

## 稳定性：首轮失败和修复后结果

旧短压结论 **FAIL**：59840 条 UDP 中仅24362条解析完成，parser queue达到20000，
DB batch约11.7秒，出现3次 database-is-locked 堆栈；停止/归档未完成，Electron ACK后30秒超时并清理自有进程。
旧脚本 summary 的 COMPLETED 不能代表通过。证据保存在旧短压根与 `dtofix-stress.log`。

增加 raw-line 索引后重新运行 **600.00063秒，功能验收 PASS_WITH_LIMITATIONS**。
压力运行使用 `scripts/dev/ground_v2_system_validation.py` 的自有进程 harness，
其运行证据与上述正式 `dev:codex` 截图/生命周期证据分别记录。

| 观测项 | 修复后结果 |
| --- | --- |
| 规模 | 60车/120MR，200心跳地址（80双IP、40单IP）；8 Quick Ping请求，现有容量下4运行+4排队 |
| fping | 11个进程稳定：7心跳分片+4 Quick Ping；Quick Ping成功采样12004 |
| UDP | sent=received=written=parsed=db_saved=59840；dropped0 |
| 队列 | parser峰值10/20000；database pending峰值60；memory ingress/compression均0 |
| DB batch | 4.016–45.298ms，平均15.720ms；新日志未检出database-is-locked |
| Backend RSS | 225.461–251.281MiB，均值239.148MiB |
| Electron进程树 RSS | 593.234–1006.492MiB，结束873.875MiB；不足以推断长期无泄漏 |
| CPU | 占一个逻辑核百分比：Backend均48.786%/峰81.174%；Electron均9.814%/峰103.615%；fping均8.276% |
| 磁盘 | 3661094→585105504字节，含Raw、索引、WAL；不把录制增长解释成无界队列 |
| 完整性 | 7个SQLite integrity_check=ok；128个gzip CRC及解压内容SHA256通过 |
| 停止释放 | Ping目标/进程0，UDPfalse，队列0，active0；Electron exit0，owned_after_cleanup=[] |

证据：`stress-index-fixed.log`、`stress-index-fixed-analysis.json`，以及新短压根的 `summary.json`、`metrics.ndjson` 和 runtime日志。
通用 scheduler 的 active/worker 计数全程0，既有心跳/Quick Ping/Syslog使用自身域资源；
这次运行不能证明所有真实 worker 已迁入新 scheduler，只证明没有破坏既有运行和资源收口。

日志限制：新短压在本地01:40:58记录一次 asyncio Proactor callback `ConnectionResetError [WinError10054]`，
发生于页面导航附近，随后仍完整录入59840条、正常停止并于1538ms退出。
另有空payload的 `ELECTRON_RENDERER_CONSOLE_ERROR` 与启动/关闭时 `TRAY_SITE_CONTEXT_REFRESH_FAILED`。
不把 harness `errors=[]`解释为日志零异常，也不通过全局吞异常掩盖；作为非阻塞运行限制保留。
没有进行24小时长稳；每次连续测试运行均受1小时上限约束。

## 回归门禁

| 门禁 | 结果与证据 |
| --- | --- |
| 最终 Ground（含 API、heartbeat、monitoring、库存/恢复） | **398 passed, 1 skipped, 5128 deselected / 210.10s**；`ground-after-loss-restore-final.log` |
| 清空旧 open-loss 恢复专项 | 29 passed / 27.71s；`clear-loss-restore-final-v2.log`，包含于最终 Ground，不重复累加 |
| Renderer 全量 | **198 files / 1392 passed / 54.54s**；`renderer-final-after-context.log` |
| Renderer 类型/构建 | vue-tsc -b与build PASS；`renderer-build-after-context.log`；保留大chunk提示 |
| Electron 全量 | **38 files / 306 passed / 20.11s**；`electron-full.log` |
| Electron 类型/构建 | PASS；`electron-final-build.log` |
| 主线关键契约 smoke | 12 passed；`main-contract-final.log` |
| Syslog旧库与新增索引 | 8 passed；`syslog-index-regression-v3.log`；旧重复行不删除 |
| 架构检查 | run_all 12/12 PASS；`architecture-after-registration.log`；原两项失败节点再跑2 passed / 56.72s |
| Ruff | 全仓PASS；`ruff-after-loss-restore.log` |
| py_compile | 18个dirty Python文件PASS；`pycompile-final.json` |
| Python全量原始运行 | **FAIL：4 failed, 5519 passed, 2 skipped / 1677.89s（27分57秒）**；`python-full-final.log`。4项为架构guard两项、Full/Customer完整性两项，均在运行期间修复后专项复验通过；没有重新完整运行全量 |
| Feature/edition消费者 | **88 passed / 9.65s**；`feature-edition-consumers-final.log`，覆盖两项原始模板失败 |
| 文档/链接/路径 | **22 passed / 0.65s**；`final-guards.log`；此前 `docs-final.log` 同样22 passed |
| workspace、根目录、diff | PASS；`final-guards.log`，仅保留LF/CRLF提示；DevStatus diff检查也通过 |

全量运行后的 `pytest_unconfigure` 清理隔离测试根时出现 `PermissionError [WinError32]`，
路径为 `pytest-fdf40f576bf044b19a16d56cacc77a60/pytest/test_production_parent_and_tes0/workspace/NetConsole`。
未改变共享清理器、放宽错误策略或删除占用未知目录；单独重跑对应
`tests/test_diagnostic_data_root_guard.py::test_production_parent_and_test_base_are_blocked` 为
**1 passed / 0.40s、exit0**（`python-cleanup-node-recheck.log`）。占用者/首次清理失败根因未确认，保留为测试基础设施限制。
该专项通过不抹去全量退出异常，也不证明完整最终快照全量通过。

所有失败、无效测试路径及修复中重跑日志保留。曾误用不存在的 `test_ground_unattended_mr_monitoring.py`，
实际为 `test_ground_unattended_monitoring.py`，最终 Ground selection 已覆盖。
500k规模用例因未设置 `NETCONSOLE_RUN_SCALE_TESTS=1` 跳过；没有谎称执行该规模。
不累加重叠专项与全量测试数量。

## 风险、消费者与兼容性审计

实际最高风险 **L4**：涉及业务SQLite additive index及Full/Customer模板；
最初路径工具仅报L2，不作为降级依据；模板审计工具明确命中L4。

- Writers：FleetPing汇总批量写、Heartbeat/QuickPing共享丢包事件、Syslog live/replay入库、设备管理→库存同步。
- Readers：heartbeat/API与drawer、timeline/history/raw/archive、恢复路径、FeatureGate/feature snapshot和edition准备。
- Caches：Fleet dirty buckets提交后清理；tracker仅为有效身份保留并以清空边界失效；Renderer共享请求与页面请求分别收口。
- 展示与导出：停止/无样本/过期不等于离线；没有修改已有history export文件协议、AP Identity resolver、数据根或通用API client。
- 旧格式：现有loss列迁移保留，legacy/UUID事件恢复兼容；新增非唯一 `(site_id, raw_file_id, raw_line_number)` 索引幂等，旧重复Raw行不清除；无全表重写。
- Feature模板：两份仅增加已注册能力的默认flags，其他键/策略不变；包内读取策略和Registry算法不变。
- 并行工作：仅一个Git worktree；保留全部原dirty，未切分支。DevStatus已有原版R3与Next内容，仅追加本轮条目。
- 最终合并：本轮无merge/main commit，合并后仍必须重跑登记consumer suites；分支验收不替代main结果。

## 原有工作区保护与交接

开始时36个dirty文件：19 tracked、17 untracked。初始差异保存在 `initial.patch`，
初始SHA256为 `initial-dirty-hashes-corrected.json`。最终逐文件映射为 `preservation-final.json`；
tracked初始增量与本轮最终组合差异为 `r31-only-tracked-review.diff`。
相同哈希文件保持不变；被修复文件叠加兼容修复，不能宣称全部哈希不变。

原 `docs/development/R3_ARCHITECTURE_AUDIT.md` 因docs guard规则移至
`docs/archive/R3_ARCHITECTURE_AUDIT.md`，原内容、字节长度和SHA256一致，引用检索无活动引用。
证据 `r3-audit-relocation.json`；原文未重写。
用户批准旧任务目录核验后移入 `temp/analysis/ground-r3.1-capture-20261107`，26个文件逐个SHA256/长度一致，
保留 `temp/analysis/ground-r3.1-capture-move-20261108.json` 校验记录，没有删除或覆盖。

最终dirty数量与完整清单由 `final-git-status.txt`、`final-diff-stat.txt`、`final-tracked.patch` 和 `preservation-final.json` 记录。
R3原报告保留，只追加R3.1链接与新结果。DevStatus的 current-status、handoff、tasks/doing 只追加，未提交。
测试数据库和失败证据均保留便于复验；未清理用途未知文件或复制真实Site。

最终 **47个dirty文件：29 tracked、18 untracked**。初始36项中21项哈希不变，15项叠加修复，0项缺失；
其中原架构审计按上述路径映射，`task_scheduler.py` 哈希未变。
R3报告及DevStatus追加前字节前缀校验均通过，证据 `append-only-docs-devstatus-proof.json`。

Tracked修改清单（包含原有R3增量，不表示全部由R3.1新建）：

```text
apps/desktop_renderer/src/api/groundUnattended.ts
apps/desktop_renderer/src/components/ground-unattended/MrMonitoringDrawer.vue
apps/desktop_renderer/src/types/groundUnattended.ts
apps/desktop_renderer/src/views/command-reference/CommandReferenceView.test.ts
apps/desktop_renderer/src/views/rail-transit/ArchivePage.vue
apps/desktop_renderer/src/views/rail-transit/GroundUnattendedView.behavior.test.ts
apps/desktop_renderer/src/views/rail-transit/HeartbeatPage.test.ts
apps/desktop_renderer/src/views/rail-transit/HeartbeatPage.vue
apps/desktop_renderer/src/views/rail-transit/QuickPingPage.vue
apps/desktop_renderer/src/views/rail-transit/useGroundUnattended.ts
apps/desktop_renderer/tests/visual/e2e/ground-unattended.visual.spec.ts
apps/desktop_renderer/tests/visual/e2e/heartbeat-monitor.visual.spec.ts
config/architecture/direct_sql_access.yaml
config/profiles/features/customer.json
config/profiles/features/full.json
scripts/dev/ground_v2_system_validation.py
src/netconsole/backend/api/ground_unattended_router.py
src/netconsole/models/api/ground_unattended.py
src/netconsole/repositories/ground_unattended_repository.py
src/netconsole/services/ground_unattended/application_service.py
src/netconsole/services/ground_unattended/fleet_ping.py
src/netconsole/services/ground_unattended/quick_ping.py
src/netconsole/services/ground_unattended/supervisor.py
tests/test_feature_registry_groups.py
tests/test_ground_unattended_api.py
tests/test_ground_unattended_fleet_ping_retention.py
tests/test_ground_unattended_heartbeat_inventory.py
tests/test_ground_unattended_heartbeat_state.py
tests/test_ground_unattended_syslog_v2_stress.py
```

Untracked清单（原有文件继续保留；含本轮新增报告/测试）：

```text
docs/archive/R3_ARCHITECTURE_AUDIT.md
docs/archive/ground-unattended-v2-heartbeat-ui-r3.md
docs/archive/ground-unattended-v2-r3.1-final-integration-audit.md
docs/development/R3_FAILURE_RECOVERY_REPORT.md
docs/development/R3_FINAL_ACCEPTANCE.md
docs/development/R3_HEARTBEAT_ISOLATION_REPORT.md
docs/development/R3_NEXT_TASK_BACKLOG.md
docs/development/R3_PROCESS_BOUNDARY_DESIGN.md
docs/development/R3_QUICK_PING_ISOLATION_REPORT.md
docs/development/R3_RESOURCE_MONITORING_REPORT.md
docs/development/R3_STRESS_TEST_REPORT.md
docs/development/R3_SYSLOG_PIPELINE_REPORT.md
docs/development/R3_TASK_SCHEDULER_REPORT.md
docs/development/R3_WORKER_LIFECYCLE_REPORT.md
scripts/dev/ground_r3_short_stress.py
src/netconsole/services/ground_unattended/ping_loss.py
src/netconsole/services/ground_unattended/task_scheduler.py
tests/test_ground_unattended_ping_loss_tracker.py
```

## 剩余问题与下一步

1. 真实MR/AC、现场AP与站点关系、真实网络丢包互操作未执行：`REAL_DEVICE_PENDING`。
2. 暂停仍为“暂停深采调度”，心跳/Syslog继续；若要求暂停Ping，需要后续明确变更产品语义。
3. 10分钟覆盖不能证明长期内存稳定；Proactor连接重置与空payload日志条目保留为运行限制。
4. 通用scheduler并未接管全部既有worker；不声称完成Windows Service/Job Object架构迁移。
5. 安装包、跨机/原生DPI、500k规模、main合并后门禁未执行；本轮未新增这些验收要求。
6. 全量Python原始4项失败已有修复复验；未重新运行完整全量，且一次退出目录占用根因未确认。
7. 最终停在当前dirty分支，等待下一步指令；无产品commit/push，无DevStatus commit/push。
