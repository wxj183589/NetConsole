# 地面无人值守 V2 交付记录（2026-11-07）

状态：**PASS_WITH_LIMITATIONS**（核心实现完整 FULL Gate 为 PASS，随后收尾变更单独复验；自动化与首轮失败修复见第 9 节，Electron smoke 见第 10 节）。本记录针对原版 NetConsole 未提交工作树，不是发布、安装包或现场验收证明。

## 1. 修改文件清单

完整清单见本文末尾，由最终 Git tracked diff 与 untracked 合并生成。主要生产入口：

- Python：`services/ground_unattended/` 的 Supervisor、Fleet、Heartbeat、Quick、Syslog、History Query/Export；既有 Repository、DTO、Router、FastAPI lifespan。
- Vue：`GroundUnattendedView.vue` 父壳、`useGroundUnattended.ts` 公共上下文及十个独立页面；快速 Ping 图表、API/types、Feature/i18n/Navigation/Route。
- 必要共享消费者：基础资料备用策略、fping 可选全局间隔、AC 设备/接收时间、Export Artifact 登记及 Storage Registry。
- Electron Main/Preload 沿用现有实现，未新增连接或保存系统；未增加依赖、未改 Go 或打包发布链。

## 2. 后端架构调整

继续由唯一 GroundUnattendedSupervisor 管理运行窗口、停止、重启与子系统。目标从基础资料/设备库存建立，心跳解除 AC、Mesh-Link、凭据和位置资格门槛。Fleet 复用原 fping runner；AC 慢命令和深采失败不能阻塞心跳。

新增 HeartbeatStateEngine、TrainConnectivityAggregator、HeartbeatEventService、QuickPingService 及历史查询/导出服务。Quick Repository 能力放入既有 GroundUnattendedRepository，避免创建第二套 SQLite。Syslog Receiver、Raw Writer、Parser、压缩分别执行；队列有界，积压进入受管 spool，恢复为 at-least-once。

共享契约风险 **L4**：Feature Registry、Export Framework、历史状态持久化、SSH/设备连接消费者。Consumer Audit 涵盖写入、读取、当前快照、旧 Raw Query、历史/导出、动态图及 Frontend API；没有恢复 Legacy HistoryStore。本任务各代理在同一工作树分域修改后冻结，最终 Gate 验证组合工作树；本任务未 merge，不能宣称合并提交已验收。

## 3. 十页实现

| 页面 | 实现与证据 |
| --- | --- |
| 运行概览 | 运行、MR/列车状态、健康与最近异常，真实 API |
| 心跳检测 | MR/整车状态、双 IP、RTT/丢包、时间范围、详情抽屉与 Quick 入口 |
| AC-Mesh-Link | 复用查询/刷新，device_time、received_at 与 freshness |
| 快速 Ping | 登记设备/地址选择、参数、启动/停止、实时曲线/统计、任务历史 |
| Syslog 日志 | 服务端分页/筛选、原始与解析详情、UDP 状态 |
| 深度采集 | 既有会话、队列、覆盖与停止生命周期 |
| 时间轴 | 设备/地面时间、列车/端位/MR/类型/时间筛选与详情 |
| 系统健康 | 既有 /health 聚合五类健康，与设备状态分离 |
| 历史归档 | 九类索引分页/筛选、全量 CSV、原始查询入口、READY ZIP 校验 |
| 设置 | 既有 Profile、运行窗口、库存与存储策略 |

十 Tab 与两个新动作登记 Full/Customer Feature，独立“列车在线情况”导航移除、旧路由重定向。父壳不包含十页模板；异步请求使用现有取消/代次/在途保护。表格与日志复用 NcDataTable/NcLogWorkspace。十页剩余设置、计数、单位、日期及状态提示已补入现有 i18n；挂载后中英双向切换有回归测试。历史工作台可切换服务端时间正/倒序，分页与全量 CSV 保持同一排序。

