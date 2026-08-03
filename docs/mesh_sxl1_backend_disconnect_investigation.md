# 绍兴地铁 1 号线 MESH 导入与 Backend 中断调查

## 范围与结论

本记录覆盖正式局点 `sxl1` 在没有 AC/FIT-AP 运行数据时，仅使用轨道交通基础资料和 `2026_07_24_1meshlog.zip` 完成 MESH 导入、AP Identity 映射、位置投影和 RSSI 查询的故障链。

调查结论：截图中的“Backend 连接中断”不是 Backend 主进程退出。空 MESH 目录查询触发了单接口 HTTP 500，前端把该错误泛化成了 Backend 中断；ZIP 导入本身还存在基础资料索引不完整和事务 staging 中的索引刷新未持久化两个独立问题。

修复分支以 `b0d19bf1` 为集成基线，合入基线后的分支提交为 `5372defc`。真实数据验证只在 `D:\NetConsoleTestData\sxl1-mesh-fix-<run-id>` 隔离副本中执行，正式局点和用户 ZIP 始终只读。

## 根因链

### 1. 空目录 overview 返回 500

`mesh_session_index` 表存在但没有记录时，SQLite 的 `SUM(CASE ...)` 返回 `NULL`。`MeshAnalysisSummaryDTO.warning_session_count` 等整数字段拒绝 `NULL`，导致 `/api/rail-transit/mesh-analysis/overview` 返回 500。Backend 进程仍在线，Electron 切换局点时记录的 shutdown/restart 是受管生命周期，不是该接口导致的崩溃。

修复后，表存在但无记录时聚合值为 `0`；旧库缺表时仍保留 `NULL` 表示指标不可用的兼容语义。

### 2. 纯基础资料索引没有 Radio alias

局点有 615 条有效且物理 MAC 唯一的轨旁 AP 基础资料，没有 AC/FIT-AP 记录。历史索引只有 615 个物理 AP alias，`source_revision=-1`，而当前基础资料源修订为 615。

基础资料的厂商字段为空。旧索引构建器要求厂商显式等于 H3C，因此没有生成 R1/R2 完整 alias。修复后仅对 `base_data` 允许厂商未知；仍要求合法 48 位物理 MAC及末位为 `0`，并统一调用 `derive_h3c_r1_mac`、`derive_h3c_r2_mac`。明确的非 H3C 厂商、非法 MAC、非物理 MAC仍不派生。

### 3. staging 中重建的 Identity 没有持久化

ZIP 导入先把局点 `devices.db` 复制到事务 staging，再在 staging 中解析并刷新 Peer 映射。原流程在 staging 数据库中重建了 Identity，因此 parsed 明细可以命中一部分 Peer；提交阶段只发布 MESH Profile 和 catalog，不会把 staging `devices.db` 覆盖回局点数据库，导致局点 Identity 状态仍停留在旧 revision。

修复后，`mesh_bundle_import` Worker 在创建事务快照前显式检查当前局点 Identity source revision，并在 stale 时先原子重建派生索引。随后复制到 staging 的数据库与最终 parsed 映射使用同一 revision。普通 GET 不重建 Identity，也不更新 `mesh_links`。

### 4. 基础资料位置字段被不完整索引覆盖

历史 Identity entity 没有承载基础资料中的全部区间起止、线路侧等字段，位置快照优先使用 Identity 时会丢失完整基础资料。修复后位置快照以基础资料为主，只用 Identity 补充基础资料中不存在的物理 AP；同 MAC 多位置仍返回 ambiguous，不选择第一条。

`sxl1` 的 615 条基础资料都有 `direction`，但 `line_side` 为空，且 `direction` 的实际值为上行/下行。展示层现在仅在同一条基础资料的 `line_side` 为空时回退到 `direction`，不跨记录推断。

### 5. 前端错误分类过宽

