# NetConsole 命令参考

本文记录 NetConsole 当前实际使用或已预留展示的命令、交互输入、本地工具调用和非 CLI 接口，供后续审计、回顾和新厂商适配使用。

只读展示清单位于 `resources/command_reference.json`，Electron 页面“命令说明”直接读取该文件。首个生产执行 Profile 位于 `resources/device_command_profiles.json`；展示目录不是执行白名单，也不能据此增加任意命令 API。本文不记录真实账号、密码、IP、团体字、安全参数或现场专有数据。

## 总览

当前清单共归档 73 条：

| 统计口径 | 数量 | 说明 |
| --- | ---: | --- |
| CLI | 56 | 交换机、AC、FIT-AP、MR、Mesh、配置采集、诊断和文件准备命令 |
| 本地进程 | 14 | ping、fping、iperf3、netsh、PowerShell 和外部工具 |
| SSH/Telnet | 1 | 受控外部终端连接协议 |
| SFTP/SCP | 1 | 设备文件传输协议 |
| RESTful/HTTPS | 1 | 设备 Web 管理入口现状说明 |

风险级别：

| 风险级别 | 含义 |
| --- | --- |
| `read_only` | 只读查询或只读辅助动作 |
| `config_write` | 会进入配置上下文或写入设备/本机配置 |
| `interactive` | 存在交互确认输入 |
| `external_tool` | 本地或外部进程、连接协议、文件传输工具 |
| `unknown` | 当前源码无法确认完整行为 |

## 命令分类

| 大类 | 模块归属 | 设备类型 | 协议 | 输出 / 日志 | 解析器 / 消费模块 |
| --- | --- | --- | --- | --- | --- |
| 交换机基础采集 | 设备详情、轨旁 AP 光诊断 | 交换机 | CLI | 配置中心和轨旁 AP 原始回显 | `h3c_collect_service.py`、`trackside_optical_collection.py`、H3C parser |
| 交换机配置采集 | 配置采集中心 | 交换机 | CLI | `files/config_center/raw_logs`、配置快照 | `config_lifecycle_service.py` |
| 交换机诊断信息 | 设备管理诊断下载 | 交换机 | CLI | 诊断下载文本 | `diagnostic_download_service.py` |
| 交换机文件下载 | 设备文件下载 | 交换机 | CLI、SFTP/SCP | 文件下载队列和本地下载目录 | `file_transfer_service.py` |
| 交换机连通性检测 | 车内通信检测 | 交换机 / MR | CLI | 车内通信检测结果 | `car_network_diagnostic.py` |
| 无线 AC 管理 | AC 管理 | 无线 AC | CLI | 轨旁 AP 原始回显 | `h3c_ac_collect_service.py`、AC parser |
| FIT-AP / MR / Mesh | AC 管理、轨道交通 | FIT-AP / MR | CLI | online_mr raw logs、轨旁 AP raw logs | `online_mr_collector.py`、`vehicle_mr_online.py` |
| 网络工具 | 网络工具 | 本机 | 本地进程 | network_tools raw/outputs | ping/fping/iperf/netsh parser |
| RESTful 接口 | AC 网页入口 / 预留 | 网络设备 | HTTPS / RESTful | 当前无固定输出 | 当前未发现正式 RESTful 采集解析器 |

## 版本化生产 Profile

当前版本化命令目录登记两个稳定 Operation。`device.inventory.collect` 为只读详情采集，
`device.sftp.enable` 为独立的受控配置写操作：

| 字段 | 当前值 |
| --- | --- |
| Operation ID | `device.inventory.collect` |
| Profile ID | `h3c.comware.switch.generic.device-inventory.v1` / `h3c.comware.mobile_router.generic.device-inventory.v1` / `zte.zxr10.5960x-es.v2.device-inventory.v1` |
| Selector | H3C / switch / Comware / `*`；H3C / mobile_router / Comware / `*`；ZTE / switch / ZXR10 / `*` |
| 风险 | `read_only` |
| 兼容等级 | `generic_read_only` |
| Parser contract | H3C 结构化 parser；ZTE `netconsole.zte.zxr10-5960x-es.v2` |
| DTO contract | `netconsole.device-inventory.v1` |
| 样例证据 | Comware `7.1.070` fixture；车载 MR 只读核心命令合同；ZXR10 5960X-ES V2.00.20.03 手册 fixture |
| 真实设备状态 | `REAL_DEVICE_PENDING` |