## 4. 数据库变更

既有 Ground index.sqlite 新增四表及索引：

- ground_unattended_heartbeat_states：MR/列车当前状态、最后成功与累计统计，重启恢复依据；不是逐秒历史。
- ground_unattended_quick_ping_runs：独立任务及登记分段路径。
- ground_unattended_quick_ping_stats：整体及每 IP 统计。
- ground_unattended_quick_ping_events：生命周期/问题事件，不随普通样本或汇总到期删除。

AC 快照补设备时间/接收时间/新鲜度字段；基础资料复用 site_meta 的 mr_backup_monitoring_strategies，以 MR UUID 为键，并复用既有保存补偿，无设备表迁移。Storage Registry 登记新表及 Quick raw 根。没有逐秒样本全量写 SQLite，没有旧无人值守数据迁移或自动删除旧目录。

## 5. API 变更

在现有 Ground Router 下增加：GET /heartbeat；POST/GET /quick-ping；GET /quick-ping/{run_id}；GET /quick-ping/{run_id}/samples；POST /quick-ping/{run_id}/stop；GET /history。继续复用 /status、/profile、/health、/timeline、/ping-series、/syslog-records、深采及归档入口。历史查询/导出支持 sort_order=asc|desc 白名单，默认 desc；排序发生在 SQL 分页前，跨页使用稳定身份键，非法参数先拒绝再读库。

历史 CSV 通过固定 ground history 动作、web_export_ground_history_csv、独立 Export Process 与 Artifact 下载；保存取消不创建任务，Export 在同一读 snapshot 流式导出全部筛选索引，含 BOM 和公式转义。索引 CSV 不等于所有原始 UDP 报文导出。

## 6. 心跳状态机

默认 1000ms / 4000ms / 64 Bytes。有效目标来自基础资料的 Site、Train、MR UUID、CT/CW、主备 IP。备用策略 MONITOR 自动参与；FAILOVER_ONLY/DISABLED 不纳入自动心跳，人工 Quick 可明确选择登记地址。

每 IP 独立统计；MR 任一有效地址成功即有在线证据。偶发丢包为 LOSS/OFFLINE_PENDING，全部无响应到 10 秒进入 OFFLINE，只发一次离线事件并继续探测；恢复连续成功两次才 ONLINE。双 MR 的不可达时间交集到 120 秒才 TRAIN_OFFLINE，一端成功立即重置；单 MR 使用单端规则。

用户已确认状态名采用可达端含义：CT_ONLY=仅 CT 可达、CW_ONLY=仅 CW 可达，界面明确显示可达端。该规则取代需求示例表中相反的枚举写法。

fping 退出、流中断、Backend 重启或持久化错误归入引擎健康，缺少探测证据为 UNKNOWN/DEGRADED，不转换为全体设备离线。持久状态保留最后成功和计数；重启空窗不算连续失败。

已确认整车离线后遇到采样中断，UNKNOWN/重新计时不生成整车恢复事件；同一离线告警保持待恢复，直到新可达证据确认一端恢复。空窗后再次到达整车离线阈值也不重复发出同一离线告警。

## 7. 快速 Ping 运行与存储

默认 200ms / 1000ms / 64 Bytes、无限。支持有限/自定义时长、手停；每次独立 run，可与心跳并行且不修改心跳状态。每局点最多 4 活动 run，每 run 最多 32 地址，按全局发包间隔约束在途请求；最近样本缓存 256，任务缓存有界。

逐 MR NDJSON 使用 PathResolver 业务根内 quick_ping/<日期>/trains/<train>/<role>/<MR>/quick_ping/<run>/；manifest 位于同根日期 runs。10MiB 或小时先到者分段，64 容量后台压缩队列，gzip SHA/大小回读、压缩 SHA sidecar 和原子发布后才删除原段。查询兼容 raw/gzip、逻辑字节游标稳定；损坏失败关闭。

