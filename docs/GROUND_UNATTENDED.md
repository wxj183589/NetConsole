# 轨道交通地面无人值守

## 定位

“轨道交通 / 地面无人值守”是独立一级页面，路由为
`/rail-transit/ground-unattended`，Feature key 为 `web.ground_unattended`。它不复用人工
“车载 MR 实时收集”页面的组件状态，也不把无人值守运行塞入单一 Online MR Session。

正式调用链为：

```text
Vue 独立页面
  -> /api/rail-transit/ground-unattended
  -> GroundUnattendedApplicationService
  -> Identity / Raw Query / Raw Data Lifecycle Service
  -> GroundUnattendedRepository / 受管文件 Adapter
  -> GroundUnattendedSupervisor（FastAPI lifespan，运行态编排）
  -> AC/基础资料/Online MR/fping
```

页面卸载只停止 Renderer 增量轮询。Electron 主窗口隐藏到通知区域时 Backend、AC 常驻轮询、全车长
Ping 和深度采集继续；明确退出时 lifespan 先关闭 Supervisor，Supervisor 请求 AC Poller 正常停止，
fping 进程仍由统一 `ShutdownManager` 登记和回收，Online MR Worker 继续使用既有
`LocalProcessAdapter` 进程树收口。
功能关闭时不创建无人值守 Repository 或 Supervisor；索引库初始化失败也只让本功能 API 返回结构化
`GROUND_UNATTENDED_UNAVAILABLE`，不会阻断人工 Online MR 或整个 Backend 启动。

WMESH Syslog 的 AP 展示身份统一通过 `ApIdentityQueryService` 查询。Current AP 和 WMESH old/new
端点都可能是物理 AP MAC、Radio MAC、BSSID 或已登记 alias，统一使用
`resolve_current_ap_macs(ap_role="trackside")` 做完整 48 位 MAC 精确解析；不使用名称、尾号、前缀、
SQL `LIKE` 或 MAC 偏移猜测。历史查询按当前页 distinct old/new MAC 单批预加载，并在同一请求内固定
Identity revision；实时 Receiver 缓存已经解析的 MAC，并以 Identity revision 为失效边界。实时记录
在既有 `parsed_details` 中保存 entity ID、revision、状态、来源和原因；历史原始 NDJSON 不改写，只在
读取投影中补充当前身份。Ground 不再从基础资料和 AC 明细建立第二套 AP/Radio/Alias 字典。

## 运行状态与查看上下文

`/status` 分开返回服务状态、活动运行、最近运行、活动操作和最近终态操作。没有活动运行时，页面只按
Profile 返回 `DISABLED` 或 `WAITING_WINDOW`；最近一次 `COMPLETED` 运行只出现在“最近运行”，不能
继续充当当前状态。`/operations/active` 只返回 `PENDING/RUNNING`，`/operations/latest` 只返回当前
局点最近的 `COMPLETED/FAILED`。完成操作提示在 12 秒内自动收起，失败操作保留到用户确认。

页面使用统一 `selectedRunId` 驱动 Ping、Syslog、时间轴和深度采集历史查看；运行选择器来自 `/runs`，
不会再隐式复用状态接口的 `run_id`。Ping 行仍以自身 `run_id/train_id/mr_id/target_ip` 为最高优先级，
避免历史汇总与当前运行曲线交叉。

Renderer 初次加载状态、运行列表、必要配置和当前页签；之后按类别增量刷新。活动运行的状态和健康最长
分别约 5 秒刷新，活动操作约 2 秒，列车/Ping/Syslog 约 8 秒且只在对应活动页签刷新；无活动运行时状态
约 20 秒刷新，归档、时间轴、深度采集和设置不做后台全量轮询。相同请求防重入并用
`AbortController`、请求代次和指数退避处理切页、隐藏、恢复和过期响应；页面隐藏时暂停请求，卸载时
取消请求、定时器和图表资源。活动长 Ping 浮窗另按约 1.8 秒调用增量接口，每次最多读取 200 个新点；
页面隐藏、用户暂停或历史运行不会继续轮询，恢复后使用原游标补拉缺失样本。

普通资料表继续使用 `NcDataTable.autoHeight`。时间轴和 Syslog 属于日志控制台，统一使用
`NcLogWorkspace + NcDataTable.fillRemainingHeight`：筛选、诊断、批量动作和分页固定占用自身高度，表格
区域使用 `flex: 1; min-height: 0` 填满余下空间，唯一主纵向滚动区为 `el-table` body。日志页不再叠加
`autoHeight/maxHeight/flex:1` 三套高度策略，也不硬编码单一分辨率高度。时间轴通过服务端
`page/page_size/query` 返回精确总数，默认每页 100；Syslog 常用筛选常驻，高级筛选折叠并显示条件数量。
设置页和其他普通内容页继续使用正常纵向页面滚动。

## 配置和时间窗口

配置按局点保存在 `ground_unattended_profiles`。默认值为：

- `schedule_start_time=07:00`、`schedule_end_time=23:00`、`timezone=Asia/Shanghai`；
- AC 轮询 10 秒，同 AP 静止阈值 10 分钟，AC 异常 Ping 宽限 120 秒；
- Ping 间隔 1000 ms、超时 4000 ms、包大小 64、每分片 12 个目标，每个目标激活后预热 10 秒；
- `ping_depot_trains_enabled=false`；默认不为车辆段、停车场或存车线列车增加 Ping 目标，避免升级后
  自动扩大目标范围；
- 最多 2 辆活动列车、4 台活动 MR、2 台启动中 MR、2 台最终化 MR；
- `deep_collection_master_enabled=true`；关闭后进入轻量监测模式，只保留 AC、Fleet Ping、
  UDP Syslog、WMESH 解析、位置判断和时间关联，不再启动新的 SSH 深度 MR 采集，已运行任务安全收尾；
- `syslog_auto_repair_enabled=true`；启动、新 Boot Session、MR 重新上线、手工检查和独立低频检查可补齐
  临时 Syslog Profile，关闭后检查保持只读；
- 深度采集最低/建议/最大时长为 10/20/30 分钟；
- 详细归档保留 30 天，轻量汇总保留 180 天。

第一阶段还增加了局点级 UDP 和高频写入参数：`udp_listen_host=0.0.0.0`、
`udp_listen_port=514`、有界接收队列 20,000、原始流每 100 条或 1 秒 flush、关键事件每 100
条或 1 秒批量提交。`syslog_server_ip` 默认留空，避免将 `0.0.0.0` 或监听地址错误下发到 MR；
只有配置为有效 IPv4 后，Supervisor 才会安排设备配置检查。

