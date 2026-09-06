# Device Inventory Parser Contract

日期：2026-09-04
适用 Operation：device.inventory.collect
状态：只读审计契约，不修改现有 Parser

## 1. Contract 边界

本契约描述当前 Device Inventory parser 的输入、输出和失败语义，供 CLI replay/golden 测试使用。它不是新的 DTO、Parser 或生产接口。

生产 Collector 仍负责：

- 通过已绑定 Device Command Profile 执行命令；
- 保存 raw output 和 collect run；
- 将各 selector 传给当前厂商 parser；
- 将 parser 结果写入 DeviceFactRepository/DeviceRepository；
- 计算 task success、partial_success 或 failed。

Replay runner 只读取 selector 对应的 CLI 文本，调用相同 parser，并将结果投影为 test-only normalized dictionary。Replay 不执行连接、不写数据库、不调用生产 Collector。

## 2. 输入 Contract

### 2.1 H3C Comware

适用当前 H3C switch/wireless_controller inventory parser path；mobile_router 只应提供其 profile 允许的核心 selector。

| Selector | CLI 来源 | 当前 Parser | 作用 | 必需性 |
| --- | --- | --- | --- | --- |
| inventory.sysname | display current-configuration | parse_sysname | 补充设备系统名 | 可选，version 可提供 fallback |
| inventory.version | display version | parse_device / parse_version | 版本、厂商、平台、型号候选、序列号、MAC、uptime、BootRom | H3C identity 的主要输入 |
| inventory.device | display device | parse_device_model | slot/device model | 可选，作为 model fallback |
| inventory.manuinfo | display device manuinfo | parse_version 内部 manuinfo parser | 型号、序列号、MAC、厂商补充 | 可选 |
| inventory.boot_loader | display boot-loader | parse_boot_loader | 当前/主用/备用软件 image sections | 可选；生产 facts 使用 bootrom_version 字段承载既有结果 |
| inventory.interfaces | display interface | H3CParser.parse_interfaces | 接口状态、描述、速率、双工、PVID、二层/三层字段 | 可选；提供时单独解析 |
| inventory.transceivers | display transceiver interface | H3CParser.parse_optical_repository | 光模块型号、序列号、厂商、波长、距离、接口 | 与其它 transceiver selector 合并 |
| inventory.transceiver_manuinfo | display transceiver manuinfo interface | H3CParser.parse_optical_repository | 光模块制造信息补充 | 可选 |
| inventory.transceiver_diagnosis | display transceiver diagnosis interface | H3CParser.parse_optical_repository | 温度、电压、偏置、RX/TX、告警和状态 | 可选 |
| inventory.lldp_list | display lldp neighbor-information list | H3CParser.parse_lldp | 本地接口和邻居摘要 | list/verbose 至少提供一个时解析 |
| inventory.lldp_verbose | display lldp neighbor-information verbose | H3CParser.parse_lldp | chassis、port、system、管理地址补充 | 可选 |

H3C 生产路径由 profile 决定完整 command sequence；replay case 不重新解析命令，也不替换 profile sequence。

### 2.2 ZTE ZXR10

| Selector | CLI 来源 | 当前 Parser | 作用 | 必需性 |
| --- | --- | --- | --- | --- |
| inventory.version | show version | parse_device_identity | ZXR10 身份、型号、版本、uptime、system name、解析状态 | identity 主要输入 |
| inventory.interface_brief | show interface brief | parse_interfaces | 接口状态、媒体、速率、描述和 oper status | ZTE inventory 主要接口输入 |
| inventory.switchvlan_config | show running-config switchvlan | parse_switchvlan_running_config | 接口 mode、PVID、native/tagged/untagged VLAN | 可选；提供时参与 merge |
| inventory.vlan_table | show vlan | parse_vlan_table | VLAN table/PvidPorts 校验和补充 | 可选；提供时参与 merge |
| inventory.optical_brief | show opticalinfo brief | parse_optical_summary | 模块 presence、DOM、RX/TX、阈值、原生状态 | ZTE optical 主要输入 |
| inventory.lldp_list | show lldp neighbor brief | parse_lldp_brief | LLDP brief 邻居集合 | 可选；与 entry 合并 |
| inventory.lldp_verbose | show lldp entry | parse_lldp_entries | LLDP 详细邻居属性、管理地址、PVID、能力 | 可选；与 brief 合并 |
| inventory.optical_detail::<interface> | 受控动态 detail command | parse_optical_detail | 显式 opt-in 的单端口 detail | 不在本阶段回放范围；普通 inventory 默认不追加 |

ZTE 当前 production collector 在解析后执行已有 VLAN merge、optical merge 和 LLDP merge；Replay runner 复用这些 merge functions，但不写 Repository。

## 3. 输出 Contract

### 3.1 Device facts

H3C parser 可能提供：

- vendor；
- platform_family、software_family；
- software_version、software_train、software_release；
- software_major_version、platform_major_version；
- model、serial_number、mac_address；
- sysname、bootrom_version；
- uptime、uptime_seconds、uptime_precision_seconds；
- last_reboot_reason。

ZTE identity parser 可能提供：

- vendor、platform、platform_family、product_family；
- model、software_version、base_version、build_version；
- system_name、board_name；
- uptime/uptime_seconds；
- parser_version、verification_status、parse_status、warnings。

