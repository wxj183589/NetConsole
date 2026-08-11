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
- AP 覆盖核查：来源列表勾选恰好两个当前局点来源后运行 `capability.mesh.coverage_audit`。服务端直接聚合两个 parsed SQLite 的有效 `ACTIVE/STANDBY`（`LinkCnt>0`）；优先用 remap 已持久化的 `canonical_ap_mac`（兼容 `peer_ap_mac`）归并物理 AP，不会再次把已匹配 AP 降级为 Peer Radio MAC 重新解析。只有旧 parsed 库缺少物理 MAC 投影时才走只读 Identity fallback；索引未就绪则返回“AP Identity 索引不可用”，而非把全部观测列为资料未匹配。每个局点独立数据库的 Identity scope 均为 `current`，与 MESH remap 一致。结果页和 Excel 摘要显示来源级、全集 Peer Radio/物理 AP 去重数及持久化/fallback 诊断；不在 Vue 去重，不重新扫描 raw 日志。核查默认按已观测站点/区间的正线范围，并同时提供全正线计数；未观测不代表故障。

索引记录的旧绝对 `parsed_db_path` 随数据根迁移失效时，只允许在当前 MR 的 `parsed` 受控目录内按同名文件回退；不会回写索引。解析结果或 raw 缺失时显示明确 warning，不自动修复或重解析。

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
- RSSI 和空口由后端按 Radio、时间窗口和目标点数查询，最多返回 2,000 个点；首尾、切换/异常/断点和极值按优先级保留，返回实际 `returned_points`；单 AP 支持指定区段或全部经过时段（段间断线）。
- 切换事件 payload 预载前后 AP、Peer 和建链区段，图表点击可回到建链顺序；ECharts 仅在活动 Tab 且容器宽高有效时初始化，激活、数据变化和 ResizeObserver 触发 RAF resize，卸载时取消 RAF、解除事件并释放实例。
- 离线来源列表默认 30 秒刷新，连续失败三次降为 90 秒；
- 页面隐藏时不请求，组件卸载时清理 timer 和 ECharts；
- raw 只有用户明确点击且来源为普通文本时读取受控尾部。
- 页面内任务区域只显示任务名、状态、紧凑进度和一行摘要；完整日志、结果、Artifact、错误和停止操作统一进入 Task Center。刷新页面只恢复活动态或失败态 MESH 任务，不自动展开旧 COMPLETED 任务。

## 当前边界

- Job/Application Service 继续负责导入、重建、解析和报告；
- Web 不连接 AC、不控制 Agent、不开放 `executor=AGENT`，也不修改 Online MR 生命周期；
- 页面和报告共用 `MeshApLocationSnapshot`；候选同时读取 FIT-AP 与独立轨旁 AP 基础资料，优先按规范化 AP MAC 匹配，不要求存在 AC、FIT-AP 或交换机资料。匹配成功后返回点位编号、AP 名称、站点、区间起终点、方向和里程；基础 AP 名称为空时回退点位编号。无法唯一匹配 AP 时保持原始值和空归属，不猜测站点、区间、里程或方向。
- 报告和链路明细弹窗每次打开都从当前局点上下文 ID 读取同一份 `site_meta.json` 中的完整 MESH 默认参数；读取优先级为 `temporary task override > site default > business template default > system default`。来源 `analysis_params_json` 是不可变的历史解析追溯，不参与新任务默认值或有效参数计算。保存使用原子替换，且不会改写来源或 parsed 数据库；创建报告/链路明细任务时会将完整规范化参数写入 Job options，后续修改局点默认不影响该任务。
- `link_time_window` 是唯一的切换稳定阈值：仅在有效 ACTIVE 物理身份确实从 A 变为 B 后，按 B 的连续有效持续时间分类，`duration >= link_time_window` 为正常切换，`duration < link_time_window` 为短时建链；首个 ACTIVE 区段和同一物理 AP/Radio 内未变更的区段都不是切换。`LinkCnt=0` 整帧无效快照在进入状态机前丢弃，`LinkCnt=2` 连续有效参与时长但仅作三角链路标记。统一链路模型默认基准时间 4000ms、切换阈值 10、维持链路 22、发现链路 4，建链信号阈值为 26，首个主链路忽略信号阈值。
- Excel/WPS 报告由 Export Process 生成，包含主链路建链顺序、链路明细、全部 ACTIVE RSSI/空口负载、单 AP 经过时段统计、切换事件和异常摘要；链路明细导出额外包含“分析参数”Sheet，嵌入图表硬上限 5,000 点，完整业务 Sheet 不截断。
- [轨道交通无线综合看板](RAIL_TRANSIT_WIRELESS_DASHBOARD.md) 只复用本服务的摘要和最近会话，不读取明细表、不触发重解析，正式分析详情仍由本页面承担。
