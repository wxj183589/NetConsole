# 轨道交通 Qt → Electron 逐操作对等矩阵

## 结论

本矩阵以 `main@901e2529` 的 Qt 页面、Dialog、Widget、Worker、Application Service、Repository 与测试为事实源，记录分支 `codex/electron-rail-qt-parity-1to1` 的实际闭环。当前总状态是 `PARTIAL`，不是 `COMPLETE`：已经建立多个真实纵向链路，但仍有公共 Job/Artifact 契约依赖、Qt 操作缺口和真实设备边界。

正式调用链固定为：

```text
Electron → Vue → FastAPI Router → Application Service → Repository / 既有业务服务
```

Vue 不计算轨交业务规则，Router 不直接访问设备、数据库或文件。无线综合看板只是辅助聚合入口，不替代下列 Qt 独立业务。无线勘测和 SNMP Center 为 `EXCLUDED`，不迁移、不新增入口。

## Qt 事实源与 Electron 页面边界

| 业务边界 | Qt 事实源 | Electron 独立入口 | 状态 |
| --- | --- | --- | --- |
| 基础资料 | 正式设备库及轨交资料查询/导入规则；Qt 各业务页消费这些资料 | `/rail-transit/base-data` | `PARTIAL`（继承基线，本分支未改） |
| 在线列车与映射 | `VehicleMrOnlinePage`、查询/映射 Dialog、`vehicle_mr_online_worker.py` | `/rail-transit/train-online` | `PARTIAL` |
| 车内通信诊断 | `CarNetworkDiagnosticPage`、点表 Dialog、`car_network_diagnostic_worker.py` | `/rail-transit/car-network-diagnostic` | `PARTIAL` |
| 在线列车车地通信 | Qt 在线列车、轨旁 AP、Online MR 的 CT/TC 事实组合 | `/rail-transit/train-communication` | `PARTIAL` |
| 轨旁 AP 业务 | `TracksideApServicePage`、光衰 Worker、接口历史 Dialog | `/rail-transit/trackside-ap-business` | `PARTIAL` |
| 车载 MR 实时收集 | `OnlineMrCollectionPage`、采集/解析 Worker、Agent 包 Dialog | `/rail-transit/online-mr` | `PARTIAL` |
| 车载 MR 收集分析 | `OnlineMrCollectionAnalysisPage`、分析图表 Widget | `/rail-transit/online-mr-analysis` | `PARTIAL` |
| MR 原始 MESH 日志分析 | `MeshLogAnalysisPage`、分析参数/Peer 明细/报告 Dialog、导入 Worker | `/rail-transit/mesh-analysis` | `PARTIAL` |

## 逐入口、逐按钮与异常恢复矩阵