设置页通过 `/api/system/network/ipv4-addresses` 读取 Windows IP Helper 的本机 IPv4、网卡状态、
前缀、网关、路由 metric 和物理/虚拟属性，并分开配置“本机 UDP 监听地址”和“MR 日志回传地址”。
`0.0.0.0` 只允许用于监听，不能作为 MR 回传目标；保存和启动都会重新校验所选地址仍属于本机。
“检测到 MR 网络的推荐地址”只用 UDP `connect` 查询系统选路，不发送数据包；Windows UDP 端口检查
统一使用 IP Helper 只读读取 endpoint 表，不绑定被检查端口。运行概览的
`/syslog-transport-status` 还会优先识别 NetConsole 自身 Receiver，避免把正常监听误判为其他进程
占用。外部 NAT 地址必须启用
`allow_external_syslog_address` 并在本次保存中二次确认，后端同时记录高风险审计；普通无效、回环、
组播和广播地址始终拒绝。

开始和结束时间不能相同，支持 `22:00-06:00` 跨午夜窗口，运行日期取窗口开始日期。运行中保存
配置不会重启当前 fping 或 SSH 任务；`ac_poll_interval_seconds` 通过 Poller 控制文件热更新，
下一轮即使用新间隔且不重新登录 AC。`ping_depot_trains_enabled` 也在下一调度周期热更新：
`false -> true` 增量加入符合条件的场段 CT/CW，`true -> false` 平滑移除场段目标并保留已写入的
Ping 原始文件和汇总。其他配置保持当前 run 的既有冻结语义。状态接口同时返回下一次开始和结束时间。

首次运行前，“正线车辆”接口会从当前局点轨道交通基础资料聚合列车及 CT/CW 端点，因此无需先创建
无人值守 run 即可设置置顶。基础资料候选只表示“等待 AC 状态”，不会提前伪造正线资格或在线状态。

## 正线分类

`GroundUnattendedEligibilityClassifier` 组合当前局点：

Current AP 现场字段在基础资料未直接建立 AP 记录时，通过
`ApIdentityQueryService.resolve_current_ap_macs(ap_role="trackside")` 使用同一批次
Identity revision 进行精确解析。运行时 AP 只能由匹配的实体和物理 MAC 构造；
`ambiguous`/无效 MAC/缺少 alias 仍然不可获得正线或 Ping 资格。匹配证据、
Identity revision、站点状态和主线/Ping 排除原因以 `ap_identity_diagnostics_json` 保存。

- `main_path_code`；
- 站点 `node_type/path_code/participates_in_direction/track_facilities`；
- 区间 `section_kind/path_code`；
- 轨旁 AP 的稳定 ID、规范化 MAC、位置类型、站点、区间和结构化 metadata；
- `AcMeshLinkQueryService` 的 fresh/online、当前 AP 和本机接收时间。

位置解析分别保存原始 AP、解析后 AP、规范站点和匹配依据。AP 身份结论只有
`AP_EXACT/AP_REGISTRY/UNMATCHED`；`STATION_EXACT/STATION_ALIAS` 仅保留为站点文本诊断，不能授予
正线、Ping 或深采资格。身份匹配顺序为规范化 AP MAC、Radio/BSSID Registry MAC、稳定 AP ID；
AP 名称、显示别名和站点名称都不参与位置身份匹配。AC 上报的 AP MAC 完全未匹配轨旁 AP 资料时必须
返回 `UNKNOWN/AP_UNMATCHED`，即使名称或站点文本看起来属于正线或场段也不能获得资格。

已匹配的正式轨旁 AP 使用统一 `location_class`。AP 明确标记为
`DEPOT/PARKING_YARD/STABLING/DEPOT_CONNECTION/TEST_TRACK/NON_MAINLINE` 时按该特殊位置处理；
`UNKNOWN`/空值只表示 AP 层没有位置证据，必须继续使用已解析的站点、区间和主路径判断；站点属于
`MAIN + participates_in_direction` 时按正线处理，车辆段、停车场、存车线和明确非主路径仍按非正线处理。
已匹配 AP 在站点、区间和路径都没有特殊区域证据时使用 `DEFAULT_MAINLINE`，不得把 AP 层的
`UNKNOWN` 解释为非正线。只有 AP 未匹配、身份歧义或 MAC 无效时才保留 `UNKNOWN`。特殊位置与
`participates_in_mainline=true` 的冲突会在基础资料保存时阻断，历史冲突只读可见并保持失败关闭。

活动运行的 AP Location Classification 与 Mainline Decision 一次生成并作为单一事实源。列车列表、
详情、Ping 和深采调度共同消费 `location_class/location_class_source/participates_in_mainline`、
`mainline_*`、`ping_*`、`deep_collection_*`、`decision_revision/decision_source`，不再分别读取旧资格
字段推断位置。历史 schema 缺少该契约时只迁移已有资格证据的派生快照并标记
`LEGACY_ELIGIBILITY_SNAPSHOT`；原始 AC、Ping、Syslog 和 AP Identity 事实不重算、不改写。

分类结果不再用单一 `eligibility_status` 同时控制全部业务，而是独立返回：

- `mainline_eligible`：只控制正线车辆数量和覆盖率；
- `ping_eligible`：只控制 CT/CW 长 Ping 目标；
- `deep_collection_eligible`：只控制新的 Online MR SSH 深度采集。

正线 AP 对应列车计入正线并允许 Ping，深采继续受全局和单列车策略控制。车辆段、停车场和存车线列车
永不计入正线、永不深采；仅在 `ping_depot_trains_enabled=true` 时允许长 Ping。出入段线、试车线和
其他非正线目前不受该开关放行。`UNKNOWN/STALE`、查询失败和离线状态不启动新目标；已有 Ping 仍按
AC/离线宽限和下一轮调度平滑退出。

同一正线 AP 达到 `stationary_exclusion_minutes` 后返回 `MAINLINE_STATIONARY`：长 Ping 保持，
不启动新深采，已有自动深采走正常停止和既有最终化；AP 改变后计时清零并恢复深采资格。
存车线或其他位置切换也不会在分类瞬间直接杀死 Worker，目标增删统一交给下一调度周期处理。

## AC 轮询与长 Ping

