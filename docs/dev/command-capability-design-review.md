# NetConsole Command Capability Design Review

日期：2026-09-04
Branch：codex-A/engineering-hardening
Review HEAD：4008a35cb81803e5336c30fcd609bc79fc51921a
Review 标识：command-capability-design-review

## 1. 审查范围与约束

本文件是 Phase 2A 的只读设计审查，回答三个问题：

1. Device Inventory、Trackside Optical/LLDP、FIT-AP Optical 当前分别如何执行命令、解析输出、写入数据和向 API 提供结果。
2. 三条链路在哪些低层字段上可以复用，在哪些地方必须保持领域隔离。
3. 如果将来抽象 Command Capability，最小、低风险、可回滚的分层和迁移顺序是什么。

本轮只新增本文件，不改变以下任何内容：

- 源码、命令实现、resources/device_command_profiles.json；
- Operation ID、任务类型、Parser、DTO、API、数据库、UI；
- 设备连接、真实设备验证、真实数据目录、打包、版本和发布状态。

审查输入为当前干净的 engineering-hardening worktree、下列 canonical 文档和代码事实：

- docs/dev/command-semantic-matrix.md
- docs/dev/engineering-hardening-baseline.md
- docs/ARCHITECTURE.md
- resources/device_command_profiles.json
- src/netconsole/services/device_command_profile_service.py
- src/netconsole/services/command_guard.py
- Device Inventory、Trackside、FIT-AP 三条链路的 Application Service、Job Handler、Collector、Adapter、Parser、Repository 和 API Model。

Phase 2 的 Trackside optical worktree 在本审查开始前仍被基线标记为未合并。因此，本文区分“当前 HEAD 已确认的行为”和“Trackside worktree 合并后必须重新审计的行为”，不把未提交 diff 当作设计输入。

## 2. 结论摘要

### 2.1 总体判断

三条链路不应直接收敛为一个通用的“命令执行器 + 一个 DTO + 一个 Operation”。推荐的目标是：

- 在低层共享受约束的 Capability 词汇、命令安全约束、带单位的观测字段和原始证据引用。
- 在领域层保留各自的 Operation、目标身份、采集范围、匹配规则、持久化边界、历史语义和失败模型。
- 由每个领域自己的 Adapter/Profile 把低层 Capability 绑定到具体厂商、平台、版本和协议，不建立全局命令字符串注册表。
- 先做 replay fixture 和只读内部契约，不先改 API、数据库、任务类型或现有用户行为。

因此，本审查的核心答案是：

| 问题 | 判断 |
| --- | --- |
| LLDP 是否可以统一 | 可以统一低层 neighbor evidence 的部分字段和状态词汇；不能统一设备盘点、车站/AP 拓扑匹配、FIT-AP 侧证据三种领域语义。 |
| Optical 是否可以统一 | 可以统一带单位的模块/功率观测原语；不能统一命令来源、采集侧、接口身份、阈值解释、衰耗业务计算和存储 DTO。 |
| Command Capability 应放在哪里 | 放在领域 Adapter/Profile 之下、Parser 之上或与 Parser 契约相邻的位置；它描述“可做什么以及如何安全做”，不拥有业务关系。 |
| Operation 是否立即拆分 | 不拆。保留现有 device.inventory.collect、trackside_ap_optical_update 任务链和 ac_fit_ap_optical_refresh 任务链；未来候选只登记在设计中。 |
| 首个迁移点 | 先围绕 device.inventory.collect 做 replay-only 的 interface.discovery / transceiver.read 内部契约验证，保持现有 profile、命令顺序、API、任务和数据库不变。 |
| 当前是否可进入实现 | PHASE2_COMMAND_PROFILE_READY=NO。Trackside 分支合并、最新 github/main 重审和真实/回放证据门禁尚未完成。 |

### 2.2 当前问题登记

- DISCOVERED_BUG=NONE_CONFIRMED：本轮没有对现有业务行为提交缺陷修复，也没有将设计差异误报为 bug。
- OPEN_VERIFICATION_POINT：Trackside ZTE 适配器具有完整模式和 optical-fast-only 模式；当前 trackside_ap_optical_update 路径对 ZTE 使用 fast-only 分支，代码事实显示该分支采集版本、接口摘要和光模块摘要后返回，不执行完整 LLDP 命令。该行为必须在 Trackside worktree 合并后重新审计，并由明确的业务验收决定是性能策略还是业务缺口；本审查不改动它。
- BASELINE_BOUNDARY：任何 Trackside 命令/profile 结论都必须以 dirty worktree 完成合并后的最新代码和最新 github/main 为准。

## 3. 当前三条采集链路事实

### 3.1 Device Inventory

#### 入口与调度

当前入口是设备详情页的刷新接口：

~~~text
POST /devices/{device_uuid}/refresh
  -> DeviceDetailApplicationService.refresh
  -> DeviceOperationService.start
  -> resolve_device_operation_profile
  -> BackgroundJob(task_type="device_detail_collect")
  -> run_device_inventory_refresh
  -> collect_h3c_device_details