`device.sftp.enable` 当前只登记 H3C Comware V7 的交换机、无线 AC 和车载 MR 三类精确 Profile，
风险为 `controlled_write`，真实设备状态均为 `REAL_DEVICE_PENDING`。命令顺序固定为：

```text
system-view
sftp server enable
ssh user {username} service-type all authentication-type any
return
quit
```

该操作只允许在用户明确授权、SSH 登录成功且明确确认 SFTP 子系统不可用后，通过
`Application Service -> DeviceOperationService -> Task Center -> Command Profile` 提交。
Huawei、ZTE、未知厂商、未知角色、未知平台和未知版本均失败关闭，不猜测命令、不提供兼容 fallback。

每个 step 都包含稳定 `step_id`、顺序、输出 selector、parser/DTO contract、只读风险和验证证据。`src/netconsole/services/h3c_collect_service.py` 按 Profile 固定步骤执行：H3C 继续保持原命令和解析行为；ZTE 先执行 `show version` 并确认 59X/5960X-ES，其他 ZXR10 型号在接口和 DOM 采集前失败关闭；通过型号门后才继续 `show interface brief`、`show opticalinfo brief`。分页由通用 SSH 交互执行器处理，不下发未经确认的关闭分页命令，raw 保留分页提示而 parser 使用清理副本。未知厂商、设备角色或平台失败关闭，任何厂商都不得回退到 H3C。未知软件版本只可使用明确标记的只读 generic Profile，不能据此宣称已完成真实设备验收。

除 `device.sftp.enable` 外，AC、MR、配置、诊断和文件管理的其他命令尚未迁入统一 Profile，
仍属于后续命令平台治理范围。不得用本切片状态替代逐域迁移和真实设备验收。

命令审计对经正式 loader 验证的 Profile 只做完整规范化字符串相等，不使用前缀匹配。旧 `H3CAdapter/H3CConnection/H3CCommandProfile` 没有生产调用且依赖用户备注猜测版本，已连同未验证的 `display transceiver`、`display interface all` 分支删除；后续只有在取得真实样本、Parser 契约和设备验收后，才允许通过新版本 Profile 重新引入对应命令。

## 交换机命令基线

以下命令来自当前源码和白名单，已全部纳入 `resources/command_reference.json`。