无人值守 run 启动时，Supervisor 通过
`AcMeshLinkResidentPollingApplicationService` 为每台可连接控制器确保一个
`ac_mesh_link_resident_poll` Task。唯一键为 `site_id + run_id + controller_id`；每个 Task 在自己的
受控 Worker 进程内维持一个 SSH 会话，连接建立后执行一次 `screen-length disable`，随后立即采集并按
`ac_poll_interval_seconds` 在同一会话串行执行 `display clock` 和
`display wlan mesh-link ap`。单轮采集仍各自产生独立 snapshot/raw，Task 则覆盖整个无人值守 run，
不再每个周期新增任务或重新登录。

连接中断时 Poller 在同一 `task_id` 内进入 `RECONNECTING/BACKOFF`，按有界退避重新读取受控设备和
凭据后重连；每次新连接才重新执行一次 `screen-length disable`。解析或快照写入失败记录为单轮失败，
连接仍可用时不强制重连。Task 参数、控制文件、状态文件和任务中心均不保存用户名、密码或命令文本。

Supervisor 每秒以内读取各控制器最新快照，按 controller 独立维护
`last_processed_snapshot_id`，只在出现新 source snapshot 时追加无人值守索引和当日 AC JSONL；
联合分类仍使用每台 AC 的各自最新快照，不以全局最新一条覆盖其他控制器。没有新快照时只更新
freshness，不重复持久化同一来源。无人值守索引保存 AC 设备时间、本机接收时间、来源快照 ID、
列车/MR、端位、AP、站点、区间、里程、RSSI、freshness 和受控 raw 引用。

暂停或关闭深度采集总开关只阻止新的 Online MR 深采，AC Poller、长 Ping 和 Syslog 继续。已有常驻
Poller 时，AC 管理或列车在线的“立即刷新”只写入立即轮询请求，返回同一 resident `task_id` 和本次
`request_id` 并复用 SSH；没有常驻 Poller 时仍使用原 `ac_mesh_link_refresh` 一次性任务。

`fping_v5_runner` 保持 `target: str` 向后兼容，并增加 `targets`。`FleetPingSupervisor` 默认每进程
12 个目标，目标变化时保留不受影响的分片，先启动替换分片再停止旧分片。多目标 JSON 在实际二进制
不可用时，每个分片降级为一个有界单目标轮询进程，不会为每台 MR 无上限创建进程；页面和事件表会
显示降级警告。

目标生成按列车策略和端点事实逐项执行：`enabled=false` 取消全部资格；`monitor_only=true` 或
`deep_collection_enabled=false` 只取消深采，不影响 Ping；`priority` 只影响深采排序。CT、CW 分别按
在线状态和有效管理 IP 建立独立目标，缺少或非法 IP 返回明确原因；相同 `target_ip` 在同一目标集只加入
一次。场段 Ping 复用同一 `FleetPingSupervisor`、分片和 10 秒预热规则，不启动 iPerf、Online MR SSH
或 MR Syslog 配置下发，也不影响 AC 常驻会话。

运行概览分别返回 `mainline_ping_target_count`、`depot_ping_target_count` 和 `ping_target_count`；
列车/Ping 列表显示位置类型、Ping 纳入原因、是否正线和深采状态。场段目标只出现在长 Ping 视图，
不能伪装为正线车辆。

Ping 样本使用毫秒时间戳，按小时写入 `fleet_ping/*.jsonl`。索引库只保存分段元数据和 1 分钟、
5 分钟、AC 轮询窗口、AP 停留段、每日 MR/列车汇总。首次获得 AP 只建立当前位置基线，不伪装成
一次 AP 切换；后续真实 AP identity 变化才建立切换前后窗口。`GroundUnattendedTimelineCorrelator`
以本机接收时间关联最近 AC 快照；即使样本携带快照 ID，只要接收时间超出配置容差，丢包仍明确标记为
AC 位置未知，并继续识别 CT 单端、CW 单端和双端同时丢包。

每个 Ping 目标的激活时间按 `site_id/run_id/target_ip` 持久化。激活后的
`fleet_ping_warmup_seconds`（默认 10 秒）仍真实发包并写入 NDJSON，但记录
`warmup_ignored=true`，不计入有效发送、成功/丢失、RTT、连续丢包、告警、时间关联和汇总。
分片重建或 Backend 恢复同一 run 不重置激活时间；目标真正移除后重新加入才重新预热。原始样本同时
保存采样时的 AP identity/名称/MAC、站点、区间、里程、RSSI、AC 快照及接收时间、位置质量和
AP 切换上下文，历史查询不会把当前 AP 回填到旧样本。

Ping 曲线的黄色切换标记只来自索引库中持久化的真实
`MESH_ACTIVELINK_SWITCH`，周期 Ping 位置上下文和重复 `display wlan mesh-link` 状态采样都不生成
切换事件。重复 ingest 优先按 raw file/line 或事件 provenance 合并；真实
`A -> B -> A -> B` flap 全部保留。一次曲线查询用请求级 `GroundApDisplayResolver` 批量解析 old/new
Radio/BSSID Peer，固定同一 Identity revision，并按同 run、同 MR、同 CT/CW、同 AP、前后各 5 秒
关联真实 RSSI。RSSI 保留采集源数值语义，不自动补负号或插值。图形仅把同一自然秒的多条真实事件
聚合成 `AP 切换 xN`，底层事件不删除。

时间轴和 Ping 曲线共用 `GroundApDisplayResolver.project_switch()` 生成 canonical Switch 投影，统一
返回原始 old/new Peer、解析后的 AP ID/名称/物理 MAC、站点、区间、两端状态/来源/规则/原因和批次
revision。聚合状态明确区分 `BOTH_MATCHED`、`OLD_ONLY_MATCHED`、`NEW_ONLY_MATCHED`、
`BOTH_NOT_FOUND`、身份冲突、`INVALID_MAC` 与 `NO_AP_ENDPOINT`；任一端未解析或不存在都只影响展示，
不会丢弃真实 Switch。时间轴保留原始 Peer 切换并追加解析后的 AP/站点，Ping Tooltip 使用同一投影，
历史事件在查询时按当前可用 Identity 只读补全。

页面“长 Ping”保留内容自适应、超限内部滚动的汇总表，曲线不再占用列表下方空间。点击“查看曲线”
打开 Vue 内部非模态浮窗：没有遮罩，不锁定页面滚动，主页面仍可切换页签、筛选和查看其他列车；标题栏
可拖动，八个边/角可缩放，支持最大化、还原和关闭。同一时刻只保留一个浮窗，选择另一目标时复用窗口；
位置和尺寸按用户、路由和窗口 ID 保存到 Renderer 本地偏好，不写局点数据库。离开路由时释放
ECharts、`ResizeObserver`、pointer/resize/visibility 监听和请求资源。

