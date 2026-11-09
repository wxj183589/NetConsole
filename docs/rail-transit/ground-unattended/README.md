# 地面无人值守 V2

## 产品与运行边界

地面无人值守是原版 NetConsole 的车载 MR 全天监测与故障追溯工作台，路由为
`/rail-transit/ground-unattended`，主 Feature 为 `module.ground_unattended`。
正式调用链为 Vue 页面 → FastAPI Router → `GroundUnattendedApplicationService` →
领域 Service / `GroundUnattendedRepository`。`GroundUnattendedSupervisor` 协调 Run；
`HeartbeatSupervisor` 由 Backend lifespan 独立启停，复用既有 Fleet 和状态引擎。

页面关闭、切页和隐藏只停止 Renderer 查询；后台心跳、AC、Syslog 和深采由 Backend lifespan 管理。
Ground 停止、结束计划或进入 ERROR 不停止常驻心跳。
默认窗口仍为 `07:00–23:00 / Asia/Shanghai`，支持跨午夜；暂停调度不停止心跳和 Syslog。
`/status` 的活动运行、最近运行、活动操作和最近终态操作分别返回，历史完成运行不冒充当前运行。
正常停止和停止归档通过持久 operation 收口，Backend 退出与用户停止意图分别持久化。

功能关闭时不创建本模块运行资源；索引失败返回本功能结构化错误，不阻断其他业务启动。
Ground 配置仍遵循既有冻结/热更新边界。独立 `/heartbeat/config` 持久化心跳启用、周期、
超时、分片和主备策略；热更新先排空旧分片，再应用参数，不新增 Supervisor。

## 十个页面

父页只维护运行控制、公共上下文、浮窗和十页导航；各页为独立 Vue 组件，复用现有 UI。
十个 Tab 与快速 Ping、历史导出动作均登记 Feature Registry，并提供中英文词条。

| 页面 | 职责及数据入口 |
| --- | --- |
| 运行概览 | `/status`、列车、健康、AC 与最近事件，分开显示运行和监测状态 |
| 心跳检测 | `/heartbeat`、`/ping-targets`、`/ping-series`；MR/整车状态、双 IP、详情及快速 Ping 入口 |
| AC-Mesh-Link | 复用 AC Mesh-Link 查询/刷新，展示设备时间、接收时间和 freshness |
| 快速 Ping | `/quick-ping`；选择 MR/地址、参数、启动/停止、实时 RTT、完整统计和历史任务 |
| Syslog 日志 | `/syslog-records`、原始文件索引；来源/模块/事件筛选、原文和解析详情 |
| 深度采集 | `/deep-collections`、记录与覆盖；复用 Online MR 会话及现有并发预算 |
| 时间轴 | `/timeline`；列车、端位、MR、事件、时间范围和原始事件详情 |
| 系统健康 | `/health`；Backend、Heartbeat、Syslog、AC、Storage 的现有健康聚合 |
| 历史归档 | `/history` 九类统一索引、全量筛选 CSV、原始记录入口、READY ZIP 校验/下载 |
| 设置 | `/profile`、库存同步、网络辅助及现有运行/存储配置 |

原独立“列车在线情况”导航已移除，旧路由重定向到无人值守；AC 查询及其他模块使用的公共能力保留。
Run 历史查看使用明确 `selectedRunId`；心跳页始终读取常驻流，不随 Run 选择切换。普通表格使用 `NcDataTable`；
日志页使用 `NcLogWorkspace` 与服务端分页，表体承担主滚动，筛选和分页保持可见。
轮询使用在途防重、取消、代次和过期响应丢弃；隐藏/卸载时释放请求、图表和监听器。

## 常驻 Heartbeat 生命周期