MESH 页面现在区分请求 Abort、超时、单接口 500 和 Backend 不可达。局点切换导致的 Abort 不显示红色中断告警；单接口 500 显示“MESH 来源查询失败，Backend 仍在线”并保留 request id；刷新失败不清空上一次成功的会话和摘要。

## 修复后的写入顺序

1. Worker 校验已批准的 ZIP 预览和映射。
2. 检查当前局点 AP Identity source revision。
3. stale 时在局点数据库原子重建派生 Identity 索引。
4. 复制一致的 `devices.db`、catalog 和目标 Profile 到事务 staging。
5. 在 staging 中解压、解析、收集 distinct Peer MAC 并批量精确映射。
6. 原子发布 MESH Profile、catalog 和成功 manifest。
7. catalog 派生索引按现有后台机制刷新；普通查询保持只读。

## 真实副本验收

输入 ZIP：

- SHA-256：`fac6a740a7bb67ca27430993c58a606f5e5127041b1358c4ce130c52d8a09e06`
- 压缩大小：331,322 bytes
- 展开大小：2,470,793 bytes
- 成员：1 个 UTF-8 MESH 日志
- Zip Slip、绝对路径、盘符路径和 UNC 路径：未发现

导入与进程：

- 独立 `netconsole.background_worker` 退出码：0
- Worker 耗时：4.714 秒
- JSONL 事件：64，非法帧 0，stderr 为空
- 导入期间 `/api/health`：80 次成功，失败 0
- health 最大耗时：26.966 ms，P95：26.090 ms
- Worker 完成后 Backend 仍在线
- 导入来源：1；parsed 链路：12,643；distinct Peer：454

Identity 与位置：

- 导入前：revision 1，source revision -1，alias 615，derived alias 0
- 导入后：revision 2，source revision 615，alias 1,845，derived alias 1,230
- 精确命中：290 个 Peer，均为基础资料派生的 Radio 1 alias
- unresolved：164 个 Peer；不使用名称、OUI、前缀或位置猜测
- 已命中的 7,394 条链路均可投影物理 AP、点位名称、站点、区间、里程和上/下行

局点与查询：

- 13 个 SQLite 文件 `PRAGMA quick_check` 全部为 `ok`
- 审计分类：`active_site`；损坏数据库 0；符号链接 0
- overview：1 来源、1 列车、1 MR、12,643 条链路，索引状态 `ready`
- overview 查询：146.139 ms；session 查询：10.164 ms
- 日志本地链路全部属于 Radio 2；对端精确命中的 Peer alias 属于 Radio 1
- Radio 2 主链查询：约 1.17 至 1.23 秒
- Radio 2 轨旁查询：约 0.77 至 0.85 秒
- 页面仍按“主链完成首帧后再调度轨旁图”的顺序加载，两个重型接口不并发首发

正式 `devices.db` 和用户 ZIP 的 SHA-256 在验收前后均不变。测试副本之外没有写入 raw、parsed、基础资料或报告。

## 数据边界与后续处理

164 个 unresolved Peer 不在 615 条基础 AP 的任何完整 R1/R2 alias 中：其中大部分厂商前缀也未出现在当前基础资料中，少量前缀相同但完整地址仍不相等。该结果属于基础资料覆盖缺口，不能通过恢复 36/40 位前缀、OUI、名称或位置模糊匹配处理。

要进一步提高命中率，应补充或校正同一局点的轨旁 AP 基础资料，然后运行 Identity 重建和 identity-only remap；不需要重新导入 ZIP，也不会改变原始链路数量、ACTIVE/STANDBY 状态或切换统计。

回滚本次代码不会影响既有 raw、parsed 或基础资料。新增索引内容均为可重建派生数据；代码回滚后可按原有 Identity 重建任务重新生成。

首次真实 Worker 验收脚本曾因未实时消费 Windows JSONL 管道而被管道背压阻塞，测试 Worker 在 120 秒保护时限后被终止并保留 staging。改为实时消费 stdout/stderr 后，同一正式代码路径在全新副本中 4.714 秒完成；该超时属于验收脚本问题，不是产品 Worker 超时。