首次打开通过受控的 `/ping-series` 查询逐包 RTT、成功/丢包、预热、位置未知、AP 切换和连续丢包
区段，并返回绑定运行、列车、MR、目标和预热选项的游标。当前活动运行默认最近 30 分钟，历史运行默认
实际起止时间，行级起止时间优先；页面也支持最近 5 分钟、1 小时、运行全部和自定义时间。首次点数默认
最多 3000，完整运行最多 10000 个降采样点；活动运行后续通过 `/ping-series/incremental` 按 OPEN
文件字节偏移增量读取，单次最多 200 点，服务端硬上限 500。前端按 `sample_id` 或
`target_ip + timestamp + sequence` 去重，按时间和序号重排，并维护 3000/10000 点环形缓存；丢包与
AP 切换标记优先保留。用户缩放后停止跟随最新，“回到实时”恢复滚动；ECharts 实例不因每批数据重建。

Ping 汇总同时返回 Backend 生成的 `query_identity`，其稳定身份为 `run_id + target_ip`。首次和增量查询
优先使用该身份；`target_ip` 在同一 run 内唯一时作为目标级强身份，历史 `train_id/mr_id/device_uuid`
别名只用于解析和诊断，不能再把目标 IP 已精确命中的样本排除。同一 run 内目标 IP 冲突明确返回
`PING_TARGET_IDENTITY_CONFLICT`，查询身份与参数不一致返回 `PING_IDENTITY_MISMATCH`。

2026-07-29 现场故障并非 ECharts 或 Backend 进程退出：原始点查询已经命中，但 raw point 中的
`site_id/automation_run_id/device_uuid/backend/raw_file_id` 等内部字段直接进入
`GroundPingSeriesDTO`，触发数千条 `extra_forbidden` 校验错误并返回 500。Application Service 现逐点
显式投影 `GroundPingSampleDTO`；Router 记录 `GROUND_PING_QUERY_STARTED/COMPLETED/FAILED`、
`request_id`、扫描/Registry/匹配量和完整 traceback，未知错误仍返回稳定 500 且不泄露物理路径。

后端先按 `run_id/data_type/train_id/device_uuid/mr_role/start_time/end_time` 在 Repository 预筛文件，
再逐行读取并优先保留丢包点。Ping 原始查询沿用最多 256 个文件、1,000,000 条扫描记录、256 MiB
解压/读取字节和 12 秒处理预算；Syslog 列表使用更严格的交互预算，达到预算返回 `truncated` 和扫描
诊断。逐包和 Syslog 分页仅保留当前请求页所需的有界最新记录，不把全天原始流一次加载到前端、进程
内存或 SQLite。列车筛选先把页面身份解析到 Registry 中唯一等价身份，再读取文件；记录级匹配继续使用
同一规范化规则，因此历史 `_07` 与页面“列车07”等同车异名不会再把真实 `ACTIVE_RAW` 错降级为
`SUMMARY_ONLY`。

## 第一阶段实时采集基础

`TrainInventorySyncService` 从现有 `RailTransitBaseDataQueryService` 增量聚合当前局点的车载
MR。设备主体、地址和凭据仍只存在于设备管理；无人值守只保存列车/端点绑定、启用、置顶、调度优先级、
深采开关、仅监测和备注。缺少 CT 或 CW 会保留列车并显示端点缺失；设备移除只标记绑定移除，既有策略和
历史不会被物理删除。

`SyslogUdpReceiver` 的接收线程只负责 `recv -> 本机接收时间/全局与来源序号 -> 有界队列`。独立处理
线程完成 MR 映射、WMESH/IFNET/CFGMAN 关键事件解析、状态投影、按小时追加和批量入库。原始 NDJSON 保留原始
字节的安全编码、原文、设备时间、接收时间、两个接收序号、来源 IP/端口、主机名和 facility/severity。
身份只有在来源 IP 与 hostname 同时指向同一 MR 时才是 `VERIFIED`；清单同步优先将设备 `system_name`
登记为 Syslog hostname，缺失时才使用显示名。单项唯一匹配仅标记未确认，冲突绝不绑定，未知来源写入独立
`_unidentified` 流。设备时间与本机接收时间的差为 `CLOCK_OFFSET`，突变才是
`CLOCK_JUMP`，它们不表示网络传输延迟。队列溢出、重复和来源问题均作为数据质量事件，而不是把无人值守
运行标成失败。

原始流均由 `RawStreamWriter` 单线程追加并登记：Ping 为
`active/<run_date>/fleet_ping/<train>/<CT|CW>/<date>/<hour>_<generation>.ndjson`，MR Syslog
为 `active/<run_date>/realtime/syslog/<train>/<CT|CW>/<date>/<hour>_<generation>.ndjson`。当前打开
文件不会被压缩；停止、轮转或重启恢复后才登记为关闭/恢复文件。SQLite 只保存分钟汇总、连续丢包区间、
结构化 Syslog 事件、射频运行状态、SNMP 关联、原始文件索引和健康事件，不保存高频 Ping 原文。

页面新增独立“Syslog 日志”标签，通过 `/syslog-records` 分页查看当前 OPEN、历史
CLOSED/RECOVERED 和 READY ZIP 中的真实接收内容。当前运行默认最近 30 分钟，历史运行默认完整运行
时段；每页默认 100、最多 500，支持列车、MR、CT/CW、来源 IP、设备系统名、facility、级别、身份状态、
WMESH/IFNET/CFGMAN 事件族、控制来源、射频状态、关联状态/置信度、AP、关键字和
ACTIVE/ARCHIVE 来源过滤。表格填充剩余视口并内部滚动，行详情展示完整原文、
接收序号、原始文件/行号、归档成员、设备/接收时间、时钟差、身份和解析字段。

已完成运行的 active Syslog 支持 `SELECTED/FILTERED/RUN_ALL` 三种服务端删除范围。页面只提交稳定记录
身份或筛选条件，先调用 `/syslog-delete-preview` 取得匹配数量、影响文件/派生事件、revision、阻断原因
和短期 token，再要求输入 `DELETE <run_date>` 或当前局点名；确认后只创建一个
`ground_syslog_delete` Job。活动/ERROR/停止/最终化/归档 run、OPEN 文件、READY/校验/下载归档、路径
不安全、文件缺失、锁超时和 revision 变化均阻断。READY ZIP 永不做记录级改写，只能使用既有整包归档
删除入口。