活动多 MR 分页为每个待读分段保留续读位置，最多 32 个检查点，轮转访问其他 MR；关闭分段消费到 EOF 即移除检查点。修复了旧游标越过当前 EOF 后遗漏追加样本的问题；每条样本只登记当前新增分段，不再遍历历史路径。

启动、每小时及结束按 live Profile 执行原始 30 天/汇总 180 天默认保留策略；只处理精确 site、终态、结束时间和登记路径，校验身份/边界，保护 active/未知文件；重要事件保留。清理/压缩失败记录健康错误并保留相关证据。

## 8. Syslog 接收与解析

保持现有设备连接/凭据及固定命令：system-view、info-center enable、info-center loghost <server> port <udp-port>、return。UDP / Informational，不新增 Debugging、Trap、TCP、save、旧配置清理或未验证 CLI。未连接真实设备执行配置。

原始 envelope 先落盘再解析，未知 WMESH/IFNET/CFGMAN/WLAN/SYSTEM/UNKNOWN 原文均保留，解析失败独立记录。MR UUID/ID 参与目录及文件键，安全段含摘要防大小写/截断碰撞；未知来源按 IP 隔离，歧义不猜测 MR。

10MiB/小时分段，后台 gzip 校验登记，原始 NDJSON 保留；gzip_path 不替代 READY ZIP compressed_path。ACTIVE 和 READY ZIP 的 /ping-series、/syslog-records 与历史 MR 筛选实测可读。压缩后记录级改写拒绝，避免 raw/gzip 不一致。停止超时保留 owned run/writer/compressor，重试完成后清空；较早小时流跨 MR 及时关闭。

## 9. 自动化测试

核心实现冻结快照的统一 FULL Gate：**PASS**，进程退出码 0。执行时间为 2026-11-07 03:31:33–04:00:46（Asia/Shanghai），风险 L4、10 个必需套件全部通过，无 failed 或 not_run。证据为 `.local-reports/ground-v2-final-full.log`、`.local-reports/local-gate.json` 和 `.local-reports/local-gate.md`。

| 最终套件 | 实际结果 |
| --- | --- |
| Repository / Workspace layout | PASS / PASS |
| Renderer full | 191 files / 1363 tests passed / 111.13s；vue-tsc、Vite build 通过 |
| Python full | 5448 passed、2 skipped、34 warnings / 1555.00s |
| Electron contract | 38 files / 306 tests passed / 13.22s；typecheck、build 通过 |
| Architecture guards | 12/12 passed |
| Main contract smoke | 12 passed / 12.38s |
| Ruff full | All checks passed |
| Docs path guards | 22 passed / 0.78s |
| Git diff check | PASS |

使用既有 `scripts.quality.local_gate.run_gate(requested_mode="full", ...)` 完整执行所有套件；临时 wrapper 仅为 Renderer Vitest 命令增加 `--maxWorkers=2`，没有跳过测试或修改超时/仓库测试配置。Gate 为本轮独占 TEST 根，结束后已清理。该 FULL Gate 期间 110 个变更文件内容哈希保持一致；随后追加的国际化与历史排序收尾不在此快照中，验证结果另列如下。

首轮 FULL 为 FAIL：Python 5431 passed、4 failed、2 skipped / 1480.13s，其中三项为 direct SQL/动态图架构守卫、一项为 Quick 分段读取；Renderer 的 CommandReference locale 用例触发既有 5 秒超时。已修复架构分类/图表选项与 Quick 分页及分段边界；限 Renderer 并发后全量通过，超时值保持原样。收尾又发现并修复整车 UNKNOWN 误发恢复事件，随后重新执行上述完整最终 FULL。首轮日志 `.local-reports/ground-v2-full.log` 保留用于追踪，不能作为最终通过证据。

定向执行结果（各组存在重叠，不相加为总数）：