~~~

对应代码入口是：

- src/netconsole/backend/api/device_management_router.py：设备 refresh API；
- src/netconsole/application/device_detail.py：Application Service；
- src/netconsole/services/device_operation_service.py：Operation/Profile 解析、任务计划和 worker；
- src/netconsole/services/job_center/handlers/device_jobs.py：device_detail_collect Handler 注册；
- src/netconsole/services/h3c_collect_service.py：H3C/ZTE 设备详情采集和写入。

#### Profile、命令和能力边界

这是目前三条链路中唯一已经由 resources/device_command_profiles.json 作为正式 catalog 管理的采集链路。schema 为 2026.07.device-command-profiles.v1，稳定 Operation 为 device.inventory.collect。

当前 catalog 中的 readonly profile 是：

| 厂商/角色 | 平台和选择 | Profile | 关键命令 |
| --- | --- | --- | --- |
| H3C switch | Comware，generic 或已支持的 major version | h3c.comware.switch.generic.device-inventory.v1 | screen-length disable、sysname/version/device/manuinfo/boot-loader、interface、transceiver、transceiver manuinfo、transceiver diagnosis、LLDP list/verbose |
| H3C wireless controller | Comware，generic 或已支持的 major version | h3c.comware.wireless_controller.generic.device-inventory.v1 | 与 H3C switch inventory 合同相同，但角色选择不同 |
| H3C mobile router | Comware | h3c.comware.mobile_router.generic.device-inventory.v1 | 到 display boot-loader 为止；不假设 optical/LLDP 能力 |
| ZTE switch | ZXR10，generic 或已支持的 major version | zte.zxr10.switch.generic.device-inventory.v3 | show version、show interface brief、running-config/VLAN、show opticalinfo brief、LLDP brief/entry |

device_command_profile_service.py 对厂商、角色、平台、软件主版本和 profile binding 做规范化和 fail-closed 选择。未知厂商、角色、平台、版本歧义或提交的 profile binding 不匹配时，不自动猜测命令。

command_guard.py 对 device.inventory.collect 使用 inventory command sequence 和上下文校验。命令目录校验还覆盖危险字符、未经允许的 pipe、危险模式和上下文不匹配。当前实现的安全边界是“profile 的精确 sequence + guard 的 allowlist”，不是任意 Capability 名称可以自由展开为命令。

#### Collector、Parser 和持久化

collect_h3c_device_details 根据已绑定 profile 执行命令，保存 raw output，并按厂商进入不同解析路径：

- H3C：系统身份、版本、设备信息、接口、transceiver/DOM 和 LLDP，由 H3C parser 及 h3c_lldp_parser.py、h3c_optical_parser.py 等契约解析。
- ZTE：设备身份、接口、optical summary、VLAN 和 LLDP brief/entry 由 ZTE parser 解析；可选的 per-interface optical detail 使用受 guard 约束的动态只读命令。

写入侧以 DeviceFactRepository 为主，包含：

- DeviceFactDTO 对应的设备事实：系统名、型号、序列号、MAC、软件/BootROM、厂商、uptime、采集时间；
- 接口、光模块、LLDP neighbor 等设备事实集合；
- DeviceRepository 的设备身份和关联信息。

当前 API 的 DeviceDetailDTO 将这些事实作为设备详情的一部分返回。DeviceLldpNeighborDTO 已包含规范化本地接口、邻居 chassis/system/MAC/port/interface、关联状态、采集时间等字段，但这些字段的语义仍是“被盘点设备观察到的邻居”，不等于车站/AP 业务链路。

#### 失败语义

- profile 解析、兼容性或 guard 失败：在执行前 fail closed；
- 单命令失败或解析失败：记录 per-command/per-parser 错误，能保留的事实仍可形成 partial_success；
- 没有可用事实时：任务为 failed；
- 设备身份、接口、optical、LLDP 的持久化属于设备事实域，不产生 Trackside 的站点/AP 匹配结论。

### 3.2 Trackside Optical / LLDP

#### 入口与复合任务

当前入口是 Trackside AP 业务页的更新接口：

~~~text
POST /rail-transit/trackside-ap-business/update
  -> RailTransitWebApplicationService.start_trackside_ap_update
  -> BackgroundJob(task_type="trackside_ap_optical_update")
  -> run_trackside_ap_optical_update
  -> collect_trackside_optical
     ├─ station switch targets -> TracksideSwitchAdapter
     └─ FIT-AP targets -> AcOpticalService / collect_h3c_fit_ap_optical
~~~

对应代码入口是：

- src/netconsole/backend/api/trackside_ap_business_router.py：Trackside 业务更新 API；
- src/netconsole/application/rail_transit/web_application_service.py：站点/AP 精确身份、范围、锁和任务启动；
- src/netconsole/services/job_center/handlers/rail_transit_jobs.py：Trackside Handler 注册；
- src/netconsole/services/rail_transit/trackside_ap_update_job.py：完整 business snapshot、worker 和结果汇总；
- src/netconsole/services/rail_transit/trackside_optical_collection.py：switch/FIT-AP 两个并行分支、目标构建和持久化；
- src/netconsole/adapters/trackside_switch.py：H3C/ZTE Trackside adapter；
- src/netconsole/models/trackside_switch.py：内部 collection/profile/capability 模型；
- src/netconsole/models/api/trackside_ap_business.py：Trackside switch adapter catalog 和业务投影 DTO。

