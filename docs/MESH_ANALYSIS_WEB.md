# Mesh 原始日志分析 Web 页面

## 定位

阶段 5C-8 在 `/rail-transit/mesh-analysis` 增加只读 Web 页面，Feature key 为 `web.mesh_analysis`。页面用于查看主程序已经持久化的离线 Mesh 分析结果，不承担导入、解析、重建、报告生成或删除。

```text
catalog.sqlite
  -> MR/mesh.sqlite 来源索引
  -> MR/parsed/<source>.mesh.sqlite
  -> GET-only Query Service
  -> Vue 分页与降采样展示
```

## 数据和规则

- 来源索引：`files/rail_transit/mr_raw_mesh/catalog.sqlite` 与每个 MR 根下 `mesh.sqlite`；
- 正式明细：每个来源对应的 `parsed/*.mesh.sqlite`，包含 `mesh_links`、`active_points`、`active_segments`、`switch_events`、`rssi_stats`、`diagnosis_events` 和 `parse_issues`；
- 主/备链路：直接读取 `mesh_links.link_state`，前端不根据当前 Active 数量推断备链；
- 短时建链、同 AP 双射频和乒乓：复用现有 `_active_build_order_rows_from_points` 和来源 `analysis_params_json`，不复制规则；
- RSSI：使用持久化统计和结构化采样。缺失值保持 `null`，已有真实 `0` 保持原值；
- 空口：读取结构化 Mesh 指标中的 Tx/Rx busy；没有持久化 CtlBusy 时返回 `null`，不从原始文本临时抓数字；
- fping/iPerf：只在存在同 MR 且时间重叠的 Online MR 解析会话时做内存只读对齐，并返回 `transient=true`，不保存为正式结果。

索引记录的旧绝对 `parsed_db_path` 随数据根迁移失效时，只允许在当前 MR 的 `parsed` 受控目录内按同名文件回退；不会回写索引。解析结果或 raw 缺失时显示明确 warning，不自动修复或重解析。

## API

全部业务接口为 GET-only：

```text
GET /api/rail-transit/mesh-analysis/summary
GET /api/rail-transit/mesh-analysis/sessions
GET /api/rail-transit/mesh-analysis/sessions/{session_id}
GET /api/rail-transit/mesh-analysis/sessions/{session_id}/links
GET /api/rail-transit/mesh-analysis/sessions/{session_id}/timeline
GET /api/rail-transit/mesh-analysis/sessions/{session_id}/switch-events
GET /api/rail-transit/mesh-analysis/sessions/{session_id}/rssi
GET /api/rail-transit/mesh-analysis/sessions/{session_id}/channel-busy
GET /api/rail-transit/mesh-analysis/sessions/{session_id}/anomalies
GET /api/rail-transit/mesh-analysis/sessions/{session_id}/ap-statistics
GET /api/rail-transit/mesh-analysis/sessions/{session_id}/alignment
GET /api/rail-transit/mesh-analysis/sessions/{session_id}/artifacts
GET /api/rail-transit/mesh-analysis/sessions/{session_id}/artifacts/{artifact_id}/download
GET /api/rail-transit/mesh-analysis/sessions/{session_id}/raw-sources
GET /api/rail-transit/mesh-analysis/sessions/{session_id}/raw-sources/{source_id}/tail
```

不存在 analyze、reparse、export、report、delete、start 或 stop 路由。

## 文件安全

报告和 raw 先由服务端在当前 MR 的 `raw/outputs` 受控目录枚举，再生成不可逆 `artifact_id/source_id`。下载和 tail 只接受该 ID，不接受相对路径、绝对路径、UNC 或 `..`；响应不包含本机绝对路径。压缩 raw 仅显示 metadata，不在请求线程在线解压 tail。

## 性能和生命周期

- 链路明细使用后端分页和时间/AP/MR 条件；
- 主链路时间线读取既有区间，不返回全部采样；
- RSSI 和空口由后端最多返回 2,000 个降采样点；
- 离线来源列表默认 30 秒刷新，连续失败三次降为 90 秒；
- 页面隐藏时不请求，组件卸载时清理 timer 和 ECharts；
- raw 只有用户明确点击且来源为普通文本时读取受控尾部。

## 当前边界

- Qt/Job Center 继续负责导入、重建、解析和报告；
- Web 不连接 AC、不控制 Agent、不开放 `executor=AGENT`，也不修改 Online MR 生命周期；
- 页面只展示现有正式资料匹配结果，不猜测 AP、站点、区间、里程或方向；
- Excel/WPS 导出不在本阶段新增，现有 XLSX/ZIP 仅作为 artifact 查看或下载。