- Quick/Repository/History/API：72 passed / 40.88s；gzip、游标、篡改、live retention、active/未知保护、失败留证。
- Raw/Archive/History/Lifecycle/Foundation/UDP：71 passed / 37.27s。
- Fleet/Usability/Retention/AC/QueryScale/History：60 passed、1 skipped / 63.84s。
- 最新小时分段、20k压力、真实10MiB、MR隔离、consumer：8 passed / 21.95s。
- Ground mounted behavior：34/34；基础资料三策略保存→GET→sync→targets：28/28；Feature/edition：58/58。
- Fleet 全天汇总缓存与写入失败重试：2 passed / 1.01s；定向 Ruff、vue-tsc 与 Python compile 均执行通过。
- 历史导出：2 passed，601行全量、取消保护、真实 Export Process 下载 SHA 一致。
- 低磁盘 Supervisor：1 passed / 1.28s，critical 时停止/收尾深采、调度 paused=True，心跳继续；空间恢复后 paused=False。
- 架构 pytest 复验：23 passed / 59.17s（架构 guards 与 Storage Registry language guards）；先前 direct SQL 分类、图表稳定选项、UI 展示逻辑分类及存储词条扫描问题已修复。
- 完整 Renderer：`pnpm test --maxWorkers=2`，191 files / 1362 tests passed / 112.86s；随后 `pnpm build`（vue-tsc + Vite）通过。首轮默认并发的一项 CommandReferenceView locale 测试 5 秒超时，限并发重跑全套通过，未修改超时或测试配置。
- 最新前端文案、十页顺序及目标范围契约：5 files / 63 tests passed / 22.98s，随后 build 通过；此为完整 Renderer 验证后的受影响复验。
- 心跳与 AC 恢复缓存最终组合：ac_resident、eligibility、api、fleet_ping 共 99 passed / 102.23s。缓存只保留真实 AC 辅助信息，过期后仍合并基础资料目标，避免虚假宽限期事件；包含 R01 与恢复/过期六例。
- Syslog metadata 停止边界：8 passed、13 deselected；真实 UDP 与 OPEN/CLOSED metadata barrier 验证首停失败保留 owner、释放后重试成功。Raw V2 consumer 另 1 passed / 4.18s；两组后端修改的 Ruff 与定向 diff 检查通过。
- 最终 Quick 分页复验：Quick、Quick Repository、Ground API、raw V2 consumers 共 69 passed / 47.71s。并发 Barrier 先使旧实现确定遗漏 A2，再验证 limit=1/1000、多 MR 空闲续读、结束收口及 40 轮/80 段轮转无遗漏或重复；检查点≤32、游标≤8192字节。Ruff、py_compile、diff 检查通过，未提高原测试等待超时。
- 最终整车采样中断边界：心跳状态机 15 passed / 3.41s；离线→UNKNOWN→重新计时不误报恢复、不重复离线，出现可达证据后仅一次恢复。Ruff 与 diff 检查通过；发现该边界后中止尚未完成的 FULL，并重新启动完整门禁。

FULL 后的最终收尾复验（国际化及历史排序，未重新执行整个 Python FULL）：

- 完整 Renderer：193 files / 1367 tests passed / 107.95s，exit 0；日志 `.local-reports/ground-v2-locale-renderer-final.log`。包括挂载后 zh→en→zh 的 Settings/Syslog/Health 与 Quick 统计测试。
- Renderer `pnpm build`：vue-tsc 和 Vite 均通过，3403 modules / 2.36s；保留既有大 chunk 提示。
- History Query / History Export / Ground API：49 passed / 48.15s；验证 asc/desc 跨页全局次序、时区、稳定同时间排序、导出同序、非法 sort 拒绝及真实 Export Process/Artifact SHA。
- 架构守卫：23 passed / 71.49s；修改范围 Ruff 通过；新增词条存在性与重复 key 检查通过。
- 文档守卫：22 passed / 0.72s；Git diff check 通过。
- 收尾首轮发现 Syslog 测试 context 缺 mock、旧静态测试要求硬编码中文及 Artifact 尚未完成登记时的读取竞态。分别补齐 mock、将静态断言转为 i18n key、在原有 30 秒期限内等候 Artifact SHA；未增加等待上限。前一轮 Renderer 1366 passed/1 failed 的日志保留，最终全套重跑通过。公共词典合并时缺少分隔逗号已修正，最终 typecheck/build 与全套测试覆盖。