Replay golden 只保留稳定字段，不保留 raw command、raw output reference、采集时间或运行态 metadata。

### 3.2 Interface records

稳定低层字段包括：

- interface_name 和 normalized_name；
- link/physical/protocol/admin status；
- oper_status；
- description；
- speed/duplex/media_type；
- H3C 的 interface_type、port_status、vlan；
- ZTE 的 pvid、pvid_source、pvid_verified、port_mode、native_vlan、VLAN config status。

接口 parser 不产生 station_id、ap_uuid、Trackside match 或 FIT-AP relation。

### 3.3 Optical records

稳定字段包括：

- interface_name；
- module_model/type、module_present、module_online、DOM support；
- module/vendor/wavelength/connector/distance；
- RX/TX power；
- RX/TX thresholds；
- temperature、voltage、bias（若该 vendor output 提供）；
- vendor_status、normalized_status/status、severity_reason。

RX/TX 是设备侧单端观测。Parser 不把单端 optical power 命名为 Trackside forward/reverse loss，也不计算 AP 业务 severity。

### 3.4 LLDP records

稳定字段包括：

- local_interface；
- neighbor MAC/chassis ID/system name；
- neighbor interface/port；
- neighbor IP/management address；
- scope、holdtime/TTL；
- port description、system capabilities、PVID（若 ZTE Entry 提供）。

Parser 不决定：

- AP UUID 或站点归属；
- 跨站点关系；
- fuzzy identity match；
- reverse match/conflict；
- Trackside 或 FIT-AP 业务状态。

## 4. 必需、可选和缺失规则

### 必需输入

- H3C：至少有 version 才能形成有意义的 device identity；interfaces、optical、LLDP 各自只在对应 selector 存在时解析。
- ZTE：version、interface_brief、optical_brief 是当前固定 inventory profile 的主要输入；VLAN/LLDP 依据 profile 和设备结果可分别为空。
- fixture metadata 必须明确 vendor、platform、software_version、profile_id 和 source category。

### 可选输入

- H3C sysname、device、manuinfo、boot-loader、transceiver manufacture/diagnosis、LLDP verbose；
- ZTE switchvlan、VLAN table、LLDP brief/entry 的任一侧；
- ZTE optical detail 不是本阶段普通 inventory replay 的必需输入。

可选输入缺失时，golden 必须记录 EMPTY/MISSING 或对应 parser status，不用别的领域输出补猜。

## 5. 异常与状态

Parser 应返回可序列化结果或已有 parser result，不应因未知列、空行、分页提示或额外字段崩溃。

常见状态：

| 状态 | 含义 | Replay 处理 |
| --- | --- | --- |
| OK/PARSED | 至少识别到有效结果 | 写入 golden 的 stable result |
| EMPTY/NO_NEIGHBOR | 输出有效但没有记录，或明确无邻居 | 保留空数组和状态 |
| PARSE_FAILED | 未找到必要表头/结构或字段不足 | 保留状态和 warning count，不抛 runner 级异常 |
| NOT_RECOGNIZED | identity 不是目标厂商/平台 | 保留空/部分 identity 和状态 |
| COMMAND_UNSUPPORTED/UNSUPPORTED | 输出明确表示命令/型号不支持 | 保留 parser status；不 fallback 到其它厂商 |
| partial | 某些 selector 或记录可解析、其它缺失/失败 | 由 production collector 聚合；replay 逐 selector 保留状态 |

异常文本包括 unknown field、坏行、缺少表头、输出截断、命令不支持、空输出和无邻居。Replay 测试只断言现有 parser contract 的“不崩溃和稳定状态”，不在本阶段修改 parser。

## 6. Production partial success 映射

生产 H3C collector 以 per-command/per-parser 错误继续处理可用 selector：

- facts、interfaces、optical、LLDP 分开解析和写入；
- 某一块失败不应被 replay runner 伪造成其它块成功；
- 没有任何可用事实时，生产任务才进入 failed；
- 有事实且存在命令或解析错误时，生产任务可以进入 partial_success。

ZTE production collector 额外保留 VLAN merge warnings、optical merge status、LLDP brief/entry merge 和 snapshot preservation 语义。Replay golden 只断言稳定 parser result 和 warning count，不写入这些 production snapshots。

## 7. 不变量

1. 同一 fixture 同一 parser 版本重复回放，normalized result 必须字节稳定。
2. 增加未知 selector 或未知输出字段，不改变已知 selector 的 normalized result。
3. 空输出和异常格式不触发网络连接、不写 DB、不生成 UUID/时间/路径。
4. vendor/platform/version 不匹配不触发跨厂商 parser fallback。
5. golden 变化必须有原因和审查记录，不能通过自动更新掩盖 parser 回归。
6. 本契约不授权新增 DTO、Operation、Profile 或生产 Parser。

## 8. 证据状态

本阶段预期 fixture 统计：

- REAL_CAPTURE：1 个既有 C89E-4 V1.9.0 脱敏现场片段；
- SYNTHETIC：H3C Comware 7、H3C Comware 9、ZTE 5960X-ES 共 3 个；
- 真实设备连接：NO；
- 真实数据写入：NO；
- fixture 回放通过不等于 C89E-4 之外的 ZTE 型号、H3C Comware 9 或其它版本已经现场验证。