`/heartbeat/runtime` 查询状态，`PUT /heartbeat/config` 独立启停。默认启用；首次初始化继承旧
Profile 的 Fleet 参数，之后独立保存。Backend 每 5 秒检查 MR 基础资料变化；查询 API 不承担同步。
每 Site 只有一个 Heartbeat owner，重复 start 幂等，Site 切换关闭旧实例，Backend 关闭安全排空。
停用保留历史，清空库存须先停用并等待分片停止。分片失败有界退避，状态明确为
`HEARTBEAT_DEGRADED`；库存读取失败继续最后一次已验证目标。

`heartbeat-resident` 是持久数据流标识，不创建 Ground Run。原始心跳写入业务目录 `heartbeat/`，
不随每日 Ground 归档删除。首次迁移复制最近旧快照和心跳丢包区间，保留旧 Run；幂等标记防止
用户清空后再次恢复旧记录。累计汇总按目标恢复，重启空窗不视作设备失败。

## 心跳目标与状态

`HeartbeatStateEngine`、`TrainConnectivityAggregator` 和 `HeartbeatEventService` 维护独立的
IP、MR 和列车事实。目标来自当前局点基础资料/设备库存：列车、MR UUID、CT/CW、主用和备用管理 IP。
不依赖 AC 在线、Mesh-Link、SSH 凭据、Syslog 或位置分类；场段与未知位置也不能取消有效心跳目标。
AC 位置资格只用于位置展示、正线统计和深采，不能再用作心跳目标门槛。

默认心跳参数为间隔 **1000ms**、超时 **4000ms**、包大小 **64 Bytes**，复用
`FleetPingSupervisor` 和既有 fping runner；默认每分片 12 个目标，变更目标保留未变化分片。
没有自动快速扫描、离线停止、低频重新发现或独立恢复扫描任务。

同 MR UUID 的有效监测地址按“任一成功”聚合，分别保存每个 IP 的 RTT、发送/成功/丢失计数、
最近成功和连续无响应。基础资料的 `backup_monitoring_strategy` 明确控制备用地址：
`MONITOR` 纳入自动心跳，`FAILOVER_ONLY` 与 `DISABLED` 不纳入自动心跳；人工快速 Ping 可以明确选择
已登记备用地址。策略按 MR UUID 保存，库存只是投影。

- 单 MR 连续 10 秒无任何有效地址成功才进入 `OFFLINE`，只生成一次离线事件，并持续探测。
- 偶发丢包经过 `LOSS/OFFLINE_PENDING`，不立即触发离线告警。
- 离线后经过 `RECOVERING`，连续成功 2 次才确认 `ONLINE` 和恢复事件。
- CT/CW 双端不可达交集达到 120 秒才进入 `TRAIN_OFFLINE`；一端恢复立即清零交集。
- 部分在线状态按可达端命名：`CT_ONLY` 表示仅 CT 可达，`CW_ONLY` 表示仅 CW 可达。
- 单 MR 列车使用单端 10 秒规则，不伪造双端整车状态。
- fping 退出、流中断、重启或写入失败属于引擎问题；缺少有效探测证据时标记
  `UNKNOWN/DEGRADED`，不能把采样空白转换成设备连续失败。

当前 MR/列车快照持久化在心跳状态表，事件写入既有事件索引。重启保留最近成功和累计统计，
恢复有效目标并记录采样中断；历史快照不作为重启后连续失败的证据。
原 Fleet 的 10 秒统计预热只影响有效统计/关联，原始样本仍落盘，心跳状态证据不受此预热延迟。
汇总缓存只保留每目标/种类的当前时间桶；旧桶落盘后淘汰，迟到样本从 Repository 恢复累计。

## 快速 Ping

`QuickPingService` 通过既有 fping runner 启动独立任务，默认 **200/1000/64、无限时长**。
支持修改参数、30 秒/1/5/10 分钟及自定义时长，有限时长自动结束，无限任务手动停止。
选择列车、CT/CW、单台/多台 MR 与主备地址时只接受当前局点已登记的身份和地址。

每次生成独立 `run_id`，任务可在无人值守停止时单独运行，也可与心跳并行；不写心跳状态、不停止心跳。
Backend 退出会收口快速 Ping worker。每局点最多 4 个活动任务，每任务最多 32 个目标，
通过全局发包间隔控制最大在途请求；内存仅保留最近 256 个样本和有界任务缓存。