`GroundRawDataLifecycleService` 只对 Registry 登记且位于当前局点根内的
`CLOSED/RECOVERED/PENDING` NDJSON 工作：同目录写受控 `.part`，flush/fsync 后重算行数、大小、
SHA-256、起止时间，再用 `os.replace` 原子替换并在单一 SQLite 事务中更新 revision 和 provenance
派生数据。Registry 事务失败时由同目录备份恢复原文件；损坏单行原样保留。默认删除对应 WMESH 与
Syslog 时间轴事件；取消该选项时保留事件并标记 `source_deleted=true`。操作审计保存范围、数量、
前后 revision、阶段、任务号和失败码，不保存原始报文或凭据。

新 Syslog NDJSON 在写入时携带 WMESH/AP、IFNET 射频和 CFGMAN 来源字段。旧记录缺字段时在查询内存中只读重解析并标记
`display_enriched=true`，不会回写原始文件。查询仅解析 Repository 已登记且位于当前无人值守数据根内
的普通文件或受校验 ZIP 成员，拒绝路径逃逸、符号链接和目录联接。

三个 Syslog 来源严格分工：WMESH 只描述 Mesh 链路，IFNET 以 `WLAN-Radio*` 的真实 UP/DOWN 更新射频
状态，CFGMAN 只描述配置操作来源。`CommandSource=snmp` 的 CFGMAN 与同一 `device_uuid` 的 IFNET
事件按设备时间优先、接收时间降级进行双向关联：不超过 3 秒为 `HIGH`，大于 3 秒且不超过 10 秒为
`MEDIUM`，超过 10 秒不关联。单独 CFGMAN 仅显示“检测到 SNMP 配置变更”，不得推断接口或具体配置；
单独 IFNET 也不得强行归因于 SNMP。DOWN 到 UP 计算毫秒级中断，60 秒 3 次状态转换投影为
`FLAPPING`，5 分钟 3 次 SNMP 相关转换生成 `RADIO_SNMP_FLAPPING`。原始报文、去重后的结构化事件和
可重建状态投影分层保存，页面读取投影表，不扫描全部 NDJSON。

AP 展示解析先使用轨旁基础资料中的稳定 AP MAC、显式 Radio/BSSID 和唯一 Alias，再使用 AC Detail
中的显式 Radio/BSSID；H3C WMESH Peer MAC 与 AP MAC 的 Radio 前缀派生只能返回
`H3C_RADIO_DERIVED` 和 90 置信度，不能伪装成精确 BSSID。AC Detail 只读结果缓存 30 秒，避免 Syslog
自动刷新反复加载全量 FIT-AP。响应同时保存 `resolution_status/resolution_rule/confidence` 和
`display_name_source`；`AC_AP_NAME` 只表示 AC 当前配置名称，不等于轨旁工程点位名。多候选保持
`AMBIGUOUS`，主链路切换缺少旧或新 Peer 时分别显示“无主链路 → 新 AP”或“旧 AP → 无主链路”。

运行概览另有“UDP Syslog 与 MR 日志回传”状态区，由单一只读 DTO 返回保存的 MR 回传目标、地址是否
属于本机或已确认外部/NAT、本机监听地址、Receiver 状态、端口空闲/本进程监听/其他进程占用、目标端口
与监听端口是否一致、最近接收、活跃 MR、未识别来源、身份冲突、队列和丢弃数。推荐地址与网卡只展示，
不会自动覆盖 Profile；`NOT_LOCAL/EMPTY/INVALID` 阻止立即开始，`EXTERNAL_CONFIRMED` 允许启动但持续
显示风险。本状态查询不连接设备、不下发配置，也不启动 UDP Receiver。

Ping 稳定成功后，`MrSyslogConfigService` 通过既有设备凭据按
`display clock -> display version -> display clock` 连续取证。Boot Session 的主时间轴为两次设备
时钟中点减 uptime；同时保存设备时区、UTC offset、uptime 精度、估算误差、重启原因和本机
`checked_at`。设备时钟无法解析时才明确降级为 `LOCAL_FALLBACK` 并保存失败原因，不会静默冒充设备
时间。uptime 明显回退，或检查间隔内 uptime 已重置且估算上电时间越过容差时创建新 Session；只有设备
时钟因 NTP 跳变而 uptime 连续增长时保持原 Session，并记录 `CLOCK_JUMP`。

随后将 `display info-center` 作为运行态主检查，并以
`display current-configuration | include info-center` 补充验证来源规则，过滤不支持时才回退完整运行配置。
运行态必须确认 Information Center、loghost、实际目标 IP 和端口；`current-configuration` 只确认
`default deny`、WMESH、IFNET、CFGMAN 四条 source 规则。该固定临时 Profile 的
`managed_profile_version=2`。Comware 省略默认 `info-center enable` 或默认 UDP 514 的
显式配置行时，以 `display info-center` 的实际运行态为准，不会重复下发或误报失败。下发缺项后逐条检查
命令回显，再执行两层复查：完整才为 `CONFIG_SENT` 或 `CONFIG_REPAIRED`，
复查缺项为 `CONFIG_VERIFY_FAILED`，异常为 `CONFIG_FAILED`。只有双层验证成功后才可进入
`WAITING_FIRST_LOG`；仅已验证匹配的 UDP 才可进入 `LOG_ACTIVE`。审计证据保存配置前后输出、运行态前后
输出、按运行态/source 规则拆分的缺项、修复命令与校验时间；配置指纹由规范化运行态目标和 source 规则
生成，不依赖原始配置字符串。固定 H3C Profile 不会执行 `save`、`undo`、重启、删除或停止时回滚。
`display info-center` 还解析 loghost 和其他输出目的地的时间格式，以及独占或同行展示的缓冲计数。dropped
计数增长是日志数据质量告警；overwritten 增长仅表示设备本地环形缓冲覆盖，不等同于 UDP 网络丢包。旧目标的
`undo` 清理仍需真实设备命令验证后单独实现。

CFGMAN 接收路径不调用 `MrSyslogConfigService`、Supervisor 配置检查、SSH 或任何 info-center 命令。
Profile 完整性只由启动、新 Boot Session、MR 重新上线、用户手工检查和独立低频机制维护；禁止实现
`CFGMAN -> display info-center/current-configuration -> 漂移检查/自动修复`。NetConsole 自身配置
窗口内的非 SNMP CFGMAN 仅标记 `expected_internal_change` 并保留原始证据，SNMP 事件始终按外部变更处理。

