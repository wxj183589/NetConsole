# Mesh 原始日志分析 Web 页面

## 定位

当前 `/rail-transit/mesh-analysis` 是 Electron/Vue 的离线 MESH 分析工作台，Feature key 为 `module.mesh_analysis`。页面负责受控导入、来源匹配、重建任务、主链路建链顺序、链路明细、动态图和报告任务；原始日志、parsed SQLite 和 session ID 仍由 Python Core/Job/Export Process 管理，Vue 不实现解析或业务判定。

```text
catalog.sqlite
  -> MR/mesh.sqlite 来源索引
  -> MR/parsed/<source>.mesh.sqlite
  -> Application Service / Query Service
  -> Vue 分页与降采样展示
```

## 数据和规则

- 来源索引：`files/rail_transit/mr_raw_mesh/catalog.sqlite` 与每个 MR 根下 `mesh.sqlite`；
- 正式明细：每个来源对应的 `parsed/*.mesh.sqlite`，包含 `mesh_links`、`active_points`、`active_segments`、`switch_events`、`rssi_stats`、`diagnosis_events` 和 `parse_issues`；
- 主/备链路：直接读取 `mesh_links.link_state`，前端不根据当前 Active 数量推断备链；
- 短时建链、正常切换、同 AP 双射频和乒乓：复用现有 `_active_build_order_rows_from_points`，不在页面、报告或导出器复制规则；来源 `analysis_params_json` 只保留解析时的历史追溯信息，不能覆盖当前局点默认；
- RSSI：使用持久化统计和结构化采样。缺失值保持 `null`，已有真实 `0` 保持原值；
- 空口：读取结构化 Mesh 指标中的 Tx/Rx busy；没有持久化 CtlBusy 时返回 `null`，不从原始文本临时抓数字；
- 解析诊断：来源摘要分列 `info_count`、`warning_count`、`error_count`；列表“告警”只显示 `warning_count + error_count`，INFO 诊断不影响完整性、不进入异常摘要或正式报告。旧来源仅有混合 `issue_count` 时保守显示，重新解析后升级；
- 来源详情分别返回 catalog/profile schema、parser 语义版本、derived analysis 版本和 AP Identity projection revision。页面打开只检测并展示状态，不自动提交重建；Identity stale 只显示“立即刷新身份映射”，parser outdated 才允许显式重新解析，二者不能互相冒充；
- 导入前由 `MeshImportPreflightService` 核对 Profile 根、raw、parsed、来源索引、catalog 会话和 fingerprint。数据库仍有来源而受管文件被人工删除时，catalog 持久化 `BROKEN_SOURCE` 生命周期记录；重新选择同一正文可恢复原 session 的 raw 并重建，而不是要求删除数据库；
- AP 覆盖核查：来源列表勾选恰好两个当前局点来源后运行 `capability.mesh.coverage_audit`。服务端直接聚合两个 parsed SQLite 的有效 `ACTIVE/STANDBY`（`LinkCnt>0`）；优先用 remap 已持久化的 `canonical_ap_mac`（兼容 `peer_ap_mac`）归并物理 AP，不会再次把已匹配 AP 降级为 Peer Radio MAC 重新解析。只有旧 parsed 库缺少物理 MAC 投影时才走只读 Identity fallback；索引未就绪则返回“AP Identity 索引不可用”，而非把全部观测列为资料未匹配。每个局点独立数据库的 Identity scope 均为 `current`，与 MESH remap 一致。结果页和 Excel 摘要显示来源级、全集 Peer Radio/物理 AP 去重数及持久化/fallback 诊断；不在 Vue 去重，不重新扫描 raw 日志。核查默认按已观测站点/区间的正线范围，并同时提供全正线计数；未观测不代表故障。

索引记录的旧绝对 `parsed_db_path` 随数据根迁移失效时，只允许在当前 MR 的 `parsed` 受控目录内按同名文件回退；不会回写索引。普通 GET 遇到解析结果或 raw 缺失时只显示明确 warning，不自动修复或重解析；修复仅发生在用户显式重新导入或提交维护任务后。

## API

查询接口保持 GET；导入、重建和报告使用受控 POST/Task API：