这不是单一“交换机采集”任务，而是一个由完整站点/AP 业务快照约束的复合任务。它在同一个更新范围内同时处理车站交换机侧事实和 FIT-AP 侧事实，最后形成业务投影；这也是不能简单把 Trackside 命令 profile 改为 Device Inventory profile 的直接原因。

#### Trackside 命令来源和 Adapter

Trackside 命令目前由独立的 TracksideCommandProfile、adapter 采集计划和 TRACKSIDE_OPTICAL_COMMANDS/guard context 管理，不在 resources/device_command_profiles.json 中。当前已确认的 profile 是：

| Adapter | 目标 | Profile 特征 | 当前 trackside_ap_optical_update 关注点 |
| --- | --- | --- | --- |
| H3CTracksideSwitchAdapter | H3C Comware 车站交换机 | h3c_comware_trackside_v1；interface brief、transceiver diagnosis、LLDP list，并支持 interface detail 模板 | 采集 switch 接口、光模块和 LLDP；LLDP 是 AP 关系证据之一 |
| ZteZxr10TracksideSwitchAdapter | ZTE ZXR10，含 5960X-ES 适配信息 | zte_zxr10_5960x_es_v2；version、interface/optical brief/detail、LLDP brief/entry | 当前 worker 对 ZTE 传入 optical_fast_only=True，因此 fast-only 路径在摘要采集后返回；完整 adapter 模式另有 per-port 和 LLDP 计划 |

TracksideSwitchAdapter 统一的是 adapter 生命周期和采集结果形状：目标、身份、接口、LLDP、optical、warnings、per-port errors、coverage/status 等；它没有把 Trackside 业务的站点、AP、前后向衰耗或冲突判断塞进 parser。

采集前仍通过 command_guard.validate_command_list(..., context="trackside_switch_collect") 约束命令。H3C 当前核心只读命令集合包括 screen-length disable、display interface brief、display transceiver diagnosis interface、display lldp neighbor-information list；ZTE 具有 show version、接口、optical 和 LLDP brief/entry 等候选命令。厂商和平台不同，不能只通过一个“optical”标签推断命令相同。

#### Parser、身份和业务投影

- H3C adapter 复用接口、transceiver diagnosis、LLDP 的低层 parser；
- ZTE adapter 复用 ZXR10 的身份、接口、optical、LLDP parser，并处理 brief/detail、per-port error 和 LLDP 状态；
- 目标身份由站点范围、设备 UUID、厂商、管理地址和已解析身份共同约束；
- AP 与交换机邻居关系需要 Trackside 的 identity matching 和 conflict/ambiguous 语义，不能由通用 LLDP parser 决定。

内部结果包括 TracksideDeviceCollectionResult、TracksideOpticalSessionResult 和 TracksideSwitchCollection 一类的 collection 结果。面向 API 的 TracksideSwitchAdapterDTO/TracksideSwitchAdapterCatalogDTO 展示 adapter adaptation/verification/capability 状态；面向业务的主投影是 TracksideApBusinessRowDTO，包含站点一致性、交换机接口、LLDP 观察、AP 身份、光功率、正反向衰耗、计算状态、快照时间和严重度等字段。

#### 持久化与失败语义

车站交换机成功结果仍可能写入 DeviceFactRepository 的接口、optical、LLDP 事实，但 collect run 类型和调用域标识为 Trackside switch；共享物理事实存储不代表它成为 Device Inventory 的结果。FIT-AP 结果写入 AcRepository 的 FIT-AP optical 数据，并在查询/刷新时结合交换机事实和身份索引形成 Trackside/AC 视图。

失败模型是目标级和会话级的：

- 单目标 skipped、失败、per-port error、LLDP 状态和 warnings 必须保留；
- identity ambiguous、站点范围冲突和快照不完整必须 fail closed，不允许模糊匹配或跨站点猜测；
- 复合任务可以在部分目标成功时返回 partial 结果，同时保留业务快照覆盖率、持久化错误和历史/当前边界；
- trackside_ap_optical_update 依赖完整的 Trackside business snapshot，不能把一次不完整读取当作全站点空数据覆盖。

### 3.3 FIT-AP Optical

#### 入口、Application Service 和 Worker

FIT-AP 有独立的 AC refresh 入口：

~~~text
POST /ac/refresh/{refresh_kind}  (refresh_kind="optical")
  -> AcWebApplicationService.start_refresh
  -> BackgroundJob(task_type="ac_fit_ap_optical_refresh")
  -> ac_fit_ap_optical_refresh
  -> AcOpticalService.refresh_fit_ap_optical
  -> collect_h3c_fit_ap_optical
  -> AP Telnet collection + FIT-AP parser + identity matching
