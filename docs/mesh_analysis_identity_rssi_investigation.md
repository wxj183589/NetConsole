# MESH 身份、存储协调与 RSSI 调查记录

## 基线与范围

- 基线 SHA：`108cc0ba6eb6640e0a0d27bf3d6019628a0e0f9a`
- RSSI 首次加载追加修复基线：`5dba2745ff326c3b75c1e445085961a6241c4126`
- 产品版本：`v1.4.7`
- 调查对象：轨道交通 → MR 原始 MESH 日志分析
- 真实数据状态：仓库不包含列车07-MR-CT 的原始日志、parsed SQLite 或对应局点数据库。本记录不连接 AC/MR，也不访问或修改 `D:\NetConsoleData`。

## 根因证据

### 问题 1：历史来源的 AP 身份投影可能过期

当前统一解析链使用 `MeshPeerMappingService` 调用 `ApIdentityQueryService.resolve_peer_mac`，Identity builder 生成完整的 H3C R1/R2 derived alias；批量 remap 只读取 distinct `peer_mac_normalized`，不会逐行调用 resolver，也不会恢复模糊前缀匹配。

旧 parsed/source schema 没有保存 Identity revision，因此仅凭旧的 `unresolved` 字段无法判断“当时没有 AP”还是“索引后来更新”。本次增加来源与 parsed DB 的 `identity_index_revision`、`identity_mapped_at`、`identity_mapping_status`。查询服务只读比较来源保存 revision 与当前 `ap_identity_index_state.revision`；当前 revision 大于 0 且不一致时返回 `identity_stale`。普通 GET 不写库；Web 打开 `parsed_status=ready` 的 stale 来源后，通过现有任务中心提交一次 identity-only remap，旧结构、缺失或损坏的 detail DB 不自动触发全量重解析。

### 问题 2：建链表行点击参数误用

Element Plus 的 `row-click` 参数为 `(row, column, event)`，旧方法把第二参数当作 `showChart` 布尔值，导致 column 对象被判定为真值并打开 RSSI。现已拆成 `selectBuildOrderRow(row)` 与 `openBuildOrderRssi(row)`；建链表只绑定前者，双击没有 RSSI 处理器，只有“查看动态图”操作列按钮打开图表。

### 问题 3：两个重型图表请求互相拖累

旧实现使用 `Promise.all` 加载 active-path 与 trackside-signal，任一请求失败都会使整体失败；普通 GET 默认 15 秒也会误中止重型查询。现改为先加载 active-path，再按轨旁区域可见性懒加载 trackside-signal；两者拥有独立 loading/error/retry 状态，失败状态不再显示“采样点 0”。仅两个图表 API 使用局部超时（active 30 秒、轨旁 60 秒），普通 GET 默认仍为 15 秒，外部 AbortSignal 继续生效。

在 `5dba2745` 后的追加修复中，轨旁可见性不再直接触发请求。主链响应写入后必须经过 `nextTick` 和两个 `requestAnimationFrame`，再通过 `requestIdleCallback(timeout=750)` 调度轨旁；不支持 idle callback 时使用 `setTimeout + requestAnimationFrame`。IntersectionObserver 只决定轨旁是否需要加载，不能越过主链首帧门。主链失败时轨旁不自动加载，轨旁重试也不重新请求主链。

页面级协调器以 endpoint、session、来源文件/revision、Identity revision、Radio、目标点数、时间范围和 include flags 组成请求 key。同 key 的并发调用复用同一个 Promise；新 key、页面暂停、Radio/session 变化会取消旧请求，generation 和 AbortSignal 共同阻止旧响应覆盖新状态。KeepAlive 返回时 revision 未变化直接复用已完成缓存；若暂停时请求仍在途，则恢复后只重启被取消的阶段。

### 问题 4：外部删除目录后的三层状态不一致

MESH catalog、每个 MR 的 `mesh.sqlite` 和 detail SQLite 分别保存会话摘要、来源索引与解析事实；直接删除物理目录只移除了文件，并不会同步清理数据库记录。旧列表查询会继续信任 catalog，随后打开缺失 detail DB，导致单条悬空记录扩大为页面 500。现在列表只校验数据库中已登记的 MR/source 路径，不递归扫描数据根：整个 MESH 根不存在时返回空快照；单个 detail DB 缺失时只过滤对应来源，其他有效来源继续返回；GUI 的“仅删除解析结果”通过 `parsed_deleted_at` 保留可重建来源。

### 问题 5：终态任务恢复覆盖历史管理状态

普通 Task snapshot upsert 过去没有携带 `acknowledged_at`、`dismissed_at` 等历史字段，恢复写回可能清空用户已处理/已移除状态。同时，导出恢复把 `COMPLETED` 任务的文件缺失当作任务失败，产生“报告恢复校验失败”。现在 upsert 保留历史管理字段，恢复处理和返回结果都跳过 dismissed 任务；已完成任务保持 `COMPLETED`，Artifact 单独标记 `MISSING`，FAILED/CANCELLED 仅清理未完成临时文件，不改写终态。