所有自动化使用独立 RuntimeMode.TEST / Fixture/Mock；没有读写/复制 Production 或真实开发业务根。

## 10. E2E 与视觉

浏览器 Playwright 六项通过（40.7s）：真实 Vue 组件/API client、HTTP Mock；1920×1080、2560×1440、125%等效浏览器视口，验证页面布局、筛选分页及 Quick 交互。证据位于忽略的 .local/tests/renderer-visual/ground-unattended.visual-*；未将截图作为源码提交。已查看 Syslog/Quick 125%和 Timeline 2K 截图，无外层横溢或分页遮挡。

Electron `pnpm smoke:dev` 退出码 0：隔离 TEST 根、Backend 与 Vite ready/warmup、TraySync 局点一致；正常退出依次记录 SHUTDOWN_STARTED、DOWNLOADS_STOPPED、BACKEND_STOPPED、EXIT_REQUESTED、EXIT_RETURNED。日志位于 `.local-reports/ground-v2-electron-smoke.log`。

这不等于原生 Windows DPI、完整 Electron 人工交互或真实设备端到端验收；浏览器视觉使用 HTTP Mock。

## 11. 压力与强制验收矩阵

下表测试前缀为 tests/test_ground_unattended_，UDP spool 另列。PASS 只表示所列自动化范围。

| ID | 状态 | 实际证据/边界 |
| --- | --- | --- |
| H01/H02 | PASS | ac_resident::test_heartbeat_without_ac_or_credentials_persists_both_ip_stats |
| H03/H07 | PASS | heartbeat_state::test_occasional_loss_does_not_raise_offline_and_single_ip_is_monitored |
| H04 | PASS | heartbeat_state::test_dual_ip_any_success_keeps_mr_online_and_tracks_each_ip |
| H05/H06/H12 | PASS | heartbeat_state::test_mr_offline_after_ten_seconds_and_recovers_after_two_successes；9/10秒及两成功边界 |
| H08 | PASS | heartbeat_state::test_ct_offline_cw_online_keeps_train_partially_online |
| H09/H10/H11 | PASS | heartbeat_state::test_train_offline_uses_intersection_and_resets_when_one_side_recovers；119/120秒交集 |
| H13 | PASS | fleet_ping::test_fping_shard_failure_reports_health_without_serial_fallback；heartbeat_state::test_sampling_engine_gap_becomes_unknown_without_device_offline_event |
| H14 | PASS | ac_resident::test_backend_restart_restores_counters_but_requires_live_recovery_evidence |
| Q01/Q02 | PASS | quick_ping defaults_and_input_validation / adjustable_parameters_reach_runner |
| Q03 | PASS_WITH_LIMITATIONS | 无限任务手停、活跃持续分段/压缩测试；未墙钟24h |
| Q04 | PASS | quick_ping::test_quick_ping_stop_or_failure_does_not_stop_concurrent_heartbeat |
| Q05/Q06 | PASS | quick_ping manual_stop_closes_stream_and_records_cancelled / collects_stats_and_writes_mr_ndjson |
| S01/S02 | PASS | 全模块及UNKNOWN原文落盘、解析失败保raw的UDP/Foundation测试 |
| S03 | PASS_WITH_LIMITATIONS | 20,000 Mock ingress+有界100队列/Parser阻塞spool，逐条比对raw；另本机UDP 1000/5000，不能证明网络零丢包 |
| S04/S05 | PASS | syslog_v2_stress::test_real_10mib_rotation_and_gzip_roundtrip（Ping/Syslog各参数）；consumer真实HTTP active与READY ZIP |
| A01 | PASS | ac_resident::test_slow_ac_query_does_not_block_fleet_heartbeat；实际阻塞30秒的Fake AC命令 |
| A02 | PASS | ac_resident::test_restart_marks_persisted_main_link_stale_after_existing_grace |
| D01 | PASS | ac_resident::test_repeated_deep_scheduler_failure_keeps_heartbeat_running_and_recovers |
| R01 | PASS | ENOSPC raw write失败计数/报警/恢复、spool磁盘阈值与恢复；ac_resident::test_critical_disk_space_pauses_deep_collection_but_keeps_heartbeat_running 以模拟1GiB/恢复8GiB确认停止深采、paused调度、MR在线且心跳继续；未填满真实磁盘 |
| R02 | PASS_WITH_LIMITATIONS | fleet_ping::test_400_ip_mock_fleet_has_bounded_shards_and_stops：400目标、20个Mock runner分片；非400真实设备或真实fping进程 |
| R03 | PASS_WITH_LIMITATIONS | heartbeat_state虚拟86400秒、172800样本，warmup后tracemalloc增量<1MiB、事件有界；Fleet跨1440分钟/AP窗口缓存≤10、迟到补累计、写失败重试；非全栈墙钟24h soak |