| 类别 | 命令模板 | 参数说明 | 前置条件 | 当前用途 | 风险级别 | 中兴适配状态 |
| --- | --- | --- | --- | --- | --- | --- |
| 会话准备 | `screen-length disable` | 无 | 登录设备 | 关闭分页 | `read_only` | 第一批待确认 |
| 会话准备 | `screen-length d` | 无 | 登录设备 | 关闭分页简写白名单 | `read_only` | 第一批待确认 |
| 系统名 | `display current-configuration \| include sysname` | 无 | `screen-length disable` | 提取 sysname | `read_only` | 第一批待确认 |
| 设备信息 | `display version` | 无 | `screen-length disable` | 版本、型号、运行信息 | `read_only` | 第一批待确认 |
| 设备信息 | `display device` | 无 | `screen-length disable` | 设备/板卡状态 | `read_only` | 第一批待确认 |
| 设备信息 | `display device manuinfo` | 无 | `screen-length disable` | SN、制造信息 | `read_only` | 第一批待确认 |
| 启动信息 | `display boot-loader` | 无 | `screen-length disable` | 启动版本 / Boot 信息 | `read_only` | 第二批参考 |
| 接口信息 | `display interface` | 可扩展接口参数 | `screen-length disable` | 接口详细状态 | `read_only` | 第一批待确认 |
| 接口信息 | `display interface brief` | 无 | `screen-length disable` | 接口概要、up/down | `read_only` | 第一批待确认 |
| 光模块信息 | `display transceiver interface` | 可扩展接口参数 | `screen-length disable` | 光模块基础信息 | `read_only` | 第二批参考 |
| 光模块信息 | `display transceiver manuinfo interface` | 可扩展接口参数 | `screen-length disable` | 光模块制造信息 | `read_only` | 第二批参考 |
| 光诊断 | `display transceiver diagnosis interface` | 可扩展为 `<interface>` | `screen-length disable` | 收光、发光、温度、电压、电流、阈值 | `read_only` | 第一批待确认 |
| LLDP | `display lldp neighbor-information list` | 无 | `screen-length disable` | LLDP 邻居列表 | `read_only` | 第一批待确认 |
| LLDP | `display lldp neighbor-information verbose` | 无 | `screen-length disable` | LLDP 邻居详细信息 | `read_only` | 第二批参考 |
| 配置采集 | `display current-configuration` | 无 | `screen-length disable` | 运行配置 | `read_only` | 第二批待确认 |
| 设备时钟 | `display clock` | 无 | `screen-length disable` | 无人值守按前后两次设备时间中点减 uptime 估算上电时间，并记录时区/UTC offset | `read_only` | H3C 北京时区现场格式已适配；解析失败显式降级 |
| Syslog 运行态检查 | `display info-center` | 无 | `screen-length disable` | 验证车载 MR Information Center、全部 UDP loghost 的 IP/实际端口/facility 和本地缓冲计数；省略端口归一化为 514 | `read_only` | 不同 IP 多目标已适配；同 IP 端口冲突默认只读 |
| Syslog 配置检查 | `display current-configuration \| include info-center` | 无 | `screen-length disable` | 验证车载 MR 的固定 Syslog 来源规则；过滤失败才回退完整运行配置 | `read_only` | H3C v7/v9 现场验证待完成 |
| 配置采集 | `display saved-configuration` | 无 | `screen-length disable` | 已保存配置 | `read_only` | 第二批待确认 |
| 配置保存 | `save force` | 无 | 登录设备 | 保存配置 | `config_write` | 第二批待确认 |
| 诊断信息 | `display diagnostic-information` | 无 | `screen-length disable` | 诊断信息 | `interactive` | 第二批待确认 |
| 诊断交互 | `n` | 交互输入 | `display diagnostic-information` | 诊断命令确认输入 | `interactive` | 第二批待确认 |
| 设备文件下载 | `dir flash:/` | 无 | 登录设备 | 查看 flash 根目录 | `read_only` | 第二批待确认 |
| 设备文件下载 | `dir flash:/diagfile/` | 无 | 登录设备 | 查看诊断文件目录 | `read_only` | 第二批待确认 |
| 连通性检测 | `ping <ip>` | 目标 IP | 登录设备 | CLI ping | `read_only` | 第二批待确认 |
| 连通性检测 | `ping -c <count> <ip>` | 次数、目标 IP | 登录设备 | 指定次数 CLI ping | `read_only` | 第二批待确认 |

补充设备命令还包括 `system-view`、`sftp server enable`、`ssh user <username> service-type all authentication-type any`、`return`、`quit`，仅用于 `device.sftp.enable` 的固定 Profile 顺序。其中 SFTP 启用和用户服务类型命令属于 `config_write`，命令说明页和只读文件浏览器不得直接执行。

## 非 CLI 接口说明

RESTful 不归入设备 CLI 命令表，在 JSON 中以 `is_cli=false` 标记。

| 接口 | 用途 | 当前边界 | 风险 |
| --- | --- | --- | --- |
| 设备管理 SNMP | 连接测试和基础识别 | 仅 v1/v2c、RO community、固定基础 OID；不进入命令目录，不接受任意 OID | `read_only` |
| HTTPS / RESTful | 当前主要用于打开 Web 管理入口 | 当前未发现正式 RESTful 采集解析器 | `unknown` |