## 存储与任务协调规则

- 整个 MESH 数据目录缺失时，summary 和 session page 返回 HTTP 200 对应的空结果，不为查询重建目录。
- 单个已登记 detail DB 缺失时，仅从有效列表排除该 session；读取异常按 MR 粒度记录日志，其他来源继续处理。
- 来源删除是幂等的；物理文件已缺失仍清理 source/catalog 关系，并分别返回 `deleted_file_count`、`missing_file_count` 与 `already_deleted_count`。
- 删除请求提交后前端立即移除来源、计数、选择和详情；overview 使用 AbortController 与 generation，删除前的旧响应不能恢复已删除项，随后仍以 REST 刷新为最终事实。
- MESH 任务卡从全局 `useTaskStore` 派生，复用现有任务 WebSocket/polling；全局 dismiss 后本地卡片同步消失，不创建第二套任务连接。

## A-G 判定

| 项目 | 结论 | 证据边界 |
| --- | --- | --- |
| A. Identity 缺少物理 AP | `UNVERIFIED` | 没有现场 AP Identity/基础资料副本。 |
| B. 缺少完整 R1/R2 alias | `UNVERIFIED` | 代码支持完整 derived alias，但未对现场索引逐条核验。 |
| C. alias 多实体 ambiguous | `UNVERIFIED` | 没有现场 alias/entity 候选集合。 |
| D. Identity 更新而旧 parsed 映射未刷新 | `SUPPORTED` | 旧来源没有 revision 元数据；现有 healthy parsed DB 已具备 identity-only remap 能力。 |
| E. 解析使用旧 revision | `INFERRED` | 代码可证明历史结果没有可比较 revision；是否发生在目标来源需真实副本确认。 |
| F. 离线/暂停 AP 被错误排除 | `UNVERIFIED` | 没有现场 AC 运行状态与轨旁业务资料。 |
| G. 基础资料确实没有物理 AP | `UNVERIFIED` | 无法从截图或仓库样本证明不存在。 |

典型待核对 Peer 的规范化 MAC 为：`bc5a34579c8f`、`bc5a34579c9f`、`bc5a34579cef`、`bc5a34579cff`、`bc5a3457b5ff`、`bc5a3457817f`、`bc5a3457c11f`。附件中提出的 `9c80`、`9ce0`、`b5e0`、`8160`、`c100` 只能作为现场核查候选，不能替代 `derive_h3c_r1_mac`、`derive_h3c_r2_mac`、`normalize_mac_key` 与 `resolve_peer_mac` 的精确结果。

## 历史来源刷新

健康 parsed DB 走现有 `MeshSourceRebuildService` identity-only remap：批量读取 distinct Peer、统一 resolver、批量替换 `mesh_peer_mapping` 和 `mesh_links`/`active_points` 身份投影，最后写入 revision metadata。raw 日志、链路事实、ACTIVE/STANDBY 数量和切换事实不重新解析、不删除。缺失、损坏或旧结构化 DB 才走原始日志重建路径。remap 未完成时页面通过 warning 暴露 stale 状态，不把旧 unresolved 静默当作最新事实。

## RSSI 查询与性能边界

当前 parsed repository 已有并复用以下组合索引：

- `mesh_links(source_file_id, radio, sample_time, id)`
- `mesh_links(source_file_id, link_state, radio, sample_time, id)`
- `mesh_links(source_file_id, peer_mac_normalized, radio, sample_time, id)`
- `active_points(source_file_id, radio, sample_time, id)`
- `switch_events(source_file_id, radio, event_time, id)`

查询仍保持完整的时间戳、ACTIVE/STANDBY、切换、断点和统计语义；显示层只在受控行集上降采样。仓库没有目标现场数据，因此本次不能报告真实 SQL 耗时、读取行数、响应字节数、点数或 `EXPLAIN QUERY PLAN` 结果，不能声称已完成现场性能验收。

本次追加修复没有修改后端 SQL、索引、DTO、既有关键点下采样或 30/60 秒局部超时，也没有在 GET 中增加缓存写入。现有 600 点有界查询与图表缓存继续使用；是否需要持久图表缓存、300 点预览层或新的可选字段协议，必须在显式测试数据副本完成 profile 后再决定，不能以缺少现场证据为由改变 MESH 业务语义。

## 证据缺口与禁止事项

- A-G 中标记 `UNVERIFIED` 的项目必须在真实数据副本上只读核验，并记录 matched/unresolved/ambiguous 数量与耗时。
- 没有恢复 36/40 位 MAC 前缀匹配，没有按 OUI、名称、站点、位置或截图 MAC 写死映射。
- 没有刷新 AC、连接车载 MR、修改真实 raw/parsed/报告或真实业务数据根。

## 回滚

本次 schema 变化仅为幂等新增列；回滚代码不会删除这些列，旧代码可忽略它们。需要恢复行为时可回退本分支提交；不要删除或重建用户的 raw、parsed SQLite、报告或 Identity 索引。