实时显示发送、接收、丢失、丢包率、最小/最大/平均 RTT、抖动、连续丢失及 RTT 曲线。
SQLite 保存任务、统计与事件，逐包数据按 MR 写入独立 NDJSON；无限任务持续按小时或 10MiB 分段。
关闭分段后后台 gzip、校验并原子发布，样本查询支持已关闭压缩段，游标使用稳定逻辑路径。
原始数据和终态汇总分别采用 Profile 的 `ping_raw_retention_days`、`summary_retention_days`，
只处理受管、已登记、已关闭、到期的任务数据，不触碰活动任务、未知文件或真实数据根外路径。

## Syslog：原始优先

沿用设备连接、凭据、配置核验和命令白名单。指定配置仍为：

```text
system-view
info-center enable
info-center loghost <服务器IP> port <UDP端口>
return
```

UDP、Informational，不启用 Debugging、不添加 Trap/TCP、不执行 `save`、不清理旧配置。
设备回传地址与本机监听地址分开校验；`0.0.0.0` 只能用于监听。
自动测试不连接或配置真实设备。

```text
UDP Receiver → 有界 Raw Queue → Raw Writer → 原始 NDJSON
                                          ↓
                                  有界 Parser Queue → Parser Worker → 派生索引
```

原始 envelope 先保存，解析失败和未知模块仍保留完整原文。支持 WMESH、IFNET、CFGMAN、WLAN、SYSTEM
和 UNKNOWN 模块分类；解析失败另记诊断。Raw Writer 与 Parser 独立线程，Receiver 不进行压缩。
接收/解析积压进入当前运行的受管 spool；正常停止有界排空并登记，异常恢复采用 at-least-once 重放。
应用层 `dropped=0` 不能证明网络 UDP 没有丢包，也不能证明跨崩溃 exactly-once。

每个 MR 独立文件键和目录，未知/冲突来源隔离，不能猜测绑定其他 MR。
文件按小时或 10MiB 关闭轮转；后台压缩逐段校验 SHA-256 与原始大小后登记，失败保留原始证据。
现有 RawCompressionWorker 保留 NDJSON 与登记的 gzip 副本，原始查询/READY ZIP 读取契约继续有效。
队列、Writer/Parser 存活、spool、写盘失败、压缩失败及磁盘压力进入系统健康。

## AC、深采和统一时间轴

AC 是独立辅助数据源，保留既有轮询频率、解析、常驻任务与 SSH 复用；每 run/controller 一个受管
Poller。慢轮询与失败不阻塞心跳。`device_time` 与 `received_at` 分开保存，freshness 基于本机
收到的事实和现有阈值计算；过期显示 `STALE`，缺失设备时间保持未知，不能伪造实时性。

深采继续使用 Online MR 的连接、命令、会话、并发及停止最终化流程；默认并发预算仍为
2 辆活动列车、4 台活动 MR、2 台启动、2 台最终化。深采失败不停止心跳，偶发丢包不取消深采。
关键磁盘阈值阻止新增深采，已有任务按既有生命周期收尾，并保存具体失败原因。

`/timeline` 合并心跳丢包/离线/恢复、整车事件、Syslog、系统重启、Mesh 切换、RSSI、深采与 AC 异常。
查询提供列车、端位、MR、事件、时间范围和分页，保留原始事件详情与设备/地面时间。
AC 延迟只影响接收新鲜度，不改写设备事件实际发生时间。
AP Current/Peer/Radio/BSSID 身份通过统一 `ApIdentityQueryService` 完整 MAC 精确解析，
请求内固定 revision；歧义保持未绑定，不以名称、站点、尾号或 MAC 相似度猜测。

## 系统健康