~~~

对应代码入口是：

- src/netconsole/backend/api/ac_management_router.py：AC refresh API；
- src/netconsole/application/ac/web_application_service.py：refresh kind、AC/AP 目标和任务参数；
- src/netconsole/services/job_center/handlers/ac_jobs.py：ac_fit_ap_optical_refresh Handler；
- src/netconsole/services/ac/ac_optical_service.py：refresh/load/single/all 编排和 snapshot 查询；
- src/netconsole/services/h3c_ac_collect_service.py：FIT-AP 目标枚举、AP 连接、命令执行和写入；
- src/netconsole/parsers/h3c/ac/fit_ap_optical_parser.py：AP 侧 LLDP/transceiver 输出解析。

#### 命令侧事实

AcOpticalService 是 orchestration service；实际 FIT-AP 命令由 collect_h3c_fit_ap_optical 对在线 AP 资源建立 AP Telnet 目标执行，不应把它描述为“AC SSH 上执行的相同 optical 命令”。当前受 guard 约束的 FIT_AP_OPTICAL_COMMANDS 是：

~~~text
screen-length disable
display lldp neighbor-information list
display transceiver diagnosis interface
~~~

这些输出的 CLI 侧是 FIT-AP/AP 资源，不是被盘点的车站交换机。解析器先得到 AP 侧邻居和 transceiver 观测；交换机匹配、反向匹配、冲突、unknown、partial 等业务判断在 collector/service 层完成。

#### Parser、Repository 和 API DTO

parse_fit_ap_optical 组合 FIT-AP LLDP 和 transceiver 解析，输出的是 AP 侧/邻居侧的中间字典，不直接产出站点业务行。Collector 将结果与当前 AC/AP resource、交换机 LLDP/身份索引相联，成功结果写入 AcRepository 的 fit_ap_optical 数据。

AcOpticalService.load_optical_snapshot 读取 AC/AP 资源和 optical 结果，并可从 DeviceFactRepository 补充 source switch 的 optical status。当前 API DTO 分工为：

- AcOpticalDTO：AP 光功率、交换机 RX/TX 状态、阈值、严重度、数据新鲜度、source switch/interface 和错误信息；
- AcLldpDTO：AP 与交换机之间的 LLDP/接口/MAC/端口/VLAN/匹配和 optical 投影；
- AcCurrentLldpDTO：当前 AP MAC、本地接口、邻居 MAC/interface、邻居设备和采集时间。

这些 DTO 是 AC/FIT-AP 查询投影，不是 DeviceLldpNeighborDTO 或 DeviceDetailDTO 的替代品。

#### 失败语义

- AP 目标、AC 归属、在线状态和当前 debug device 不满足条件时不执行或跳过；
- 单 AP 连接、命令、解析或匹配失败按 AP 记录；
- collector 支持 retry、partial/cancel 语义，成功的当前结果和边界由现有刷新/快照规则保护；
- AP 邻居无法唯一匹配交换机时返回 unknown/conflict，不以 MAC/名称模糊猜测站点或设备；
- 任务级结果可为 success、partial_success 或 failed，查询 DTO 还会表达数据新鲜度和异常原因。

## 4. 命令、解析、DTO 和失败模型对照

下表只描述当前实现和领域语义，不表示本阶段要改造为统一实现。

| 能力/语义 | Device Inventory | Trackside Optical / LLDP | FIT-AP Optical |
| --- | --- | --- | --- |
| LLDP | 被盘点设备观察到的邻居事实；H3C list/verbose 或 ZTE brief/entry | 车站交换机观察到的 AP/链路关系证据；当前 H3C update 路径使用 LLDP，ZTE fast-only 路径不执行完整 LLDP | AP/FIT-AP 侧观察到的邻居证据，之后参与 AP↔交换机匹配 |
| Interface | 被盘点设备的接口 inventory，接口状态/描述/能力等 | 车站交换机接口及 AP-facing 端口，参与站点/AP 业务行 | AP 侧或邻居侧用于 optical/LLDP 关联的接口，不是交换机全量 inventory |
| Optical RX | 设备侧 transceiver/DOM 的 RX 观测 | 交换机端口 optical，随后可参与正反向链路/衰耗计算 | AP 侧 optical，并可补充 source switch 状态；采集侧、方向和业务含义不同 |
| Optical TX | 设备侧 transceiver/DOM 的 TX 观测 | 交换机端口 optical，可能与 AP 侧观测组成链路计算 | AP 侧或关联侧 TX 观测；由 AC/FIT-AP DTO 投影 |
| Neighbor | 通用设备 LLDP neighbor，关联状态是设备事实关联 | 站点范围内的交换机邻居，必须经过严格 AP/交换机身份和冲突规则 | AP 侧邻居，必须结合 AC/AP resource 和交换机索引匹配 |
| AP mapping | 不属于 inventory 业务；可保留 generic neighbor_device_uuid，不推出 AP 业务关系 | 是核心业务语义，包含 AP UUID/MAC/name、匹配状态、规则和冲突 | 是采集目标和业务关系的一部分，目标来自 AC/AP resource |
| Station mapping | 不属于通用 device inventory | 是核心范围约束和业务投影字段；要求站点一致性 | 通过 AC/AP 资源和 Trackside 关系参与，不由 AP parser 单独决定 |
| Radio relation | 当前 inventory LLDP/optical 不建立无线 radio 业务关系 | 当前 optical/LLDP collector 不直接拥有 radio 关系 | optical DTO 不直接拥有 radio 关系；若其他 AC DTO 有无线字段，不能倒推为 optical 原语 |
| Parser | H3C device parser/LLDP/optical parser 或 ZTE device parser | H3C/ZTE Trackside adapter 加通用低层 parser；adapter 负责采集计划和结果状态 | FIT-AP LLDP/transceiver parser；匹配在 collector/service |
| DTO | DeviceFactDTO、DeviceLldpNeighborDTO、DeviceDetailDTO 及接口/optical 集合 | 内部 TracksideDeviceCollectionResult 等；API TracksideSwitchAdapterDTO、TracksideApBusinessRowDTO | AcOpticalDTO、AcLldpDTO、AcCurrentLldpDTO |
| Failure model | profile/guard fail closed；per-command/per-parser 错误；可 partial_success；无事实则 failed | target skipped/failed、warnings、per-port/LLDP 状态、snapshot coverage、identity conflict 和持久化错误 | AP 级连接/命令/解析/匹配失败；retry/cancel；success/partial_success/failed；保留当前/新鲜度语义 |