运行态可同时返回多个不同 IP 的 loghost，省略端口统一为 514。NetConsole 只管理当前 Profile 指定的
IP/端口，保留其他 IP 的外部目标，不执行 `undo`。当前现场 H3C 版本以 IP 为 loghost 唯一键：同 IP
端口一致为 `TARGET_PRESENT`，IP 不存在为可安全补齐的 `TARGET_MISSING`，同 IP 已存在其他端口则为
`TARGET_PORT_CONFLICT`。冲突的自动检查不生成修复命令、不进入 `system-view`；只有用户在单台 MR
详情中明确二次确认后才允许改端口，并写入高风险授权与执行审计。配置指纹包含排序后的全部 loghost 和
当前 managed target，因此设备输出顺序变化不产生伪变更。

`ground_unattended` 索引库的 additive schema v10 包含列车清单/端点绑定/策略、boot session、Syslog
配置审计、结构化 Syslog 事件、`radio_interface_states`、`mr_runtime_states`、`radio_correlations`、
原始文件索引、Ping 丢包区间和健康事件表；新增 Profile 外部地址确认和自动补齐字段，以及
Boot Session 的前后设备时钟、估算误差、重启原因、设备时区、UTC offset、时间质量和时钟跳变证据。
本轮新增深采总开关、Ping 预热字段、目标激活表、运行控制操作表、raw file `revision` 和
`ground_unattended_delete_operations` 删除审计表；列车运行快照新增位置来源、正线参与标记、三类
资格原因码/文案和决策 revision/source。旧 `system` 或空时区迁移为
`Asia/Shanghai`，其他显式 IANA 时区保持不变。启动迁移为幂等加列与
`CREATE TABLE IF NOT EXISTS`，不重建既有局点数据库。

## 深度采集与覆盖

`DeepMrCollectionScheduler` 只构造强类型 `OnlineMrStartRequest`，底层继续使用
`OnlineMrApplicationService`、Job Center、原始命令、Session、正常停止、解析和原子 ZIP。无人值守
模板固定：terminal monitor、MESH、信道繁忙度、AP 射频统计、切换记录和接口速率开启；无线状态
默认关闭；会话级 fping 与 iPerf 均强制关闭。全车 Ping 不受深采轮换影响。

`OnlineMrConcurrencyPolicy` 统一设备互斥和活动/启动/最终化预算。人工任务不再受“整个局点只能有
一个任务”限制；同一 MR 仍只允许一个任务。自动调度先读取全部人工和自动 allocation，只使用剩余
资源，不停止人工任务。

局点级深采总开关位于单车 `deep_collection_enabled` 之上。总开关关闭时 Scheduler 仍同步和安全收尾
既有自动任务，但以 `paused` 方式跳过 `_fill_slots`，因此不会新增 Online MR 会话；单车开关只在总开关
开启时生效。轻量模式下深采数量为 0 是正常结果，归档汇总记录运行模式和未执行原因。

每日随机队列保存 seed、候选和稳定顺序。第一轮排序固定为：置顶未完成、从未采集、PARTIAL 补采、
采集次数少、持久随机顺序。只要仍有可采集列车未完成第一轮，已完成列车不会因 Ping 异常进入第二轮；
全部完成后才按置顶、次数、异常和随机顺序开始后续轮次。深度采集页直接复用同一排序函数展示每日
队列位置、当前调度优先级和选择原因，查询接口不会重新随机或改写队列。

资格刷新会把尚未产生结果的列车同步到 `WAITING/OFFLINE/EXCLUDED`；已经进入
`COLLECTING/PARTIAL/COVERED/FAILED` 的业务结果不会被普通 AC 状态刷新覆盖。

Session 只有满足最低时长、Mesh raw 存在且增长、最终化完成、正式包可用且完整性为 complete 时才
计为 `COVERED`；单端失败、时长不足、静止/离线、软件中断或最终化不完整为 `PARTIAL`，后续重新
符合条件时继续补采。

深采资格与 Collector 状态严格分离。`INELIGIBLE`、`ELIGIBLE`、`QUEUED` 只描述资格或调度位置；
创建 Online MR 会话但尚无任何 Collector 原始字节时为 `STARTING`。只有会话可读取且至少一个
Collector 已写入原始字节时才展示 `RUNNING`。`GET /deep-collections/records` 复用受管 Online MR
原始日志的 source/cursor 读取契约，按会话和分类返回有界增量；UI 的“暂停显示”只停止轮询与滚动，
不会停止后台 Collector，也不会把文件大小或当前分页行数伪装为记录总数。

深采记录在查询层按内容语义投影为 `WMESH/RSSI/RADIO/STATUS/RAW_OUTPUT`。WMESH 只接受解析成功的
链路状态或切换事件，RSSI 必须同时具有 MAC 和真实数值，Radio 只接受信道/接口/射频 telemetry，
Status 只接受明确生命周期或错误状态；命令回显、prompt、`display clock` 和时区文本只属于 raw。
过滤顺序固定为分类、关键词、时间排序、cursor/limit，cursor 同时绑定 Session、分类和关键词。
切换筛选会取消旧请求并清空列表；暂停后恢复继续使用原 cursor 补拉，不跳到最新。

列车详情的 CT/CW 会话按钮先用稳定 `collector_session_id` 查询现有 Online MR Session，再复用
`/rail-transit/online-mr-analysis?session_id=...` 工作区。活动和已结束 Session 均可打开；Session
缺失显示“会话不存在或已被清理”，其他失败显示结构化 error code 和 request ID。Browser 与 Electron
使用同一路由契约，不创建第二套 Session Viewer。

Ping 和深采浮窗 body 使用 `flex: 1; min-height: 0` 的真实可用空间。深采表格填满余下高度并仅在
table body 滚动；Ping 的 RTT 区为主要弹性区、逐包图和丢包表保留有界空间。ECharts 通过
`ResizeObserver + requestAnimationFrame` 响应最大化、恢复和 DPI 导致的容器变化，不依赖写死的
viewport 减法。

## 数据、归档和恢复

```text
files/rail_transit/ground_unattended/
├─ active/<run_date>/
├─ archives/<run_date>_ground_unattended.zip
└─ index.sqlite
```

