# 旧版软件功能完善进度

2026-11-28。产品基线 `28d6e201`，集成分支 `codex-A/legacy-functional-completion`。本轮验证使用源码 Electron、局点隔离夹具和本机回环。运行记录在 Workspace 的 `reports/tests/fc-devices`、`fc-rail` 和 `fc-services`。下列耗时均为单机观察值。

| 模块与依赖 | 数据来源、API 与页面 | 本轮实现和证据 | 尚缺的验收 |
| --- | --- | --- | --- |
| 设备管理和档案，依赖台账、采集事实、配置仓和任务库 | 台账与档案共用设备 UUID；`/network/devices`、`/devices/:deviceId`。接口、模块、LLDP 按当前设备读取局点快照 | 从档案带入设备创建任务。Electron 打开七区，核对 SW01 接口、光模块及 LLDP 来源和时间，以及本轮升级记录。万行夹具中目标匹配 5,000 行，深页 50 行与计数合计 21.77 ms。`b9aa2dcb` | PARTIAL。首次七区检查中 SW01 的配置与关联业务为空；现场数据待验 |
| 网络设备任务，依赖局点、模板、Worker、设备锁和 Artifact | `/api/device-operations`、`/api/job-center`；`/tasks` 由后端按当前 Site 和设备任务域查询 | 隔离升级走真实子进程、每设备结果、重试与 XLSX 导出。Electron 中点选 SW01，查看回滚后 1.0 版本。校验失败、取消、成功分支有定向用例。`508ab0b8`、`155154f5`、`c7a8cdaa` | PARTIAL。固件和目标设备为模拟对象；厂商传输、真实重启和失联恢复待实验设备验收 |
| 控制台，依赖会话与终端适配器 | `/console`、`/api/terminal`；宏解析器与终端输入链路 | `3abcea08` 增加宏执行前预览确认。广播、粘贴、多窗口机制见基线[模块契约](../architecture/LEGACY_MODULE_CONTRACTS.md) | PARTIAL。跨窗广播和连接协议应分别核验。SSH、COM 和真实 SFTP 联调待验 |
| 地面无人值守，依赖活动 Run、历史库和时间窗 | `/api/rail-transit/ground-unattended`；实时、回放各自持有页面状态 | Quick Ping 按需读取，MR/时间窗变化取消过期请求，MR UUID 线性去重。游标读取验证组合索引和限量取详情。实时 20,000 条 Syslog 压力用例 9.74 s，归档 Heartbeat 回放用例 0.10 s。源码 Electron 预热后切换至实时/归档标题一次为 170/17 ms。`966e31df`、`e2822302`、`aa06fdfa` | PARTIAL。生产规模多源归档的端到端吞吐待测 |
| Syslog 与轨旁 AP，依赖监听器、身份解析、光衰及 LLDP | 地面实时设置和轨旁 AP 业务页；轨旁服务读 AC 和交换机采集事实，手工工程字段由轨交入口维护 | TCP 配置检查监听地址与端口；TCP/UDP 回环、Comware 能力选择、光衰失败历史隔离、LLDP 冲突及过期回归。AP 编辑迁移沿用原 AP ID 和权限。`538c57c8`、`83cce171` | PARTIAL。真实 V5/V7/V9 配置和设备回传待现场验证 |
| 无线管理，依赖 Site 台账、AC 快照及 FIT-AP 资源 | `/api/ac-management/controllers`、`/ac-management`、`/ac-management/fit-aps`；控制器按 UUID 关联，AP 资源保留各 AC 归属 | 新增轻量 AC 目录和定向 FIT-AP 下钻；SQL trace 验证目录不读取 AP 明细。登记部署按 Site 保存成员 UUID 和修订号 | PARTIAL。登记信息来自运维录入；物理堆叠、集群与 1+1 拓扑的现场验证待办 |
| 日志，依赖结构化事件和请求中间件 | 软件说明与维护 `/logs`，请求 ID 关联运行事件 | 按路由对慢请求 30 秒采样，5xx 按次记录。隔离注入万行事件，源码 Electron 用 request ID 筛选，前两页各 200 条，交互加两次查询 1204 ms。`63fca3e5` | PARTIAL。这个样本不能说明每类历史事件都有 Device 或 Task 关联 |
| 文件管理，依赖局点受管根、设备传输服务和任务 Artifact | `/file-manager`、`/device-files`、`/api/file-management`，每设备执行结果链接产物 | 搜索受管目录，文本预览上限 64 KiB；真实 Electron 打开合成 CSV；任务隔离导出 XLSX 见 `e9b17d7d` | PARTIAL。真实 SFTP 上传、设备下载和网络中断后的重试待验 |
| 网络服务，依赖网络工具 Worker、系统探测器和局点历史 | `/tools/connectivity`、`/api/network-tools`；Ping 历史、DNS、Traceroute、TCP 测试 | 统一 DNS/Traceroute 作业和历史分页；Windows 回环 Traceroute 后刷新 Renderer，重新打开历史输出。通断区间显示失败与恢复。`c39506c2`、`4d57edc6` | PARTIAL。跨主机链路与实网故障时间轴待现场验证 |
| 菜单，依赖 Feature、路由及业务执行器 | 设备资料、无线管理、轨道交通和任务中心均路由到业务页 | 任务分类复用同一表单与执行链；保留原诊断下载、配置采集深链及权限。无线规划字段移至轨交 | PARTIAL。菜单和后端授权分别验证 |

## 开源参考与演进

已核对的固定源码版本、文件和许可证见[源码研究](../architecture/OPEN_SOURCE_REFERENCE_STUDY.md)。本轮沿用现有依赖。

| 参考 | 本轮对应实现 | 后续核验或演进 |
| --- | --- | --- |
| NetBox，Apache-2.0 | 设备 UUID 与接口、光模块及归属关系分开，AC 部署引用台账 | 用多 AC 同序列号样本核对资源归属 |
| Oxidized，Apache-2.0 | 配置文件与版本由配置采集服务管理；档案消费版本与差异 | 核验有多个快照时的跨版本浏览 |
| eNMS，GPL-3.0 | 单次任务、每设备输出、重试分别持有标识 | 在多设备失败/恢复样本中核验结果链 |
| Semaphore，MIT | 局点过滤、执行环境、升级能力门控在后台实施 | 进一步验证长时调度与取消恢复 |
| xterm.js，MIT | 终端输入保留现有处理链，应用层提供预览与用户确认 | 用实机验证多窗口断线时的目标集合 |
| Netmiko，MIT | 沿用连接适配层与设备锁，上层模板使用明确目标 | 真实机型的回显及超时由适配层验证 |

上述项目均采用设计参考，本轮未移植其源码。发布、安装和生产数据维护在本阶段范围外。