```text
GET /api/rail-transit/mesh-analysis/summary
GET /api/rail-transit/mesh-analysis/sessions
GET /api/rail-transit/mesh-analysis/sessions/{session_id}
GET /api/rail-transit/mesh-analysis/sessions/{session_id}/links
GET /api/rail-transit/mesh-analysis/sessions/{session_id}/active-build-order
GET /api/rail-transit/mesh-analysis/sessions/{session_id}/charts/active-path
GET /api/rail-transit/mesh-analysis/sessions/{session_id}/charts/peer-segment
GET /api/rail-transit/mesh-analysis/sessions/{session_id}/timeline
GET /api/rail-transit/mesh-analysis/sessions/{session_id}/switch-events
GET /api/rail-transit/mesh-analysis/sessions/{session_id}/rssi
GET /api/rail-transit/mesh-analysis/sessions/{session_id}/channel-busy
GET /api/rail-transit/mesh-analysis/sessions/{session_id}/anomalies
GET /api/rail-transit/mesh-analysis/sessions/{session_id}/ap-statistics
GET /api/rail-transit/mesh-analysis/sessions/{session_id}/artifacts
GET /api/rail-transit/mesh-analysis/sessions/{session_id}/artifacts/{artifact_id}/download
DELETE /api/rail-transit/mesh-analysis/sessions/{session_id}/artifacts/{artifact_id}
GET /api/rail-transit/mesh-analysis/sessions/{session_id}/raw-sources
GET /api/rail-transit/mesh-analysis/sessions/{session_id}/raw-sources/{source_id}/tail
POST /api/rail-transit/mesh-analysis/ap-coverage/audit
POST /api/rail-transit/mesh-analysis/ap-coverage/export
```

POST /api/rail-transit/mesh-analysis/import-context/prepare
POST /api/rail-transit/mesh-analysis/import-preview
POST /api/rail-transit/mesh-analysis/bundles/import
POST /api/rail-transit/mesh-analysis/sources/batch-delete
POST /api/rail-transit/mesh-analysis/sessions/{session_id}/maintenance
POST /api/rail-transit/mesh-analysis/sessions/{session_id}/rebuild
POST /api/rail-transit/mesh-analysis/sessions/{session_id}/report
GET /api/rail-transit/mesh-analysis/analysis-params
GET /api/rail-transit/mesh-analysis/analysis-params/templates/{service_type}
PUT /api/rail-transit/mesh-analysis/analysis-params

不存在任意 SQL、任意命令或直接文件系统写入路由；长任务统一进入 Task Center，报告统一进入 Export Process。

## 文件安全

报告和 raw 先由服务端在当前 MR 的 `raw/outputs` 受控目录枚举，再生成不可逆 `artifact_id/source_id`。下载和 tail 只接受该 ID，不接受相对路径、绝对路径、UNC 或 `..`；响应不包含本机绝对路径。删除只接受显式确认的派生报告/导出文件，并限制在当前 MR `outputs` 白名单目录；同名 sidecar 和临时文件可一并清理，原始导入日志、parsed SQLite、catalog 和 raw 永不由该入口删除。压缩 raw 仅显示 metadata，不在请求线程在线解压 tail。

## 性能和生命周期

- Web 详情页签固定为“主链路建链顺序、链路明细、RSSI 分析、空口负载、切换事件、报告与来源”；Rate 原始值、Retry/Error 增量、AP 统计和异常摘要不再作为独立页面页签，也不会在打开会话时发起对应请求。底层结构化字段、查询 API 和报告数据保持不变；
- 主链路建链顺序、链路明细、RSSI 和空口图表使用同一可视区域高度计算，监听窗口与容器尺寸变化；分页保留在表格下方，表格内部滚动。嵌套 RSSI/空口模式 Tab 不再占据独立内容高度；
- 链路明细使用后端分页和时间/AP/MR 条件；
- 主链路时间线读取既有区间，不返回全部采样；
- RSSI 和轨旁图先在 Repository 下推 `source/radio/time`，再按 SQL 候选行、关键事件、frame 和 series 预算读取；不再全库 `fetchall` 后才抽样。统一 `response_budget` 返回 source/selected、total/returned、LOD 级别和降级原因，目标响应 4 MiB，16 MiB 仅是自动逐级降级后的最后硬阈值；
- 全天 Overview 的曲线、事件、站点带、series 和 frame 分别受全局预算约束。事件超过 256 条时保留关键事实并按时间代表采样，真实总数继续通过 `total_events` 返回；轨旁图最多向 Renderer 交付受控 frame/link-point/series 集合，缩放后再按当前窗口读取细节；
- 切换事件列表使用真实服务端分页，默认 100 条并支持 50/100/200，Radio、正常/短时/乒乓条件下推 SQL；表格高度按可用视口和实际行数共同计算，不再固定 430px；
- RSSI 工作区取消整卡灰色遮罩，metadata、主链查询、轨旁等待/查询/渲染分别维护局部状态；旧图在新窗口请求期间继续可见。轨旁未加载且未在加载时始终提供当前窗口加载动作，失败时提供重新加载；
- 最近窗口使用非响应式、最多 2 项且估算 payload 合计不超过 16 MiB 的 LRU；key 包含 session、source revision、Radio、窗口和预算。返回最近窗口直接复用 immutable DTO 与 compact series cache，驱逐、切换来源和卸载都会显式 dispose；
- 切换事件 payload 预载前后 AP、Peer 和建链区段，图表点击可回到建链顺序；ECharts 仅在活动 Tab 且容器宽高有效时初始化，激活、数据变化和 ResizeObserver 触发 RAF resize，卸载时取消 RAF、解除事件并释放实例。
- 离线来源列表默认 30 秒刷新，连续失败三次降为 90 秒；
- 页面隐藏时不请求，组件卸载时清理 timer 和 ECharts；
- raw 只有用户明确点击且来源为普通文本时读取受控尾部。
- 页面内任务区域只显示任务名、状态、紧凑进度和一行摘要；完整日志、结果、Artifact、错误和停止操作统一进入 Task Center。刷新页面只恢复活动态或失败态 MESH 任务，不自动展开旧 COMPLETED 任务。
- 多选来源删除只创建一个 `mesh_analysis_sources_delete` Job。Worker 按稳定顺序逐来源执行，返回 requested/success/failed/skipped 和逐项状态；任务完成前列表不提前移除，`parsed_deleted` 保留来源并刷新，只有 raw 来源删除成功或已不存在才移除行。