### 4.1 可以共享的低层字段

未来若建立中性 evidence contract，下面字段可以作为候选共享字段，但不应直接改名覆盖现有 DTO：

- interface_name 和 normalized_interface_name；
- neighbor_mac、neighbor_system_name、neighbor_interface_name、neighbor_port_id；
- rx_power_dbm、tx_power_dbm、对应阈值和模块状态；
- observed_at/collected_at、source_device_uuid/source_ap_uuid、采集侧和协议；
- parse_status、evidence_status、warnings、raw_output_ref；
- vendor、platform、软件版本和 profile/adapter 标识。

共享字段必须明确单位、采集侧、接口方向、空值原因和原始证据引用。尤其不能把 rx_power 这个相同名字当作相同物理方向，也不能把交换机端口的 neighbor_interface 当作 AP 端口的同义字段。

### 4.2 必须保留的领域字段

下列字段不应进入通用 Capability 结果，或只能以 domain extension 形式存在：

- 站点 ID/名称、计划与实际一致性、站点范围和业务快照 revision；
- AP UUID/MAC/name、AC UUID、AP 在线状态和 AP 资源归属；
- LLDP/AP 身份匹配规则、matched/unresolved/conflict/ambiguous 及反向匹配结果；
- forward/reverse optical loss、计算状态、衰耗原因和业务严重度；
- AC/FIT-AP current/recent/history、数据新鲜度和刷新来源；
- Device Inventory 的设备事实版本、设备详情任务历史和设备级关联；
- Trackside 的会话覆盖率、目标级 skipped、持久化错误和完整 snapshot 保护；
- FIT-AP 的 AP 级 retry/cancel/partial 记录。

## 5. Capability 统一边界判断

### 5.1 LLDP：部分统一

LLDP 可以在 parser 原语层部分统一：不同输出都可以归一为本地接口、邻居 chassis/system/MAC、邻居端口、VLAN/能力、采集时间、解析状态和原始证据。

但下列语义不能统一：

1. Device Inventory 的 owner 是一台被盘点的网络设备，LLDP 结果是它的设备事实。
2. Trackside 的 owner 是车站交换机和站点/AP 业务范围，LLDP 是 AP 端口匹配和正反向链路证据。
3. FIT-AP 的 owner 是 AP/FIT-AP 资源，LLDP 是 AP 侧证据，需要和 AC/AP resource 及交换机索引二次匹配。

所以推荐共享 LldpEvidence 一类低层记录，但每个领域必须拥有自己的 DeviceLldpFact、TracksideLinkEvidence、FitApNeighborObservation 包装和关联服务。禁止通用 parser 直接返回 station_id、ap_uuid 或业务 matched 结论。

### 5.2 Optical：部分统一

Optical 可以在 measurement 原语层部分统一：接口/模块标识、RX/TX 功率、单位、阈值、模块状态、采样时间和 raw evidence 可以由稳定的低层 schema 表达。

不能统一的部分包括：

- 设备 inventory 的 transceiver 盘点与 Trackside 的链路两端衰耗计算不是同一 Operation；
- Trackside 交换机 optical 与 FIT-AP/AP optical 的采集侧和方向相反或不同；
- 厂商的 brief/detail、接口 detail、阈值输出和版本命令并不等价；
- source_switch、AP 匹配、站点范围、forward/reverse loss 和 severity 是业务投影，不是 optical parser 的职责；
- 既有 DeviceFactRepository 与 AcRepository.fit_ap_optical 的写入边界、current/recent/history 规则不可因字段相似而合并。

