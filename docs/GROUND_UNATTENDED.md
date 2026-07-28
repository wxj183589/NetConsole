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
  -> GroundUnattendedSupervisor（FastAPI lifespan）
  -> AC/基础资料/Online MR/fping/Repository
```

页面卸载只停止 5 秒 REST 轮询。Electron 主窗口隐藏到通知区域时 Backend、AC 轮询、全车长
Ping 和深度采集继续；明确退出时 lifespan 先关闭 Supervisor，fping 进程仍由统一
`ShutdownManager` 登记和回收，Online MR Worker 继续使用既有 `LocalProcessAdapter` 进程树收口。
功能关闭时不创建无人值守 Repository 或 Supervisor；索引库初始化失败也只让本功能 API 返回结构化
`GROUND_UNATTENDED_UNAVAILABLE`，不会阻断人工 Online MR 或整个 Backend 启动。

## 配置和时间窗口

配置按局点保存在 `ground_unattended_profiles`。默认值为：

- `schedule_start_time=07:00`、`schedule_end_time=23:00`、`timezone=Asia/Shanghai`；
- AC 轮询 10 秒，同 AP 静止阈值 10 分钟，AC 异常 Ping 宽限 120 秒；
- Ping 间隔 1000 ms、超时 4000 ms、包大小 64、每分片 12 个目标，每个目标激活后预热 10 秒；
- 最多 2 辆活动列车、4 台活动 MR、2 台启动中 MR、2 台最终化 MR；
- `deep_collection_master_enabled=true`；关闭后进入轻量监测模式，只保留 AC、Fleet Ping、
  UDP Syslog、WMESH 解析、位置判断和时间关联，不再启动新的 SSH 深度 MR 采集，已运行任务安全收尾；
- 深度采集最低/建议/最大时长为 10/20/30 分钟；
- 详细归档保留 30 天，轻量汇总保留 180 天。

第一阶段还增加了局点级 UDP 和高频写入参数：`udp_listen_host=0.0.0.0`、
`udp_listen_port=514`、有界接收队列 20,000、原始流每 100 条或 1 秒 flush、关键事件每 100
条或 1 秒批量提交。`syslog_server_ip` 默认留空，避免将 `0.0.0.0` 或监听地址错误下发到 MR；
只有配置为有效 IPv4 后，Supervisor 才会安排设备配置检查。

设置页通过 `/api/system/network/ipv4-addresses` 读取 Windows IP Helper 的本机 IPv4、网卡状态、
前缀、网关、路由 metric 和物理/虚拟属性，并分开配置“本机 UDP 监听地址”和“MR 日志回传地址”。
`0.0.0.0` 只允许用于监听，不能作为 MR 回传目标；保存和启动都会重新校验所选地址仍属于本机。
“检测到 MR 网络的推荐地址”只用 UDP `connect` 查询系统选路，不发送数据包；UDP 端口检查使用临时
独占绑定。外部 NAT 地址必须启用 `allow_external_syslog_address` 并在本次保存中二次确认，后端同时
记录高风险审计；普通无效、回环、组播和广播地址始终拒绝。

开始和结束时间不能相同，支持 `22:00-06:00` 跨午夜窗口，运行日期取窗口开始日期。运行中保存
配置不会重启当前 fping 或 SSH 任务，新配置从下一次调度周期生效；状态接口同时返回下一次开始和
结束时间。

首次运行前，“正线车辆”接口会从当前局点轨道交通基础资料聚合列车及 CT/CW 端点，因此无需先创建
无人值守 run 即可设置置顶。基础资料候选只表示“等待 AC 状态”，不会提前伪造正线资格或在线状态。

## 正线分类

`GroundUnattendedEligibilityClassifier` 组合当前局点：

- `main_path_code`；
- 站点 `node_type/path_code/participates_in_direction/track_facilities`；
- 区间 `section_kind/path_code`；
- 轨旁 AP 的稳定 ID、规范化 MAC、唯一精确名称、站点、区间和结构化 metadata；
- `AcMeshLinkQueryService` 的 fresh/online、当前 AP 和本机接收时间。

位置解析分别保存原始 AP、解析后 AP、规范站点、匹配依据和
`AP_EXACT/AP_REGISTRY/AP_ALIAS/STATION_EXACT/STATION_ALIAS/UNMATCHED` 等级。AP 只按稳定 ID、
规范化 MAC、Radio/BSSID Registry、唯一精确名称或基础资料中明确保存的 alias 匹配，不使用模糊名称。
若 AP 未匹配但 AC 站点可与正式站点或来源别名匹配，先按站点判断车辆段、停车场、存车线、非主路径和
方向参与状态，再决定正线资格，不能先误判为 `AP_UNMATCHED`。正式站点精确匹配可继续正线 Ping 和深采；
来源别名匹配只继续 Ping，待 AP 或正式站点精确确认后才启动深采。`UNKNOWN/STALE`、查询失败或 AP/站点
均无法匹配不会伪装为入段；这些状态暂停新深采，已有深采保持运行，已有 Ping 在
`ac_stale_grace_seconds` 内继续。

同一正线 AP 达到 `stationary_exclusion_minutes` 后返回 `MAINLINE_STATIONARY`：长 Ping 保持，
不启动新深采，已有自动深采走正常停止和既有最终化；AP 改变后计时清零并恢复深采资格。

## AC 轮询与长 Ping

Supervisor 每个轮询周期复用 `AcMeshLinkRefreshApplicationService` 创建或复用 AC Mesh-Link 只读
任务，并从 `AcMeshLinkQueryService` 读取现有解析结果。无人值守索引保存 AC 设备时间、本机接收
时间、来源快照 ID、列车/MR、端位、AP、站点、区间、里程、RSSI、freshness 和受控 raw 引用；
同一批记录另追加到当日按小时 AC JSONL。

`fping_v5_runner` 保持 `target: str` 向后兼容，并增加 `targets`。`FleetPingSupervisor` 默认每进程
12 个目标，目标变化时保留不受影响的分片，先启动替换分片再停止旧分片。多目标 JSON 在实际二进制
不可用时，每个分片降级为一个有界单目标轮询进程，不会为每台 MR 无上限创建进程；页面和事件表会
显示降级警告。

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

页面“长 Ping”保留汇总表，并通过受控的 `/ping-series` 和 `/ping-samples` 查询逐包 RTT、成功/丢包、
预热、位置未知、AP 切换和连续丢包区段。页面支持最近 5 分钟、30 分钟、1 小时、自定义时间和可关闭的
自动刷新；默认只读最近 30 分钟，单次最多 7 天，图表点数默认 3000、最多 10000。后端只选择与时间范围
相交的已登记文件，逐行读取并优先保留丢包点；逐包和 Syslog 分页仅保留当前请求页所需的有界最新记录，
不把全天原始流一次加载到前端、进程内存或 SQLite。

## 第一阶段实时采集基础

`TrainInventorySyncService` 从现有 `RailTransitBaseDataQueryService` 增量聚合当前局点的车载
MR。设备主体、地址和凭据仍只存在于设备管理；无人值守只保存列车/端点绑定、启用、置顶、调度优先级、
深采开关、仅监测和备注。缺少 CT 或 CW 会保留列车并显示端点缺失；设备移除只标记绑定移除，既有策略和
历史不会被物理删除。

`SyslogUdpReceiver` 的接收线程只负责 `recv -> 本机接收时间/全局与来源序号 -> 有界队列`。独立处理
线程完成 MR 映射、WMESH/IFNET 关键事件解析、状态聚合、按小时追加和批量入库。原始 NDJSON 保留原始
字节的安全编码、原文、设备时间、接收时间、两个接收序号、来源 IP/端口、主机名和 facility/severity。
身份只有在来源 IP 与 hostname 同时指向同一 MR 时才是 `VERIFIED`；清单同步优先将设备 `system_name`
登记为 Syslog hostname，缺失时才使用显示名。单项唯一匹配仅标记未确认，冲突绝不绑定，未知来源写入独立
`_unidentified` 流。设备时间与本机接收时间的差为 `CLOCK_OFFSET`，突变才是
`CLOCK_JUMP`，它们不表示网络传输延迟。队列溢出、重复和来源问题均作为数据质量事件，而不是把无人值守
运行标成失败。

原始流均由 `RawStreamWriter` 单线程追加并登记：Ping 为
`active/<run_date>/fleet_ping/<train>/<CT|CW>/<date>/<hour>_<generation>.ndjson`，WMESH Syslog
为 `active/<run_date>/realtime/syslog/<train>/<CT|CW>/<date>/<hour>_<generation>.ndjson`。当前打开
文件不会被压缩；停止、轮转或重启恢复后才登记为关闭/恢复文件。SQLite 只保存分钟汇总、连续丢包区间、
WMESH 关键事件、原始文件索引和健康事件，不逐条保存秒级原始 Ping 或 Syslog。

页面新增独立“Syslog 日志”标签，通过 `/syslog-records` 分页查看当前 OPEN 和历史 CLOSED/RECOVERED
文件中的真实接收内容。默认最近 30 分钟、每页 100、每页最多 500，支持列车、MR 名称、来源 IP、
设备系统名、级别和原文关键字过滤，分别展示设备时间、本机接收时间和时钟差。查询仅解析 Repository
已登记且位于当前无人值守数据根内的普通文件，拒绝路径逃逸、符号链接和目录联接。

Ping 稳定成功后，`MrSyslogConfigService` 通过既有设备凭据按
`display clock -> display version -> display clock` 连续取证。Boot Session 的主时间轴为两次设备
时钟中点减 uptime；同时保存设备时区、UTC offset、uptime 精度、估算误差、重启原因和本机
`checked_at`。设备时钟无法解析时才明确降级为 `LOCAL_FALLBACK` 并保存失败原因，不会静默冒充设备
时间。uptime 明显回退，或检查间隔内 uptime 已重置且估算上电时间越过容差时创建新 Session；只有设备
时钟因 NTP 跳变而 uptime 连续增长时保持原 Session，并记录 `CLOCK_JUMP`。

随后将 `display info-center` 作为运行态主检查，并以
`display current-configuration | include info-center` 补充验证来源规则，过滤不支持时才回退完整运行配置。
运行态必须确认 Information Center、loghost、实际目标 IP 和端口；`current-configuration` 只确认默认来源
禁止和 WMESH notification 两条 source 规则。Comware 省略默认 `info-center enable` 或默认 UDP 514 的
显式配置行时，以 `display info-center` 的实际运行态为准，不会重复下发或误报失败。下发缺项后逐条检查
命令回显，再执行两层复查：完整才为 `CONFIG_SENT` 或 `CONFIG_REPAIRED`，
复查缺项为 `CONFIG_VERIFY_FAILED`，异常为 `CONFIG_FAILED`。只有双层验证成功后才可进入
`WAITING_FIRST_LOG`；仅已验证匹配的 UDP 才可进入 `LOG_ACTIVE`。审计证据保存配置前后输出、运行态前后
输出、按运行态/source 规则拆分的缺项、修复命令与校验时间；配置指纹由规范化运行态目标和 source 规则
生成，不依赖原始配置字符串。固定 H3C Profile 不会执行 `save`、`undo`、重启、删除或停止时回滚。
`display info-center` 还解析 loghost 和其他输出目的地的时间格式，以及独占或同行展示的缓冲计数。dropped
计数增长是日志数据质量告警；overwritten 增长仅表示设备本地环形缓冲覆盖，不等同于 UDP 网络丢包。旧目标的
`undo` 清理仍需真实设备命令验证后单独实现。

运行态可同时返回多个不同 IP 的 loghost，省略端口统一为 514。NetConsole 只管理当前 Profile 指定的
IP/端口，保留其他 IP 的外部目标，不执行 `undo`。当前现场 H3C 版本以 IP 为 loghost 唯一键：同 IP
端口一致为 `TARGET_PRESENT`，IP 不存在为可安全补齐的 `TARGET_MISSING`，同 IP 已存在其他端口则为
`TARGET_PORT_CONFLICT`。冲突的自动检查不生成修复命令、不进入 `system-view`；只有用户在单台 MR
详情中明确二次确认后才允许改端口，并写入高风险授权与执行审计。配置指纹包含排序后的全部 loghost 和
当前 managed target，因此设备输出顺序变化不产生伪变更。

`ground_unattended` 索引库的 additive schema v6 包含列车清单/端点绑定/策略、boot session、Syslog
配置审计、WMESH 事件、原始文件索引、Ping 丢包区间和健康事件表；新增 Profile 外部地址确认字段，以及
Boot Session 的前后设备时钟、估算误差、重启原因、设备时区、UTC offset、时间质量和时钟跳变证据。
本轮新增深采总开关、Ping 预热字段、目标激活表和运行控制操作表；旧 `system` 或空时区迁移为
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

## 数据、归档和恢复

```text
files/rail_transit/ground_unattended/
├─ active/<run_date>/
├─ archives/<run_date>_ground_unattended.zip
└─ index.sqlite
```

每日结束先停止新调度，按配置限制深度任务最终化，停止/flush Ping，再生成 daily summary、覆盖 CSV、
调度事件、错误、深度 Session 引用、完整 Ping 汇总 JSONL、每日 MR/列车汇总和 manifest。即使某类
当天无数据，ZIP 也保留 `fleet_ping/`、`ac_snapshots/`、`timeline/`、`ping_summaries/` 目录契约。
ZIP 先写隐藏临时文件，逐成员 CRC、manifest 和流式 SHA-256 校验后原子发布；索引先标记 READY，
之后才用白名单递归清理对应 `active/<run_date>`。任一步失败均显示“归档失败，原始数据仍保留”。
深度 Session ZIP 只引用、不嵌入每日 ZIP。

同一运行日的 READY 归档视为已封账：重复归档只校验既有 ZIP 并补做待完成的 active 清理，不重写正式
文件；已有活动 run 时“立即开始”幂等返回，已归档运行日则拒绝复用。若 READY 文件损坏且 active 已
不存在，索引标记失败并保留现场文件，不用空目录覆盖证据。详细保留和汇总清理均按 profile
`timezone` 的局点日期计算。

启动恢复会核对 RUNNING/STOPPING/FINALIZING/ARCHIVING，收口上次 OPEN Ping 分段，调用现有
Online MR mapping 恢复；窗口内恢复 Ping 与调度，窗口外继续最终化和归档。无法恢复的自动 operation
标记为 PARTIAL。BUILDING/FAILED 且 active 仍存在的归档会在下一次 Backend 启动重试。

详细保留到期只删除已校验正式归档及对应 AC/Ping 分段/事件/深采索引；每日汇总保留至
`summary_retention_days`。手工删除同样走 Supervisor 队列、明确确认和受管路径校验，正在使用的当日
数据拒绝删除。

普通停止和停止并归档均先创建持久化 `operation_id`，重复请求返回同一活动操作。操作记录保存阶段、
进度、消息、失败码、结果摘要和完成时间；页面刷新或 Backend 重启后从 `/operations/latest` 恢复。
停止流程只有在深采安全收尾、全部 fping worker 退出、UDP 接收线程退出、原监听地址和端口可重新绑定、
队列清空、writer flush 且没有 OPEN 原始文件后才把 run 标记为 `COMPLETED`。worker、UDP、队列或文件任一项失败时操作与 run
明确进入失败状态，不伪装完成。停止并归档继续显示准备、写入、校验、登记和 active 清理阶段；ZIP
失败时 run 已正常停止，但操作和 archive 为失败，active 原始数据保留。

## API

前缀为 `/api/rail-transit/ground-unattended`：

```text
GET/PUT  /profile
GET      /status
POST     /start | /pause | /resume | /stop | /stop-and-archive
POST     /inventory/sync | /config-check
GET      /health | /raw-files | /syslog-records
GET      /trains | /trains/{train_id}
PUT      /trains/{train_id}/priority
PUT      /trains/{train_id}/policy
GET      /ping-targets | /ping-summary | /ping-series | /ping-samples | /timeline
GET      /deep-collections | /coverage
GET      /operations/latest | /operations/{operation_id}
GET      /archives | /archives/{archive_id}
GET      /archives/{archive_id}/summary-download
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
解析、Syslog 分页、时间轴 MR 名称解析、持久化停止操作、同 IP 端口冲突只读保护，以及不执行
`save/undo` 的 Syslog Profile。`vue-tsc`、
定向 Vitest 和 Web production build 作为提交门。

已完成一台 H3C MR 的 10 分钟真实 UDP 单机验证：Comware 省略默认 enable/514 配置文本时只读复查为
`CONFIG_PRESENT`，未进入配置视图；Receiver 实收 668 条并全部完成身份匹配和 WMESH 解析，队列无丢弃，
Boot Session 进入 `LOG_ACTIVE`，停止后原始文件已关闭登记。该结果只确认当前单台设备和现场样本，不能
外推为多列车压力、所有 Comware 版本或 IFNET 事件均已真实验证。

以下仍是人工现场门禁，不得由 fake 或本机回环测试提升为已验证：主备 AC 真实切换与设备时钟偏差、
十几小时持续多目标 fping、真实列车 AP 漫游、2 车/4 MR 并发 SSH、Session 现场 ZIP、低磁盘故障注入、
Electron 隐藏到通知区域后的整窗运行，以及退出后的 fping/Worker/SSH 进程核对。