## 12. 未完成及原因

- 真实 H3C 配置/SSH/Telnet、生产/开发真实数据运行：本任务禁止，未执行。
- 完整后台墙钟24h、200–400真实 fping 进程/网络、真实多MR UDP、托盘长时：未执行；虚拟时间/Mock资源证据不能替代。
- 原生保存窗口、用户选择最终文件落盘、Windows原生125%DPI与正式安装包：需人工/制品环境，未执行；自动取消、Export Process/Artifact与浏览器视觉分别已有证据。
- 设备日志、后端来源事件原文不做机器翻译；固定页面词条及动态统计单位已完成本轮中英文接入。
- 无 BLOCKED 或 NOT_IMPLEMENTED 的核心生产链路；上述验收边界保持 PASS_WITH_LIMITATIONS，不承诺未经证明的全天稳定性。

## 13. Git 与数据影响

Branch：`main`。HEAD：`9031d00017cecf8802f34a96f136bbf01007d862`。唯一 worktree 为原版主仓库；没有 staged 修改。最终 `git status --short` 为 68 个 tracked 修改（` M`）与 44 个 untracked 新增（`??`），共 112 个文件；无删除/重命名项。`git diff --shortstat` 为 68 files changed、4192 insertions(+)、3079 deletions(-)，该统计不含 44 个新增文件内容。完整文件清单如下，已与 tracked diff + untracked 逐项比对一致。

新增 Commit：无。Push：未执行。DevStatus Commit / Push：均未执行，本任务限定仅修改原版仓库，且明确禁止未经要求提交、推送。工作树保留本次全部修改供审阅。

未 commit、push、PR、merge、release、部署；未切分支或创建/删除 worktree；未修改 DevStatus、NetConsole-Next、fping独立项目、依赖/锁文件；未连接真实设备、未复制真实数据。修改保留在原版工作树等待用户审阅。

数据库仅通过隔离 Fixture 验证 schema/读写；真实业务库未迁移。保留的 .local 测试日志/视觉证据可重新生成，FULL Gate 与 smoke 负责退役其独占测试根。

### 文件清单（含未跟踪新增文件）