每日结束先停止新调度，请求 AC Poller 正常停止并等待当前命令有界收口，再按配置限制深度任务最终化、
停止/flush Ping，最后生成 daily summary、覆盖 CSV、调度事件、错误、深度 Session 引用、完整 Ping
汇总 JSONL、每日 MR/列车汇总和 manifest。即使某类
当天无数据，ZIP 也保留 `fleet_ping/`、`ac_snapshots/`、`timeline/`、`ping_summaries/` 目录契约。
ZIP 先写隐藏临时文件，逐成员 CRC、manifest 和流式 SHA-256 校验后原子发布；索引先标记 READY，
之后才用白名单递归清理对应 `active/<run_date>`。任一步失败均显示“归档失败，原始数据仍保留”。
深度 Session ZIP 只引用、不嵌入每日 ZIP。

历史原始查询优先读取仍存在的 active 文件；active 已清理且归档为 READY 时，通过
`GroundArchiveReader` 直接流式读取 ZIP，不把归档解压回 active。同一运行同时存在 active 与 archive
时返回 `MIXED` 并按稳定接收/采样标识去重。读取前校验受管 archives 路径、登记大小、ZIP SHA-256、
manifest SHA-256、成员 SHA-256、CRC、成员数量、单成员/总解压量和压缩比；只读取 manifest 登记的
Ping/Syslog NDJSON。旧 ZIP 缺少 manifest 时只允许已登记的 `fleet_ping/`、`realtime/syslog/` 或
`syslog/` 成员，并标记 `legacy_archive`，不放宽路径规则。

归档详情提供概览、文件清单、Ping/Syslog 汇总、深度会话、完整性和保留策略七个页签；“重新校验”只读
检查现有 ZIP，不重写 READY 文件。ZIP 与汇总 JSON 使用两个明确按钮和严格 Artifact 端点：
`/artifacts/{archive_id}/download` 与 `/artifacts/{archive_id}/summary-download`。后端只按 opaque
`archive_id` 解析受管文件，Electron 再核对 endpoint、文件名、大小和 SHA-256；Renderer 不能提交物理
路径。

同一运行日的 READY 归档视为已封账：重复归档只校验既有 ZIP 并补做待完成的 active 清理，不重写正式
文件；已有活动 run 时“立即开始”幂等返回，已归档运行日则拒绝复用。若 READY 文件损坏且 active 已
不存在，索引标记失败并保留现场文件，不用空目录覆盖证据。详细保留和汇总清理均按 profile
`timezone` 的局点日期计算。

启动恢复会核对 RUNNING/STOPPING/FINALIZING/ARCHIVING，收口上次 OPEN Ping 分段，调用现有
Online MR mapping 恢复；窗口内恢复 Ping 与调度，并为每台控制器创建新的 resident Worker。旧
RUNNING Task 先按本地 Worker orphan 规则收敛，新 Task 延用按 run/controller 稳定生成的
`poll_session_id` 并记录 `ac_poller_recovered`，不会把陈旧任务当作活动 Poller。窗口外继续最终化和
归档。无法恢复的自动 operation 标记为 PARTIAL。BUILDING/FAILED 且 active 仍存在的归档会在下一次
Backend 启动重试。

详细保留到期只删除已校验正式归档及对应 AC/Ping 分段/事件/深采索引；每日汇总保留至
`summary_retention_days`。手工删除同样走 Supervisor 队列、明确确认和受管路径校验，正在使用的当日
数据拒绝删除。

普通停止和停止并归档均先创建持久化 `operation_id`，重复请求返回同一活动操作。操作记录保存阶段、
进度、消息、失败码、结果摘要和完成时间；页面刷新或 Backend 重启后分别从 `/operations/active` 和
`/operations/latest` 恢复。
停止流程包含 `STOPPING_AC_POLLER / 正在停止 AC 常驻轮询` 阶段。只有 AC Poller 已关闭 SSH 并退出、
深采安全收尾、全部 fping worker 退出、UDP 接收线程退出、原监听地址和端口可重新绑定、队列清空、
writer flush 且没有 OPEN 原始文件后才把 run 标记为 `COMPLETED`。Poller 超时会保存具体 controller、
task 和连接状态并执行有界进程树收口，操作以 `AC_POLLER_STOP_TIMEOUT` 失败，不伪装完成。停止并归档
继续显示准备、写入、校验、登记和 active 清理阶段；ZIP 失败时 run 已正常停止，但操作和 archive 为
失败，active 原始数据保留。

## API

前缀为 `/api/rail-transit/ground-unattended`：

```text
GET/PUT  /profile
GET      /status
GET      /syslog-transport-status
POST     /start | /pause | /resume | /stop | /stop-and-archive
POST     /inventory/sync | /config-check
GET      /health | /raw-files | /syslog-records
GET      /mr-runtime-status
GET      /runs
GET      /trains | /trains/{train_id}
PUT      /trains/{train_id}/priority
PUT      /trains/{train_id}/policy
GET      /ping-targets | /ping-summary | /ping-series | /ping-series/incremental
GET      /ping-samples | /timeline
GET      /deep-collections | /coverage
GET      /deep-collections/records
GET      /operations/active | /operations/latest | /operations/{operation_id}
GET      /archives | /archives/{archive_id} | /archives/{archive_id}/detail
POST     /archives/{archive_id}/verify
GET      /artifacts/{archive_id}/download
GET      /artifacts/{archive_id}/summary-download
POST     /archives/open-directory
DELETE   /archives/{archive_id}
```

写接口校验当前局点和 Pydantic 范围，返回结构化错误；停止、压缩、清理和归档由 Supervisor 执行，
不会在 Router 请求线程运行。

本机网络只读辅助接口使用 `/api/system/network`：

```text
GET  /ipv4-addresses
POST /recommend-source-ip
POST /check-udp-port
```

## 验证边界