| Qt 有效入口/操作 | Electron 实际闭环 | 状态与证据/缺口 |
| --- | --- | --- |
| 基础资料总览、站点、区间、轨旁 AP、列车、MR、关系、质量问题 | 现有基础资料 Query Service → Router → `RailTransitBaseDataView` | 已有真实查询；本分支未复验全部 Qt 消费场景，`PARTIAL` |
| 基础资料导入预览、合并确认、正式应用、历史和回滚 | 现有 Import Service、写入 Guard、审计与回滚 API | 已有受控写链；仍需 Electron 人工对照，`PARTIAL` |
| 在线列车查询/重置、CT/TC 当前 AP、站点、方向、RSSI、状态原因、历史 | `VehicleMrOnlineQueryService` → Router → `VehicleMrOnlineView` | 真实持久数据查询、loading/error/success/empty 完成 |
| 在线列车“刷新全部” | 复用已注册 `vehicle_mr_online_refresh_all` Task；可取消、重启恢复 | 真实 Task 完成 |
| 在线列车“刷新 AP 映射” | 复用已注册 `vehicle_mr_ap_mapping_refresh` Task；支持按列车刷新、取消、恢复 | 真实 Task 完成 |
| 映射管理新增、删除、保存 | DTO → Application Service → 已注册 `vehicle_mr_mapping_save` Task | 真实持久化 Task 完成 |
| 在线列车连续采集“开始/停止” | 尚无 Electron Application Service/Job 闭环 | 缺口：需抽取 Qt Worker 生命周期，不能由定时刷新代替 |
| 在线列车结果导出、映射导入、模板导出 | 尚无 Electron Export Process/受控文件导入闭环 | 缺口 |
| 车内通信“刷新” | 查询正式列车和既有诊断结果 | 真实查询完成 |
| 车内通信“开始检测/取消检测” | 选中正式列车后创建 `car_network_diagnostic` Task；Job 调用既有 `CarNetworkDiagnosticService`；支持轮询、取消、恢复、结果 DTO | 业务链已实现；公共 handler 尚未注册，Feature 执行开关保持关闭，不能交付执行态 |
| 车内通信节点详情、结果状态与异常 | Electron 独立页面展示 Task 结果、失败和空状态 | 已实现；待 handler 后做真实执行验收 |
| 车内点表导入/导出、打开点表、锁定、增删、地址映射、从设备生成、全局规则保存/应用/覆盖/恢复 | 尚无完整 Electron Application Service、受控文件与 Export Process 闭环 | Qt 有效功能缺口 |
| 在线列车车地通信 CT/TC、当前轨旁 AP、RSSI、fping RTT/丢包、iPerf、光衰异常、任务、包和 raw tail | `TrainCommunicationQueryService` → Router → `TrainCommunicationView`；复用既有状态与阈值 | 真实查询和降级状态完成；未新增阈值或名称猜测 |
| 车地通信进入 Online MR 实时收集/分析 | 独立 `/online-mr` 与 `/online-mr-analysis` 页面 | 已拆分，不由只读看板替代 |
| 轨旁 AP 查询、筛选、分页、当前 AP/光衰、异常 | `TracksideApBusinessQueryService` 复用 `load_trackside_ap_business_snapshot` 与 `trackside_row_status` | 真实查询完成，无新光衰阈值 |
| 轨旁 AP 轻量更新：全部/站点/AP、取消、失败与恢复 | `trackside_ap_optical_update` Task 调用既有 `collect_trackside_optical`，保留持久化和部分失败 | 业务链已实现；公共 handler 尚未注册，Feature 动作开关保持关闭 |
| 轨旁 AP“全量更新” | Electron 尚未串联 Qt 的交换机详情预检、AC FIT-AP 刷新和光衰更新 | 缺口：需抽取独立 Application Service/Job，不能复制 Qt QThread 业务 |
| 轨旁 AP 导出/取消导出 | 尚无公共 Artifact source/ExportJob 授权 | 公共 Artifact 契约阻塞 |
| 轨旁接口历史、设备详情、AP 详情 | Electron 当前表格已给出核心字段，未形成三个独立详情动作 | Qt 交互缺口 |
| Online MR 配置、prepare/start、LOCAL SSH、实时 Collector 日志和指标 | `OnlineMrWebControlService` 只接收正式 MR/设备/采集参数，凭据由后端资料解析；正式 Electron Runtime 显式启用本地控制 | 真实 Application Service 链完成；无凭据、命令、路径透传 |
| fping/iPerf 配置与运行结果 | 复用既有 `FpingConfig`、Traffic/Online MR 状态机；页面展示 RTT、丢包、吞吐等既有指标 | 契约测试完成；真实工具/设备待现场 |
| 正常停止、超时停止、LOCAL 强停、停止全部、重启 reconcile/recover | stop/force-stop/recover API 调用既有 Application Service；强停保留 raw 并标记 partial | LOCAL 链完成；AGENT 仍只有正常停止，无强停契约 |
| finalize、ZIP/Artifact、partial/failure | 复用既有 metadata、原子打包、Mapping/Session/Task 终态；分析页可交付 Artifact | 自动化完成；真实设备待验收 |
| Online MR Agent start/status/normal stop 与包导入 | 消费既有 Agent Executor/Profile/Package 契约 | 既有闭环；真实 Agent 待验收，不以 Fake 代替 |
| 添加/清空采集备注 | Electron 未提供备注写入动作 | Qt 有效功能缺口 |
| 检测 iPerf 服务端、运行中重试 iPerf | Electron 当前仅消费既有运行结果 | Qt 有效功能缺口 |
| 解析/强制重解析/取消解析、打开会话目录、Agent 包管理 | 查询、报告和 Artifact 已有；这些独立按钮尚未全部对等 | Qt 有效功能缺口，目录动作需白名单 Native Bridge |
| Online MR 分析指标、时间线、报告生成/取消/恢复/下载 | Query Service + Export Process + Artifact → `OnlineMrAnalysisView` | 真实闭环完成 |
| MESH 新建 MR Profile | DTO → Application Service → 既有 `MeshStorageService`，可绑定正式 MR | 真实持久化完成 |
| MESH 导入文件/目录、取消、失败与重启恢复 | 浏览器只上传文件和 `mr_id`；后端从正式 Profile 派生安全目录/相对引用；复用已注册 `mesh_log_import` Job | 真实导入 Task 完成，不接受客户端路径和身份字段 |
| MESH 链路、时间线、切换、RSSI、Channel Busy、异常、AP 统计、对齐、raw tail | `MeshAnalysisQueryService` → Router → 独立分析页 | 真实 SQLite 只读查询完成 |
| MESH 正式报告生成/取消/恢复/Artifact 下载 | 既有 Export Process → Artifact | 真实闭环完成 |
| MESH 分析参数及持久化、导出链路明细/取消、打开目录、完整 Active 图 | 尚未对等 | Qt 有效功能缺口 |
| MESH 源文件菜单：显示单文件/全部、复制路径、删除源文件、删除解析数据、全部删除 | 当前可查询源文件和 raw tail；本机动作与三种破坏性删除尚未建设 | Qt 有效功能缺口；删除必须新增受控 Application Service 并保留审计/确认 |

