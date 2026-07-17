# 轨道交通 Qt → Electron 逐操作对等矩阵

## 结论

本矩阵以 `main@901e2529` 的 Qt 页面、Dialog、Widget、Worker、Application Service、Repository 与测试为事实源，记录累计集成分支 `codex/electron-parity-integration` 的实际闭环。当前总状态是 `PARTIAL / IMPLEMENTED_UNVERIFIED`，不是 `COMPLETE`：共享轨交 Job handler 和统一任务窗口已经接通，多个真实纵向链路已实现，但仍有 Qt 操作缺口、Electron 人工对照和真实设备验收边界。

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
| 在线列车连续采集“开始/停止” | `vehicle_mr_online_collection_start` Task 复用正式采集器；正常停止走业务停止入口，通用取消/日志/恢复进入统一任务窗口 | 真实 Job 闭环完成；真实 MR 待验收 |
| 在线列车结果导出、映射导入、模板导出 | 受控导入预览/重复策略/保存与 Export Process Artifact 已接入；保存文件由 Electron 任务窗口处理 | 真实闭环完成；待 Electron 文件对话框人工验收 |
| 车内通信“刷新” | 查询正式列车和既有诊断结果 | 真实查询完成 |
| 车内通信“开始检测/取消检测” | 选中正式列车后创建已注册的 `car_network_diagnostic` Task；Job 调用既有 `CarNetworkDiagnosticService`；通用取消、日志与恢复进入统一任务窗口 | 真实业务链已实现；Feature 执行开关默认关闭，真实设备验收后再开放默认值 |
| 车内通信节点详情、结果状态与异常 | Electron 独立页面展示 Task 结果、失败和空状态 | 自动化完成；真实执行待验收 |
| 车内点表导入/导出、打开点表、锁定、增删、地址映射、从设备生成、全局规则保存/应用/覆盖/恢复 | DTO → Application Service → Repository/Export Process；导入先预览，重复策略显式选择，任务状态进入统一任务窗口 | 真实闭环完成；待 Electron 人工逐操作对照 |
| 在线列车车地通信 CT/TC、当前轨旁 AP、RSSI、fping RTT/丢包、iPerf、光衰异常、任务、包和 raw tail | `TrainCommunicationQueryService` → Router → `TrainCommunicationView`；复用既有状态与阈值 | 真实查询和降级状态完成；未新增阈值或名称猜测 |
| 车地通信进入 Online MR 实时收集/分析 | 独立 `/online-mr` 与 `/online-mr-analysis` 页面 | 已拆分，不由只读看板替代 |
| 轨旁 AP 查询、筛选、分页、当前 AP/光衰、异常 | `TracksideApBusinessQueryService` 复用 `load_trackside_ap_business_snapshot` 与 `trackside_row_status` | 真实查询完成，无新光衰阈值 |
| 轨旁 AP 轻量更新：全部/站点/AP、取消、失败与恢复 | 已注册的 `trackside_ap_optical_update` Task 调用既有 `collect_trackside_optical`，保留持久化和部分失败；通用任务操作进入统一任务窗口 | 真实业务链已实现；Feature 动作开关默认关闭，真实设备待验收 |
| 轨旁 AP“全量更新” | Electron 尚未串联 Qt 的交换机详情预检、AC FIT-AP 刷新和光衰更新 | 缺口：需抽取独立 Application Service/Job，不能复制 Qt QThread 业务 |
| 轨旁 AP 导出/取消导出 | 尚无公共 Artifact source/ExportJob 授权 | 公共 Artifact 契约阻塞 |
| 轨旁接口历史、设备详情、AP 详情 | Electron 当前表格已给出核心字段，未形成三个独立详情动作 | Qt 交互缺口 |
| Online MR 配置、prepare/start、LOCAL SSH、实时 Collector 日志和指标 | `OnlineMrWebControlService` 只接收正式 MR/设备/采集参数，凭据由后端资料解析；正式 Electron Runtime 显式启用本地控制 | 真实 Application Service 链完成；无凭据、命令、路径透传 |
| fping/iPerf 配置与运行结果 | 复用既有 `FpingConfig`、Traffic/Online MR 状态机；页面展示 RTT、丢包、吞吐等既有指标 | 契约测试完成；真实工具/设备待现场 |
| 正常停止、超时停止、LOCAL 强停、停止全部、重启 reconcile/recover | stop/force-stop/recover API 调用既有 Application Service；强停保留 raw 并标记 partial | LOCAL 链完成；AGENT 仍只有正常停止，无强停契约 |
| finalize、ZIP/Artifact、partial/failure | 复用既有 metadata、原子打包、Mapping/Session/Task 终态；分析页可交付 Artifact | 自动化完成；真实设备待验收 |
| Online MR Agent start/status/normal stop 与包导入 | 消费既有 Agent Executor/Profile/Package 契约 | 既有闭环；真实 Agent 待验收，不以 Fake 代替 |
| 添加采集备注 | 备注 DTO → `RailTransitWebApplicationService.add_online_mr_note`；只允许当前受控会话根目录内的普通文件，固定 Electron 审计来源 | 真实追加与审计完成，不接受客户端伪造来源/动作；“清空全部备注”未提供破坏性快捷动作 |
| 检测 iPerf 服务端、运行中重试 iPerf | Electron 当前仅消费既有运行结果 | Qt 有效功能缺口 |
| 解析/强制重解析/取消解析 | `start_online_mr_parse` 创建正式解析 Job；普通/强制模式显式区分，原始 raw 不删除；取消、日志、恢复和 Artifact 进入统一任务窗口 | 真实闭环完成 |
| 打开会话目录、Agent 包管理 | Agent 管理已有独立入口；Online MR 页面尚未完成 Qt 的会话目录快捷动作和包管理快捷入口 | Qt 交互缺口，目录动作需白名单 Native Bridge |
| Online MR 分析指标、时间线、报告生成/取消/恢复/下载 | Query Service + Export Process + Artifact → `OnlineMrAnalysisView` | 真实闭环完成 |
| MESH 新建 MR Profile | DTO → Application Service → 既有 `MeshStorageService`，可绑定正式 MR | 真实持久化完成 |
| MESH 导入文件/目录、取消、失败与重启恢复 | 浏览器只上传文件和 `mr_id`；后端从正式 Profile 派生安全目录/相对引用；复用已注册 `mesh_log_import` Job | 真实导入 Task 完成，不接受客户端路径和身份字段 |
| MESH 链路、时间线、切换、RSSI、Channel Busy、异常、AP 统计、对齐、raw tail | `MeshAnalysisQueryService` → Router → 独立分析页 | 真实 SQLite 只读查询完成 |
| MESH 正式报告生成/取消/恢复/Artifact 下载 | 既有 Export Process → Artifact；活动任务的取消/日志/报告保存进入统一任务窗口，历史 Artifact 仍可从业务页受控下载 | 真实闭环完成 |
| MESH 分析参数及持久化、导出链路明细/取消、打开目录、完整 Active 图 | 尚未对等 | Qt 有效功能缺口 |
| MESH 源文件菜单：显示单文件/全部、复制路径、删除源文件、删除解析数据、全部删除 | 当前可查询源文件和 raw tail；本机动作与三种破坏性删除尚未建设 | Qt 有效功能缺口；删除必须新增受控 Application Service 并保留审计/确认 |

