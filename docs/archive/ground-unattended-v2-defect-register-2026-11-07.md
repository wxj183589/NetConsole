# Ground Unattended V2 缺陷登记（2026-11-07）

## 1. 状态与证据规则

下列代码缺陷均已修复并定向回归，当前没有已知未解决的 P0/P1。等级按触发后的业务影响判断；自动化通过不代表原生 Windows/长时/真实设备验收完成。行号针对当前 dirty 工作树，后续变更可能漂移。

路径除特别注明均相对 `src/netconsole/services/ground_unattended/`。证据位于 `.local/ground-v2-final-audit/`，测试 node 位于仓库 `tests/`。首次失败和修复后通过均保留，不使用通过日志覆盖首次失败。

## 2. 修复台账

| ID / 级别 | 文件与行号 | 触发 / 影响 | 最小修复 | 验证与状态 |
| --- | --- | --- | --- | --- |
| GUA-01 / P0 | heartbeat_state.py:435 `_check_arriving_probe_gap` | 新样本先覆盖旧 timestamp，跨采样暂停桥接失败证据，可能假离线 | 到达时先核验 gap，清连续证据并 UNKNOWN/DEGRADED | `test_arriving_probe_cannot_bridge_a_sampler_pause`，首次 defect-reproduction.log；最后 Ground 回归；FIXED |
| GUA-02 / P0 | heartbeat_state.py:236 `configure_targets`、:675 `reconcile_targets` | 地址/身份变化沿用旧状态、重复 IP 错归属、移出端位仍聚合，在线状态可错 | 目标变化重建 live 状态，冲突失败关闭，删除 departed 成员 | `test_reconfigured_address_and_duplicate_ip_fail_closed`、`test_train_membership_reconciliation_removes_departed_endpoint`；首次 defect-reproduction.log；FIXED |
| GUA-03 / P1 | application_service.py:428、:439、:448 | 当前 API 仍呈现移除的 MR/train，统计混入过时快照 | 当前 run 按库存身份/端位过滤；历史 run 事实保留 | `test_current_heartbeat_hides_departed_mr_but_keeps_historical_facts`（test_ground_unattended_api.py:205）；首次 stale-reproduction.log；FIXED |
| GUA-04 / P0 | supervisor.py:1416、:1437 | 心跳 transition 回调做数据库 I/O，SQLite 锁异常外溢/阻塞采样 | 有界待写 4096、批次 256、锁外落盘、稳定去重和失败保留/health | `test_heartbeat_events_defer_database_io_and_retry_without_losing_transition`（test_ground_unattended_ac_resident.py:167）及容量回归；首次 event-reproduction.log；event-regression-2.log 68 passed；FIXED |
| GUA-05 / P1 | quick_ping.py:363、:630 | 意外重复启动占并发资源；runner 返回未请求 IP 污染统计/归属 | 同目标同参数活动 run 拒绝 409；异常目标失败关闭 | test_ground_unattended_quick_ping.py:82、:101；重复启动首次 defect-reproduction.log；最后 Ground 回归；FIXED |
| GUA-06 / P1 | syslog_runtime.py:585、:600、:613、:2026 | metadata 次序或短暂锁失败导致注册漂移；延迟 raw 注册后 projection 不恢复 | 有序有界队列；busy/locked 最多三次重试；错误索引有界；pending 注册完成后重试派生 | `test_metadata_is_ordered_bounded_and_retries_transient_sqlite_lock`、`test_projection_error_recovers_after_deferred_raw_registration`（test_udp_syslog_reliable_spool.py:74、:103）；final-syslog-regression.log；FIXED |
| GUA-07 / P0 | syslog_runtime.py:553 `_close_one` | fsync 失败前已释放 open owner，无法正确重试关闭/Flush | fsync 成功后才移除 owner，失败保留文件和归属 | `test_failed_raw_fsync_retains_open_owner_for_retry`（test_udp_syslog_reliable_spool.py:123）；final-syslog-regression.log；FIXED |
| GUA-08 / P1 | syslog_runtime.py:171 `RawCompressionWorker.submit`、:213 起压缩重试 | 同文件重复提交、短暂压缩失败影响索引/后续处理 | pending 集合去重、最多三次重试、成功校验后登记，失败保留原始文件/health | `test_gzip_duplicate_submission_and_transient_failure`（test_udp_syslog_reliable_spool.py:138）及已有坏 gzip/原始保留测试；FIXED |
| GUA-09 / P1 | syslog_runtime.py:1899、:2272 | live/replay timeline 缺失设备时间/接收时间，关联时间不可靠 | 两路径统一保留 device_time、received_at 和时间来源 | `test_live_and_replayed_timeline_preserve_device_and_receive_times`（test_udp_syslog_reliable_spool.py:29）；final-syslog-regression.log 32 passed；FIXED |
| GUA-10 / P1 | apps/desktop_renderer/src/views/rail-transit/QuickPingPage.vue:150、:211；apps/desktop_renderer/src/components/ground-unattended/QuickPingChart.vue:28 | 终态停止操作/抽屉跳转及 Toolbox 未注册影响核心交互/绘图 | 终态停止保护和禁用、目标传递、注册已有 ToolboxComponent | QuickPingPage.test.ts 与 quickPingChartOptions.test.ts 最后 10 passed；浏览器 12 passed；FIXED |
| GUA-11 / P2 | apps/desktop_renderer/src/components/ground-unattended/quickPingChartOptions.ts:27 | ECharts 6 grid containLabel 兼容警告导致严格浏览器验收失败 | 局部 outerBoundsMode=same、outerBoundsContain=axisLabel | browser-visual-verified.log 首次 6 passed/6 failed；browser-visual-fixed.log 12 passed；chart-fixed.log 1 passed、build PASS；FIXED |
| GUA-12 / P2 | config/architecture/direct_sql_access.yaml（`scripts/dev/ground_v2_soak.py` 条目） | 新增测试脚本 integrity SQL 未登记，架构门失败 | 仅 TEST_ONLY 登记独占 fixture 数据库完整性检查，不放宽生产边界 | architecture-final.log 初次失败；architecture-fixed.log 与 FULL 12/12 PASS；FIXED |