## 公共单写依赖

本分支遵守公共 Task/Artifact/Native Bridge 单写约束，没有复制第二套实现，也没有修改这些公共文件。要解锁已写好的业务链，公共基础设施分支需提供最小改动：

1. 在 `src/netconsole/services/job_center/handlers/rail_transit_jobs.py` 导入并绑定 `run_car_network_diagnostic`、`run_trackside_ap_optical_update`，将 `car_network_diagnostic`、`trackside_ap_optical_update` 加入既有 `HANDLERS`。
2. 在公共 Artifact source root/授权表中增加轨旁 AP 业务报告来源，并授权 `web_export_trackside_ap_business` 消费既有 `ExportJob(job_type="trackside_ap_business")`；不得在轨交模块复制 Artifact Store。
3. 车内点表、在线列车导入导出、Online MR 本机目录和 MESH 本机目录动作如需 Electron 文件能力，必须扩展现有白名单 Native Bridge 契约；不得暴露任意路径或任意程序执行。

## 自动验证与真实设备边界

定向自动化覆盖 Router → Application Service → Job/Export 契约、取消/恢复、持久化、安全 DTO、Vue 状态和 Electron Runtime 开关。未连接真实列车、MR、AC 或 Agent，未使用真实凭据。因此 SSH、fping/iPerf、AC 采集、光衰采集、Agent 包收敛和真实 ZIP 内容均标记 `REAL_DEVICE_PENDING`。这只是现场边界，不会把尚有 Qt 功能缺口的模块升级为 `REAL_DEVICE_PENDING` 或 `COMPLETE`。

在本矩阵所有 `缺口` 清零、公共依赖合入、组合自动化通过、Qt/Electron 人工逐项对照完成且真实设备验收通过前，Qt 对应页面继续保留为事实源与回退入口。