复用 `GroundHealthDTO` 和 `/health`，统一 `HEALTHY/DEGRADED/CRITICAL/UNKNOWN`，与设备在线状态分开。
展示 Supervisor/worker/运行时间/最近错误、目标/进程/采样率/最近样本/写入耗时、UDP/队列/Parser/
spool/轮转/压缩、AC 成功率/失败/新鲜度以及真实磁盘总量/余量、原始文件量和归档状态。

RUNNING 启动宽限后无 Supervisor、无应有 fping、Receiver/Writer/Parser 退出或原始写入/丢弃故障为
CRITICAL；AC、压缩/归档失败及队列压力为 DEGRADED；无可观测运行态为 UNKNOWN。
历史 info 事件不冒充最近错误，不能用系统故障直接生成设备离线事件。

## 数据、查询和归档

数据根由 `PathResolver` 决定：`sites/<site>/files/rail_transit/ground_unattended/`，索引仍是既有 `index.sqlite`，
无人值守活动目录为 `active/<运行日>/`，正式归档为 `archives/`，快速 Ping 使用独立 `quick_ping/<日期>/`。
MR 目录同时包含列车、端位和 MR UUID；具体生成规则见生产 writer，禁止硬编码本机路径。
SQLite 保存索引/任务/当前状态/事件/汇总，逐秒样本写 NDJSON，不恢复 Legacy HistoryStore runtime。
当前状态表并非逐秒历史；汇总和事件提供历史证据，不能从当前快照虚构连续样本。

历史工作台按 Site、时间、run、列车、CT/CW、MR、数据类型和事件筛选，覆盖运行、车辆、心跳、
快速 Ping、Syslog 原始文件、Syslog 解析、AC 快照、深采和时间轴九类索引。
原始文件详情提供 revision、hash 和记录数，记录级查询继续走有预算的 Raw Query。
缺失来源显示 UNAVAILABLE；原始 Syslog 索引行不是每条 UDP 报文。

“导出筛选结果”复用保存协调器 → 固定导出动作 → 独立 Export Process → Artifact，导出同一读取
snapshot 下符合筛选的全量索引，不受当前页限制；CSV 使用 BOM 与公式转义。
取消保存选择不提交任务。原始记录/文件及 READY ZIP 使用各自入口，不把索引 CSV 描述为全部原始报文。

原始数据默认保留 30 天、汇总 180 天，Profile 可配置。重要问题事件与当前状态不由普通样本清理删除。
保留/删除仅限受管终态数据；不自动迁移或删除旧目录、不扫描真实数据根之外的路径。
READY ZIP 的原子发布、manifest/hash/CRC、成员路径/大小/压缩预算与 opaque Artifact 下载继续复用。
验证失败保留 active；非空 spool 阻止清理；READY 文件不可变。原始删除走预览、短期确认 token、
锁、revision/hash 复核和审计，压缩副本存在时禁止不一致的记录级改写。

## 验证入口与限制

风险及消费者套件以 `config/architecture/change_impact_matrix.json` 为准。
长期统一入口为 `python -m scripts.quality.local_gate --mode auto`；L4 最终组合使用 `--mode full`。
定向覆盖 `tests/test_ground_unattended_*.py`、UDP spool、AC/Online MR、Renderer 组件/行为和浏览器视觉。
所有自动化使用唯一 RuntimeMode.TEST 根和 Mock/Fixture，不读取或复制真实业务数据。

自动化证据分开报告状态机虚拟 24h、400 IP Mock、Syslog 集中上报、实际文件压缩和浏览器视觉，
不能替代真实 24h 后台、多 MR 现场 UDP、原生 Windows 缩放、Electron 托盘长时或安装包验收。
本次实施与命令结果见[交付记录](../../archive/ground-unattended-v2-delivery-2026-11-07.md)。

历史工作台支持 `sort_order=asc|desc`（默认 desc），在服务端按记录时间排序后分页；相同时间使用固定身份键消除跨页抖动。全量 CSV 导出沿用相同排序及筛选。页面固定文案接入现有中英文 i18n；设备原始日志和事件原文保持来源内容。
