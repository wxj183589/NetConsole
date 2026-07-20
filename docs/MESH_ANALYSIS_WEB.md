# Mesh 原始日志分析 Web 页面

## 定位

当前 `/rail-transit/mesh-analysis` 是 Electron/Vue 的离线 MESH 分析工作台，Feature key 为 `web.mesh_analysis`。页面负责受控导入、来源匹配、重建任务、主链路建链顺序、链路明细、动态图和报告任务；原始日志、parsed SQLite 和 session ID 仍由 Python Core/Job/Export Process 管理，Vue 不实现解析或业务判定。

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
- 短时建链、同 AP 双射频和乒乓：复用现有 `_active_build_order_rows_from_points` 和来源 `analysis_params_json`，不复制规则；
- RSSI：使用持久化统计和结构化采样。缺失值保持 `null`，已有真实 `0` 保持原值；
- 空口：读取结构化 Mesh 指标中的 Tx/Rx busy；没有持久化 CtlBusy 时返回 `null`，不从原始文本临时抓数字；

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
GET /api/rail-transit/mesh-analysis/sessions/{session_id}/raw-sources
GET /api/rail-transit/mesh-analysis/sessions/{session_id}/raw-sources/{source_id}/tail
```

POST /api/rail-transit/mesh-analysis/import-context/prepare
POST /api/rail-transit/mesh-analysis/import-preview
POST /api/rail-transit/mesh-analysis/bundles/import
POST /api/rail-transit/mesh-analysis/sessions/{session_id}/rebuild
POST /api/rail-transit/mesh-analysis/sessions/{session_id}/report

不存在任意 SQL、任意命令或直接文件系统写入路由；长任务统一进入 Task Center，报告统一进入 Export Process。

## 文件安全

报告和 raw 先由服务端在当前 MR 的 `raw/outputs` 受控目录枚举，再生成不可逆 `artifact_id/source_id`。下载和 tail 只接受该 ID，不接受相对路径、绝对路径、UNC 或 `..`；响应不包含本机绝对路径。压缩 raw 仅显示 metadata，不在请求线程在线解压 tail。

## 性能和生命周期

- 链路明细使用后端分页和时间/AP/MR 条件；
- 主链路时间线读取既有区间，不返回全部采样；
- RSSI 和空口由后端按 Radio、时间窗口和目标点数查询，最多返回 2,000 个点；首尾、切换/异常/断点和极值按优先级保留，返回实际 `returned_points`；单 AP 支持指定区段或全部经过时段（段间断线）。
- 切换事件 payload 预载前后 AP、Peer 和建链区段，图表点击可回到建链顺序；ECharts 组件卸载时解除事件和释放实例。
- 离线来源列表默认 30 秒刷新，连续失败三次降为 90 秒；
- 页面隐藏时不请求，组件卸载时清理 timer 和 ECharts；
- raw 只有用户明确点击且来源为普通文本时读取受控尾部。

## 当前边界

- Job/Application Service 继续负责导入、重建、解析和报告；
- Web 不连接 AC、不控制 Agent、不开放 `executor=AGENT`，也不修改 Online MR 生命周期；
- 页面和报告共用 `MeshApLocationSnapshot`；无法唯一匹配 AP 时保持原始值和空归属，不猜测站点、区间、里程或方向。
- 报告对话框默认沿用来源快照；显式启用时可提交 typed 临时分析参数，优先级为 `temporary > source snapshot > site > default`，不会写回来源或局点配置。
- Excel/WPS 报告由 Export Process 生成，包含主链路建链顺序、链路明细、全部 ACTIVE RSSI/空口负载、单 AP 经过时段统计、切换事件和异常摘要；嵌入图表硬上限 5,000 点，完整业务 Sheet 不截断。
- [轨道交通无线综合看板](RAIL_TRANSIT_WIRELESS_DASHBOARD.md) 只复用本服务的摘要和最近会话，不读取明细表、不触发重解析，正式分析详情仍由本页面承担。