### 2026-08-12 生成数据基准

命令使用当前 worktree `src`，每个 frame 10 条 ACTIVE/STANDBY link；耗时为 Repository 查询，payload 为基准脚本构造的有界标量响应，不包含 Electron 首帧耗时。

| link rows | active query | active objects / payload | trackside query | trackside objects / payload |
| ---: | ---: | ---: | ---: | ---: |
| 50,000 | 0.415 s | 7,217 / 0.833 MiB | 2.034 s | 50,000 / 5.765 MiB |
| 200,000 | 0.792 s | 8,019 / 0.925 MiB | 0.653 s | 4,230 / 0.488 MiB |
| 500,000 | 1.351 s | 8,049 / 0.937 MiB | 1.424 s | 4,860 / 0.560 MiB |
| 1,000,000 | 2.322 s | 8,099 / 0.949 MiB | 3.422 s | 5,890 / 0.679 MiB |

50k 轨旁仍走既有中等规模完整 run/boundary 语义，因此 Repository 基准保留 50k 行；正式 Query Service 随后仍执行统一 Response Budget。200k 起 Repository LOD 生效，返回对象数、payload 和峰值内存不再随原始行数线性增长。真实 Renderer transform、ECharts `setOption` 和 first paint 继续由 Electron workload 诊断采集，本脚本不伪造浏览器渲染数据。

## 当前边界

- Job/Application Service 继续负责导入、重建、解析和报告；
- Web 不连接 AC、不控制 Agent、不开放 `executor=AGENT`，也不修改 Online MR 生命周期；
- 页面和报告共用 `MeshApLocationSnapshot`；候选同时读取 FIT-AP 与独立轨旁 AP 基础资料，优先按规范化 AP MAC 匹配，不要求存在 AC、FIT-AP 或交换机资料。匹配成功后返回点位编号、AP 名称、站点、区间起终点、方向和里程；基础 AP 名称为空时回退点位编号。无法唯一匹配 AP 时保持原始值和空归属，不猜测站点、区间、里程或方向。
- 报告和链路明细弹窗每次打开都从当前局点上下文 ID 读取同一份 `site_meta.json` 中的完整 MESH 默认参数；读取优先级为 `temporary task override > site default > business template default > system default`。来源 `analysis_params_json` 是不可变的历史解析追溯，不参与新任务默认值或有效参数计算。保存使用原子替换，且不会改写来源或 parsed 数据库；创建报告/链路明细任务时会将完整规范化参数写入 Job options，后续修改局点默认不影响该任务。
- `link_time_window` 是唯一的切换稳定阈值：仅在有效 ACTIVE 物理身份确实从 A 变为 B 后，按 B 的连续有效持续时间分类，`duration >= link_time_window` 为正常切换，`duration < link_time_window` 为短时建链；首个 ACTIVE 区段和同一物理 AP/Radio 内未变更的区段都不是切换。`LinkCnt=0` 整帧无效快照在进入状态机前丢弃，`LinkCnt=2` 连续有效参与时长但仅作三角链路标记。统一链路模型默认基准时间 4000ms、切换阈值 10、维持链路 22、发现链路 4，建链信号阈值为 26，首个主链路忽略信号阈值。
- Excel/WPS 报告由 Export Process 生成，包含主链路建链顺序、链路明细、全部 ACTIVE RSSI/空口负载、单 AP 经过时段统计、切换事件和异常摘要；链路明细导出额外包含“分析参数”Sheet，嵌入图表硬上限 5,000 点，完整业务 Sheet 不截断。
- [轨道交通无线综合看板](RAIL_TRANSIT_WIRELESS_DASHBOARD.md) 只复用本服务的摘要和最近会话，不读取明细表、不触发重解析，正式分析详情仍由本页面承担。