- `apps/desktop_renderer/src/api/acMeshLink.test.ts`
- `apps/desktop_renderer/src/api/acMeshLink.ts`
- `apps/desktop_renderer/src/api/groundUnattended.ts`
- `apps/desktop_renderer/src/components/ground-unattended/QuickPingChart.vue`
- `apps/desktop_renderer/src/components/ground-unattended/quickPingChartOptions.test.ts`
- `apps/desktop_renderer/src/components/ground-unattended/quickPingChartOptions.ts`
- `apps/desktop_renderer/src/i18n/groundUnattended.ts`
- `apps/desktop_renderer/src/i18n/runtime.test.ts`
- `apps/desktop_renderer/src/i18n/runtime.ts`
- `apps/desktop_renderer/src/navigation/registry.test.ts`
- `apps/desktop_renderer/src/navigation/registry.ts`
- `apps/desktop_renderer/src/platform/exportActionRegistry.ts`
- `apps/desktop_renderer/src/platform/exportEntryAudit.test.ts`
- `apps/desktop_renderer/src/router/index.test.ts`
- `apps/desktop_renderer/src/router/routes.ts`
- `apps/desktop_renderer/src/types/acMeshLink.ts`
- `apps/desktop_renderer/src/types/groundUnattended.ts`
- `apps/desktop_renderer/src/types/railTransitBaseData.ts`
- `apps/desktop_renderer/src/views/rail-transit/AcMeshLinkPage.vue`
- `apps/desktop_renderer/src/views/rail-transit/ArchivePage.test.ts`
- `apps/desktop_renderer/src/views/rail-transit/ArchivePage.vue`
- `apps/desktop_renderer/src/views/rail-transit/DeepCollectionPage.vue`
- `apps/desktop_renderer/src/views/rail-transit/GroundUnattendedView.behavior.test.ts`
- `apps/desktop_renderer/src/views/rail-transit/GroundUnattendedView.test.ts`
- `apps/desktop_renderer/src/views/rail-transit/GroundUnattendedView.vue`
- `apps/desktop_renderer/src/views/rail-transit/HeartbeatPage.test.ts`
- `apps/desktop_renderer/src/views/rail-transit/HeartbeatPage.vue`
- `apps/desktop_renderer/src/views/rail-transit/MeshAnalysisView.test.ts`
- `apps/desktop_renderer/src/views/rail-transit/MeshAnalysisView.vue`
- `apps/desktop_renderer/src/views/rail-transit/OverviewPage.vue`
- `apps/desktop_renderer/src/views/rail-transit/QuickPingPage.test.ts`
- `apps/desktop_renderer/src/views/rail-transit/QuickPingPage.vue`
- `apps/desktop_renderer/src/views/rail-transit/RailTransitBaseDataView.test.ts`
- `apps/desktop_renderer/src/views/rail-transit/RailTransitBaseDataView.vue`
- `apps/desktop_renderer/src/views/rail-transit/SettingsPage.locale.test.ts`
- `apps/desktop_renderer/src/views/rail-transit/SettingsPage.vue`
- `apps/desktop_renderer/src/views/rail-transit/SyslogPage.locale.test.ts`
- `apps/desktop_renderer/src/views/rail-transit/SyslogPage.vue`
- `apps/desktop_renderer/src/views/rail-transit/SystemHealthPage.test.ts`
- `apps/desktop_renderer/src/views/rail-transit/SystemHealthPage.vue`
- `apps/desktop_renderer/src/views/rail-transit/TimelinePage.vue`
- `apps/desktop_renderer/src/views/rail-transit/groundFeatures.ts`
- `apps/desktop_renderer/src/views/rail-transit/groundUnattended.css`
- `apps/desktop_renderer/src/views/rail-transit/groundUnattendedLabels.test.ts`
- `apps/desktop_renderer/src/views/rail-transit/groundUnattendedLabels.ts`
- `apps/desktop_renderer/src/views/rail-transit/useGroundUnattended.ts`
- `apps/desktop_renderer/tests/visual/README.md`
- `apps/desktop_renderer/tests/visual/VisualGroundFixture.vue`
- `apps/desktop_renderer/tests/visual/e2e/ground-unattended.visual.spec.ts`
- `apps/desktop_renderer/tests/visual/ground-main.ts`
- `apps/desktop_renderer/tests/visual/ground.html`
- `config/architecture/direct_sql_access.yaml`
- `config/architecture/ui_business_logic.yaml`
- `config/profiles/features/customer.json`
- `config/profiles/features/full.json`
- `config/storage_registry.yaml`
- `docs/CHANGELOG.md`
- `docs/architecture/REFACTOR_MAP.md`
- `docs/archive/ground-unattended-v2-delivery-2026-11-07.md`
- `docs/rail-transit/README.md`
- `docs/rail-transit/ground-unattended/README.md`
- `src/netconsole/application/rail_transit/base_data_application_service.py`
- `src/netconsole/application/rail_transit/web_application_service.py`
- `src/netconsole/backend/api/ground_unattended_router.py`
- `src/netconsole/backend/api/main.py`
- `src/netconsole/core/feature_registry.py`
- `src/netconsole/core/i18n.py`
- `src/netconsole/core/ping/fping_v5_runner.py`
- `src/netconsole/models/api/ac_mesh_link.py`
- `src/netconsole/models/api/ground_unattended.py`
- `src/netconsole/models/api/rail_transit_base_data.py`
- `src/netconsole/repositories/ground_unattended_repository.py`
- `src/netconsole/repositories/rail_transit_base_data_repository.py`
- `src/netconsole/services/ac/mesh_link_query_service.py`
- `src/netconsole/services/export/export_handlers.py`
- `src/netconsole/services/ground_unattended/README.md`
- `src/netconsole/services/ground_unattended/application_service.py`
- `src/netconsole/services/ground_unattended/eligibility.py`
- `src/netconsole/services/ground_unattended/fleet_ping.py`
- `src/netconsole/services/ground_unattended/heartbeat_state.py`
- `src/netconsole/services/ground_unattended/history_export.py`
- `src/netconsole/services/ground_unattended/history_query.py`
- `src/netconsole/services/ground_unattended/inventory.py`
- `src/netconsole/services/ground_unattended/quick_ping.py`
- `src/netconsole/services/ground_unattended/raw_lifecycle.py`
- `src/netconsole/services/ground_unattended/supervisor.py`
- `src/netconsole/services/ground_unattended/syslog_runtime.py`
- `src/netconsole/services/job_center/artifact_reconciliation.py`
- `src/netconsole/services/rail_transit/base_data_query_service.py`
- `src/netconsole/services/vehicle_mr_online.py`
- `tests/test_ac_mesh_link_query_service.py`
- `tests/test_ac_mesh_link_refresh_service.py`
- `tests/test_feature_registry_groups.py`
- `tests/test_ground_unattended_ac_resident.py`
- `tests/test_ground_unattended_api.py`
- `tests/test_ground_unattended_eligibility.py`
- `tests/test_ground_unattended_fleet_ping.py`
- `tests/test_ground_unattended_fleet_ping_retention.py`
- `tests/test_ground_unattended_health.py`
- `tests/test_ground_unattended_heartbeat_state.py`
- `tests/test_ground_unattended_history_export.py`
- `tests/test_ground_unattended_history_query.py`
- `tests/test_ground_unattended_quick_ping.py`
- `tests/test_ground_unattended_quick_ping_repository.py`
- `tests/test_ground_unattended_raw_v2_consumers.py`
- `tests/test_ground_unattended_syslog_field_validation.py`
- `tests/test_ground_unattended_syslog_v2_stress.py`
- `tests/test_ground_unattended_timeline_v2.py`
- `tests/test_ground_unattended_usability.py`
- `tests/test_rail_transit_base_data_edit_api.py`
- `tests/test_udp_syslog_reliable_spool.py`
- `tests/test_vehicle_mr_online.py`