推荐共享“测量字段 + 单位 + 证据状态”，保留三个领域各自的采集计划、解析适配、匹配和 projection。

### 5.3 H3C/ZTE 与版本差异是硬边界

当前至少存在：

- H3C Comware switch/wireless controller/mobile router 的不同角色 profile；
- H3C Trackside Comware adapter 的独立命令/解析计划；
- ZTE ZXR10 inventory profile 与 Trackside 5960X-ES adapter 的不同命令和 detail/LLDP 计划；
- FIT-AP AP Telnet 的 H3C AP CLI 命令。

software_version="*" 的 generic profile 只表示当前 catalog 已批准的 generic inventory 合同，不代表未来所有 Capability 都可以使用通配版本。凡是命令、输出格式、分页行为或字段含义可能随平台/major version 变化，都必须通过 profile selector、实机 evidence 或 replay fixture 验证；无法确认时 fail closed。

## 6. 推荐分层

推荐采用五层边界。这里的 Capability 是设计对象，不是本阶段要创建的代码接口。

~~~text
目标身份/证据上下文
        ↓
Capability Contract + vendor/platform/version Profile + Command Guard
        ↓
领域 Collector / Adapter
        ↓
厂商 Parser Contract -> 中性低层 evidence
        ↓
领域匹配、持久化、历史和 API DTO projection
~~~

### Layer 0：Target Identity and Evidence Context

每次 capability 解析至少需要：

- vendor、role、platform、软件版本/major version；
- 目标 UUID、站点/AC/AP 范围、采集侧（device/switch/AP）；
- 协议、管理地址、端口和安全上下文；
- real-device status、profile binding、raw evidence reference。

Layer 0 的职责是拒绝未知或歧义目标，不用名称、MAC 片段或跨站点相似度猜测目标。

### Layer 1：Command Capability Contract

建议的初始 vocabulary 是语义能力，而不是命令名称：

- interface.discovery
- neighbor.discovery
- transceiver.read
- transceiver.detail.read
- device.identity.read

每个能力契约应描述：

- 适用 vendor/role/platform/version 和 privilege；
- 前置命令、命令顺序、分页/交互要求、超时和并发约束；
- 只读/受控写风险分类及 command_guard 规则；
- 输出 parser contract、必需字段、允许 partial 的条件；
- raw evidence、coverage、warnings 和失败状态。

Capability 不能返回业务级 AP/站点关系，也不能绕过现有 profile resolver 和 guard。命令的最终展开仍由领域拥有的 profile/adapter 完成。

### Layer 2：Domain Operation

当前 Operation/task 仍按领域保留：

- device.inventory.collect：设备详情和设备事实；
- trackside_ap_optical_update：Trackside 业务复合刷新任务类型；
- ac_fit_ap_optical_refresh：AC/FIT-AP optical 刷新任务类型。

未来若产品真的需要单独的 interface/LLDP/transceiver 刷新，才考虑新增 Operation；不能为了抽象 Capability 而把现有 inventory、Trackside、FIT-AP 的任务拆碎。

### Layer 3：Parser Contract

Parser 只负责将已确认的厂商输出转换为稳定低层 evidence，并返回 parse status、warnings、raw reference 和缺失字段原因。Parser 不负责：

- AP/交换机/站点的唯一身份决策；
- 业务匹配或 fuzzy fallback；
- forward/reverse loss 和 severity；
- Repository 写入和 API DTO 组装。

H3C/ZTE 每个版本族仍可以有自己的 parser contract；“共享字段”不要求“共享所有正则和所有输入格式”。

### Layer 4：Domain Repository and DTO Projection

领域 service 根据 evidence 完成匹配、去重、历史/current/recent 规则、持久化和 DTO projection。允许多个领域读取/补充物理层事实，但必须保留 collect type、source side、owner、revision 和失败状态，避免用一次 partial 采集覆盖另一领域的 current 数据。

## 7. 未来 Operation 候选

以下只是候选命名和边界，不是本阶段新增的 Operation，也不改变当前 API/任务。

| 候选 Operation | 目标范围 | 应包含 | 明确不包含 | 建议 |
| --- | --- | --- | --- | --- |
| device.interface.collect | 已登记的 managed device | 设备接口发现和接口事实 | AP 侧接口、Trackside 站点映射、链路衰耗 | 可作为低风险第一个内部 capability 迁移候选；先不暴露新 API |
| device.lldp.collect | 已登记的 managed device | 设备侧 LLDP neighbor facts | AP/站点匹配、AC resource、反向链路业务 | 只有在产品需要独立刷新且能与 inventory 去重后再新增；当前 inventory 已包含 LLDP |
| device.transceiver.collect | 已登记的 managed device | device-side transceiver/DOM facts | AP optical、Trackside loss、站点/AP 业务 | 可作为 transceiver.read 的领域包装；先保持 inventory 写入边界 |
| wireless.ac.fit_ap.optical.collect | AC/AP resource 及其 AP Telnet 目标 | FIT-AP/AP 侧 optical、AP 侧 LLDP、AC/AP 归属 | 车站交换机全量 inventory、通用 device facts | 未来如需独立 AC API，沿用 AcOpticalService 的边界 |
| rail.trackside.switch.optical.collect | 站点范围内精确识别的车站交换机 | switch-side optical/LLDP、coverage、identity/conflict、业务关联所需证据 | 通用 managed-device inventory、跨站点 fuzzy match | 未来可作为 Trackside 内部 operation；必须等待 dirty worktree 合并和重新审计 |