SNMP Center、通用 MIB/OID 字典、SNMPv3、RW community、SET、Trap 和通用批量采集已从产品范围删除，不得重新登记为命令目录能力。

## Huawei / ZTE 扩展边界

Huawei 仍只有未来扩展边界，没有生产 Profile、命令、Parser 或真实 fixture；相关设备返回不支持，不能凭空猜测或回退到 H3C。

ZTE 本期只登记 ZXR10 5960X-ES V2 的轨旁 AP 接入交换机第一阶段只读框架：

| 能力 | ZTE 命令 |
| --- | --- |
| 会话分页 | 不下发关闭分页命令；执行器识别 `--More--` 并发送空格，受页数、字节、命令/空闲超时和取消限制 |
| 版本 / 型号 | `show version` |
| 接口 | `show interface brief` / `show interface <safe-interface>` |
| 光模块 | `show opticalinfo brief` / `show opticalinfo <safe-interface>` |
| LLDP 全局候选 | `show lldp entry` / `show lldp neighbor` / `show lldp neighbors` |
| LLDP 接口候选 | `show lldp entry interface <safe-interface>` / `show lldp neighbor interface <safe-interface>` |
| LLDP 配置候选 | `show lldp config` / `show lldp config interface <safe-interface>` |

LLDP 候选命令配置在 `zte_zxr10_5960x_es_v2` Profile 中，只允许由 `switch_vendor_sample_collect` 独立 Job 在严格 Guard 下执行，不进入普通轨旁默认采集链。由于缺少真实设备输出，parser 固定返回 `SAMPLE_REQUIRED`，不会伪造邻居结构。

ZTE 配置采集、配置下发、文件管理、CLI Ping、完整诊断包和 AC 保持 unsupported，不登记 H3C 猜测等价命令。版本/型号、接口状态、DOM 摘要与端口详情 Parser 只基于 V2.00.20.03 文档样例，统一标记 `DOCUMENT_SAMPLE_ONLY`。

文档中的 `RxPower/TxPower` 不是现场数据。第一阶段 ZTE 业务行固定为 `NOT_VERIFIED / REAL_DEVICE_SAMPLE_REQUIRED`，不参与双向光衰计算；H3C 继续使用既有计算和状态规则。

## 维护方式

后续新增展示命令时更新 `resources/command_reference.json`；生产执行命令还必须进入对应的版本化 Profile、绑定 Operation/step/parser/DTO contract，再运行：

```powershell
.\.venv\Scripts\python.exe .\scripts\maintenance\audit_commands.py
```

审计脚本只提示候选命令、疑似遗漏和精确列出的后续 Profile 迁移候选，不会自动覆盖 JSON 或本文档。发布门使用 `--strict`，存在 deferred 迁移项时返回非零。

查看入口：

```text
Electron Desktop：主导航 -> 命令说明
```

该页面只读展示，不执行任何命令。Electron 支持搜索、筛选、查看详情、复制命令模板和刷新；搜索使用 250ms debounce，并以请求代次丢弃过期响应。Markdown 导出复用既有 Export Process、`TaskDTO/TaskCancelResponse` 和公共 `WebArtifactStore`，公开 Task/下载文件名固定为安全可读 `.md` 名称，不公开 UUID 物理名或路径。模块只用严格命名的 localStorage key 保存当前任务 ID，通过既有 `/exports/{task_id}` 串行轮询；取消请求成功后立即 GET 并持续收敛到 `CANCELLED/FAILED/COMPLETED`，临时网络或 5xx 错误按固定延迟重试且不清任务 ID，仅终态、真实 404 或页面卸载停止轮询。

命令说明已接入共享 `TaskWindowContext`/validator、Job Center `command-reference` 模块筛选和真实取消 owner capability；Electron 通过正式 PlatformAdapter 传递受控的 `{taskId,module,status}`，浏览器开发态回退到同一 `/tasks` 页面。页面文本直接消费系统设置使用的共享动态 locale runtime，不建立第二套语言状态。