## 公共单写依赖

累计集成分支继续复用唯一 Task Center、Artifact Store 和白名单 Native Bridge，没有复制第二套任务或文件系统模型：

1. `car_network_diagnostic`、`trackside_ap_optical_update` 和 `vehicle_mr_online_collection_start` 已加入既有轨交 handler 注册表。
2. Job Center 已支持 `rail` 模块筛选和正式轨交 owner 的取消；Electron 主/预加载进程只允许白名单 `rail` 任务窗口上下文。
3. 活动任务的停止、日志、恢复和 Artifact 保存统一进入 Electron 任务窗口；业务页只保留结果摘要和历史业务 Artifact。
4. 轨旁 AP 业务报告仍需接入公共 Artifact source；Online MR/MESH 本机目录动作仍需扩展既有白名单 Native Bridge，禁止暴露任意路径或任意程序执行。

## 自动验证与真实设备边界

定向自动化覆盖 Router → Application Service → Job/Export 契约、取消/恢复、持久化、安全 DTO、Vue 状态和 Electron Runtime 开关；累计分支当前轨交后端定向测试 `85 passed`、Vue 全量 `134 passed`、Electron 全量 `68 passed`，Vue/Electron 构建通过。未连接真实列车、MR、AC 或 Agent，未使用真实凭据。因此 SSH、fping/iPerf、AC 采集、光衰采集、Agent 包收敛和真实 ZIP 内容均标记 `REAL_DEVICE_PENDING`。这只是现场边界，不会把尚有 Qt 功能缺口的模块升级为 `COMPLETE`。

在本矩阵所有 `缺口` 清零、公共依赖合入、组合自动化通过、Qt/Electron 人工逐项对照完成且真实设备验收通过前，Qt 对应页面继续保留为事实源与回退入口。