### 7.1 Operation 命名原则

- device.* 只表达 managed device 事实，不隐含 AP/站点业务；
- wireless.ac.fit_ap.* 明确采集 owner 和 AP 侧；
- rail.trackside.* 明确站点/轨旁业务范围；
- collect 只描述领域结果，不把一组命令名称当 Operation；
- 现有 trackside_ap_optical_update 和 ac_fit_ap_optical_refresh 是当前任务/业务入口，迁移时需要兼容别名、幂等、锁和历史语义，不能直接重命名。

## 8. 低风险迁移路线

### Phase A：契约冻结（本文件）

- 固定三条链路的 command source、parser contract、DTO、repository 和 failure model；
- 固定 Capability vocabulary 只作为设计术语，不产生运行时代码；
- 明确设备侧、交换机侧、AP 侧和业务投影的 owner。

### Phase B：Replay fixture 证据包

为每个版本/设备族建立最小、脱敏、可回放的 raw output fixture：

- H3C Comware switch inventory；
- H3C Comware Trackside switch；
- ZTE ZXR10 inventory（当前 catalog 的 C89E-4 evidence）；
- ZTE Trackside 5960X-ES 的 fast/full 和 LLDP 差异；
- FIT-AP AP Telnet 的 LLDP/transceiver 输出；
- unknown version、命令缺失、分页异常、身份歧义和 partial output。

fixture 只用于测试和 parser contract 验证，不复制 D:/NetConsoleData 或 D:/NetConsoleData-dev，不连接真实设备。

### Phase C：内部只读 Capability 描述

在不改变现有 Operation、profile JSON、guard、API、Repository 和 DTO 的前提下，未来可以先为已有命令计划增加内部描述：

- device.inventory.collect 仍负责实际调度；
- H3C/ZTE profile 仍负责命令绑定和版本选择；
- Adapter/collector 仍负责目标身份、raw output、parser 和领域失败状态；
- Capability 只用于将“interface discovery / transceiver read / neighbor discovery”与输出 evidence 对齐。

此阶段以 replay fixture 和现有定向测试为完成条件，不以真实设备连通作为唯一证据。

### Phase D：先迁移 Device Inventory 的一个低风险 Capability

推荐先验证 interface.discovery 或 transceiver.read，理由是：

- 目标是单设备，不包含站点/AP 业务身份匹配；
- device.inventory.collect 已有正式 profile catalog 和 guard sequence；
- 失败可以保留为 device fact partial，而不会直接改变 Trackside 业务行或 AC/AP 关系；
- 可以用现有 H3C/ZTE raw fixture 对 parser 和字段单位做回放。

迁移必须保持旧路径可回退，并证明 profile id/version、命令顺序、raw evidence、partial_success 和 DeviceFactRepository 写入一致。

### Phase E：再验证 Trackside Adapter

Trackside 必须在 codex-A/trackside-optical-filter 合并、刷新最新 github/main 并重新生成 impact matrix 后才进入。优先只抽取 adapter 的 capability descriptor，不改变：

- 站点/AP 精确身份和 conflict/ambiguous fail-closed；
- H3C/ZTE 的独立 profile 和 fast/full 计划；
- 完整 snapshot、coverage、current/history 和 persistence error 语义；
- Trackside API DTO 和业务计算。

ZTE fast-only 是否允许缺少 LLDP，必须由业务验收明确，并为 fast/full 分别建立 fixture；不能由 Capability 抽象自动“补上”或静默改变流量。

### Phase F：最后处理 FIT-AP 和跨域 projection

FIT-AP 需要先稳定 AP Telnet 连接、retry/cancel/partial、AC/AP resource 和匹配索引，再考虑将 AP 侧 evidence 与交换机侧 evidence 放到同一链路模型中。第一阶段只允许共享 evidence 字段，不改变 AcRepository、DeviceFactRepository 或现有 DTO。

### Phase G：只有明确产品需求才拆 Operation/API

新增 device.lldp.collect 或 rail.trackside.switch.optical.collect 前，必须有独立的 API、幂等、锁、任务历史、权限/feature gate、数据覆盖和兼容迁移设计。Capability 抽象本身不是新增用户功能的理由。

## 9. 风险登记

评分：概率/影响均使用低、中、高、严重；每项必须在后续实现前由测试或验收证据关闭。