GUA-06～09 除注明首次失败的场景外，为代码审查后补充故障注入回归，未保存可独立重放的修复前失败日志；不虚构“全部均先红后绿”。修复后的完整 Ground 回归为 453 passed、1 skipped，Syslog 最后定向 32 passed；这些套件包含相互重叠测试，不能相加作为独立覆盖数量。

## 3. 有界故障策略

心跳 SQLite 写失败待写事件保留，队列满显式 health/失败关闭，不能保证无限数据库故障仍无损保留所有事件。Syslog metadata 和压缩重试最多三次；超过后 health 暴露并保留原始证据，不声称永久故障会无限自动恢复。UDP 本身不提供传输可靠性，本轮“0 dropped”是指定回环压力 run 的应用计数。

## 4. 未完成的验收项

| ID | 类型 | 状态 | 所需补验 |
| --- | --- | --- | --- |
| GAP-WIN-DPI | 环境/证据缺口 | BLOCKED | 六原生分辨率/DPI、重点125%，十页交互 |
| GAP-LIFECYCLE | 环境/证据缺口 | BLOCKED | 实际 Renderer/Backend 强杀、Windows 重启、托盘长运行、孤儿进程/端口 |
| GAP-INSTALLER | 环境/候选缺口 | BLOCKED | 干净源码候选、隔离 VM 安装/启动/卸载；本轮禁止提交和正式部署 |
| GAP-24H | 时长/系统覆盖缺口 | NOT_RUN | 全系统真实 24 小时；现脚本仅组件、实测245秒 |
| GAP-FINAL-FULL | 快照缺口 | NOT_RUN | 用户授权最终集成 commit 后重新 FULL；现为 FULL+最后定向验证 |

以上是验证缺口，未定性为已复现的软件缺陷，也未掩盖为 PASS。不存在已知未解决 P0/P1 的结论只适用于本轮已检查和执行的范围。总结果见[主报告](./ground-unattended-v2-final-stability-audit-2026-11-07.md)。