自动测试覆盖时间窗口/跨午夜、同日手工停止抑制、配置持久化、结构化正线排除、静止恢复、多目标与
动态分片、逐目标 10 秒预热及恢复、逐包有界查询、轮转/汇总、CT/CW 错峰补齐、覆盖轮次去重、
首轮覆盖排序、可复现队列、ZIP 成功清理、
ZIP 失败保留、Repository 故障隔离、API 空态和前端七页签。第一阶段还覆盖清单增量同步/策略保留、
多 MR UDP 分流与未知来源隔离、设备时钟中点减 uptime、NTP 跳变保持 Session、本机地址校验、多 loghost
解析、历史 Syslog 分页、活动/最近操作分离、READY ZIP/混合来源查询、ZIP 路径/CRC/压缩比防护、时间轴
AP 展示、持久化停止操作、同 IP 端口冲突只读保护，以及不执行 `save/undo` 的 Syslog Profile。
场段 Ping 回归另覆盖开关默认值与持久化、运行期仅热更新该开关、车辆段/停车场/存车线三类位置、
正线/场段/未知三资格矩阵、CT/CW 独立在线和管理地址、单列车策略边界，以及 AP 名称和站点诊断不得
替代规范化 AP MAC 身份。
规模门覆盖 50,000 条 READY ZIP Ping、500,000 条 active Ping、100,000 条 Syslog、36 台 MR/30 天
Registry；前端假时钟覆盖 30 分钟页面轮询、10 分钟 Syslog 自动刷新和 100 次图表开关。
本轮另覆盖 `NcLogWorkspace`、日志表格填充剩余高度、时间轴服务端分页、非模态浮窗拖动与八向缩放、
位置恢复、单窗口目标复用、3000 点环形缓存、重复与乱序增量样本、Windows 只读 UDP endpoint 检查，
以及 Receiver 自身监听不误判占用。Syslog 删除测试覆盖选中/筛选/运行范围、活动/OPEN/READY 阻断、
路径穿越、锁超时、revision 冲突、原子重写/回滚、损坏行保留、派生 provenance 与 Job 审计。

Syslog 列表使用独立交互预算：最多 128 个候选文件、250,000 条记录、128MB 和 8 秒。无记录级筛选的
首屏按 Registry 结束时间从新到旧读取；当已取得所需页且下一个文件可证明更旧时提前结束，返回
`total_exact=false` 与 `diagnostics.optimized_latest_page=true`，总数使用本次候选文件登记值。旧记录缺少
WMESH 字段时，无解析字段筛选只对最终返回页解析；`event_type` 或 AP 名称/MAC 筛选才在预算内逐条解析。
单一 ACTIVE 或 ARCHIVE 查询不维护全局哈希集合；只有 MIXED 查询使用最多 250,000 个稳定去重键。
列车筛选复用统一列车身份归一化，兼容历史 Registry 中的 `_07` 与记录、页面中的“列车07”等同车异名。

Syslog 响应在 Application Service 显式投影 `GroundSyslogRecordDTO`，原始记录中的内部字节、局点 ID 和
设备数据库 ID 不进入 API。Router 为每次请求生成 `request_id`，记录开始、完成、失败、扫描量、来源、
截断和耗时；未知异常保存 traceback，向前端返回不含物理路径或堆栈的稳定 500，Backend 不退出。
公共 API Client 分开标记连接中断、连接重置、超时、Backend 重启、响应体读取失败、非法 JSON 和 HTTP
错误。Syslog 网络错误会立即复核 `/api/health`：复核成功显示查询连接中断但 Backend 在线，复核失败
才显示 Backend 无法连接。相同查询 fingerprint 复用在途请求，参数变化才取消；初次和自动加载只显示
页内错误，手动查询失败只 Toast 一次，恢复后清除错误并提示一次。历史运行默认关闭自动刷新，用户手动
开启时最小间隔为 30 秒。
`vue-tsc`、定向 Vitest、Electron 测试/类型检查和 Web/Main production build 作为提交门。

已完成一台 H3C MR 的 10 分钟真实 UDP 单机验证：Comware 省略默认 enable/514 配置文本时只读复查为
`CONFIG_PRESENT`，未进入配置视图；Receiver 实收 668 条并全部完成身份匹配和 WMESH 解析，队列无丢弃，
Boot Session 进入 `LOG_ACTIVE`，停止后原始文件已关闭登记。该结果只确认当前单台设备和现场样本，不能
外推为多列车压力、所有 Comware 版本或 IFNET 事件均已真实验证。

宁波地铁 12 号线 2026-07-28 数据已复制到隔离测试根做只读来源验证：READY ZIP 扫描 9708 条 Ping，
按稳定标识保留 9705 条唯一样本；6414 条 Syslog 可分页读取。7421 条时间轴中有 6330 条 WMESH 事件，
4381 条按 H3C Radio 规则映射、1929 条按显式 Radio/BSSID 映射、20 条为无新 Peer 的
`NO_ACTIVE_LINK`，未出现 `UNRESOLVED/AMBIGUOUS` 或“未知 AP”切换。现场 AC 配置名称仍全部为 MAC
形式，轨旁基础资料虽有点位编号但没有 AP/Radio MAC，因此本次只验证到唯一物理 AP；工程点位名称仍需
导入可信的 MAC 映射后验收。

2026-07-29 已完成运行的真实根只读核对确认：原请求实际命中原始点，DTO 对内部字段执行
`extra_forbidden` 才是 500 的直接原因；请求前后 Backend PID 未变化。隔离副本修复后，
列车03-CW/`10.122.3.250` 返回 420 条原始、410 条有效、0 条丢包，平均 RTT 约 43.162 ms；
列车07-CT/`10.122.7.249` 返回 419/409 条、27 条丢包，平均约 46.411 ms；
列车11-CW/`10.122.11.250` 返回 407/397 条、110 条丢包，平均约 50.030 ms。故意传入历史错误 MR UUID
时列车03-CW 仍由稳定目标身份返回相同结果。该核对未修改真实 Profile、SQLite、NDJSON 或 ZIP，也未
启动无人值守或 UDP Receiver；正式 Syslog 删除只在隔离副本执行。

同一来源复制到 `D:\NetConsoleTestData\ground-ping-log-layout-20260731-a1` 后，选中
`raw_41c8...` 的第 4 行完成一次正式删除：preview 命中 1 条原始记录、1 个 WMESH 和 1 个 Syslog
时间轴事件；Job 完成后文件记录数 264→263、revision 0→1，SHA-256/大小与 Registry 一致，
`integrity_check=ok`，4 个运行生命周期事件保留且无 `.part/.bak` 残留。真实根仅通过 SQLite
`mode=ro&immutable=1` 执行相同 preview；前后真实 index/NDJSON 的 SHA-256、大小和修改时间完全一致。

以下仍是人工现场门禁，不得由 fake 或本机回环测试提升为已验证：主备 AC 真实切换与设备时钟偏差、
十几小时持续多目标 fping、当前活动 run 的真实增量曲线、真实列车 AP 漫游、2 车/4 MR 并发 SSH、
Session 现场 ZIP、低磁盘故障注入、1366×768 与 Windows 125%/150% 缩放截图、Electron 隐藏到通知
区域后的整窗运行，以及退出后的 fping/Worker/SSH 进程核对。

逐项风险状态和剩余验证见 [地面无人值守风险审计](GROUND_UNATTENDED_RISK_AUDIT.md)。