| 风险 | 概率 | 影响 | 具体表现 | 建议 |
| --- | --- | --- | --- | --- |
| 过度抽象 | 高 | 高 | 为三个领域建立一个万能 command/profile，隐藏目标侧、权限、版本和失败边界 | 只共享 capability vocabulary 和 evidence 原语；profile/adapter/operation/domain service 保持独立 |
| Parser 重复 | 中 | 高 | 为共享 DTO 复制 H3C/ZTE 正则，或为了去重强行共用不兼容 parser | 先共享 parser contract 和 fixture；代码复用以输入格式和版本证据为前提，不以字段同名为前提 |
| DTO 过度统一 | 高 | 高 | Device、Trackside、FIT-AP 都输出一个 neighbor/optical DTO，丢失 AP/站点/采集侧/方向语义 | 保留 domain DTO；只在内部 evidence 层使用带单位、source side 和 status 的稳定字段 |
| 厂商命令差异 | 高 | 高 | H3C display...、ZTE show...、AP Telnet CLI 被同一 capability 展开为错误命令 | capability 必须由 vendor/platform/version profile 绑定；未知绑定或 guard 失败立即 fail closed |
| 版本差异 | 高 | 高 | generic * 被误当成所有 Comware/ZXR10 版本都兼容；输出格式/分页/字段漂移 | 保留 major-version selector、profile id/version 和实机/replay evidence；不得自动 fallback 到相似版本 |
| 真实设备证据不足 | 高 | 严重 | 离线 fixture 通过但现场设备命令不支持、权限不同或 AP/交换机拓扑不同 | 发布前分开报告 replay、自动化、GUI/安装和真实设备验收；未经实机证据不得宣称现场通过 |
| 历史兼容性 | 中 | 高 | 抽取 capability 时覆盖 current/recent/history、快照 revision、partial 保留或重复写入抑制 | 先证明 collect type/source/owner/revision 不变，再考虑 repository 共享；不得恢复已退役 Legacy HistoryStore |
| Trackside dirty worktree 漂移 | 高 | 高 | 以未提交 Trackside optical diff 设计 profile/capability，合并后命令或失败语义变化 | 等待分支完成、push、merge、刷新 github/main 后重新生成 impact matrix |
| 复合任务边界丢失 | 中 | 高 | 把 Trackside 的 switch + FIT-AP 并行任务拆成单一 optical 结果，导致 coverage/identity/persistence 错误 | 保持复合任务和两个 source side；Capability 仅描述低层采集，不拥有复合编排 |

## 10. Phase 2 进入条件

进入后续实现前必须全部满足：

1. codex-A/trackside-optical-filter 的 dirty 状态完成收口，变更已 push/merge。
2. 从最新 github/main 重新读取 AGENTS.md、baseline 和 command semantic matrix，并重生成 impact matrix。
3. 对 H3C/ZTE Device Inventory、Trackside adapter、FIT-AP AP Telnet 建立最小脱敏 replay fixture。
4. 确认 command_guard 仍是最终安全门，Capability 不会绕过 profile resolver、profile binding、危险命令拒绝和版本 fail-closed。
5. 明确每个 evidence 字段的采集侧、单位、方向、owner、raw reference 和缺失原因。
6. 明确 DeviceFactRepository、AcRepository.fit_ap_optical、Trackside projection 的读写边界以及 current/recent/history 兼容要求。
7. 先完成 Device Inventory 单一低风险 capability 的回放设计，再评估 Trackside 和 FIT-AP；不以全量抽象作为 Phase 2 的完成标准。
8. 真实设备、GUI、安装、打包和发布验收另行记录，不与本设计文档的自动化/回放结论混合。

## 11. 最终审查结论

- DEVICE_INVENTORY=REVIEWED：已有正式 JSON profile、resolver、guard、collector、parser、DeviceFactRepository 和 DTO 边界；适合作为第一个低风险内部 capability 试点。
- TRACKSIDE=REVIEWED_WITH_MERGE_GATE：已有独立 TracksideCommandProfile、H3C/ZTE adapter、严格身份/快照/失败语义；必须等 dirty worktree 合并后重审，不能迁移为 Device Inventory profile。
- FIT_AP=REVIEWED：实际是 AP Telnet 采集 + FIT-AP parser + AC/AP/交换机匹配 + AcRepository/AC DTO projection；不得按 AC SSH 或通用设备 optical 处理。
- LLDP=PARTIALLY_UNIFIABLE：只统一低层 neighbor evidence，保留三个领域的 owner、匹配和 projection。
- OPTICAL=PARTIALLY_UNIFIABLE：只统一带单位的 measurement evidence，保留采集侧、方向、阈值解释和业务计算。
- OPERATION_RECOMMENDATION=KEEP_CURRENT：当前不新增、不重命名、不拆分 Operation/task；候选只作为后续产品需求的设计输入。
- FIRST_MIGRATION_POINT=DEVICE_INVENTORY_REPLAY_ONLY：先验证 interface.discovery 或 transceiver.read 的内部契约，零 API/DB/任务行为变化。
- PHASE2_COMMAND_PROFILE_READY=NO：尚未满足 Trackside 合并、最新主干重审、fixture 和验收门禁，当前不应进入命令 profile 迁移实现。
