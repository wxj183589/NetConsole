# Interface Discovery Migration Contract

## 评审状态

- 阶段：`PHASE 2D-PREPARATION`
- 范围：仅为 Device Inventory 的 `interface.discovery` 设计未来迁移契约
- 基线：`codex-A/engineering-hardening`，前置评审提交 `89997e9b91e1c753793e4b0469bc4f1e3302d739`
- 性质：只读设计；不实施迁移，不切换生产入口
- 当前正式 Operation ID：`device.inventory.collect`
- `PHASE2D_PREPARATION_STATUS=PASS`
- `PHASE2D_READY=NO`

`interface.discovery` 是未来 Command Capability 的内部语义名称，不是新增的
Operation ID、API、DTO 或 Feature Flag。Legacy 在本文中指当前正式设备库存采集路径，
不指已退役的 Legacy HistoryStore；Legacy HistoryStore 不得重新进入 runtime。

## 1. 事实来源与边界

本契约以代码、测试和现有专题文档为准：

- [Device Inventory capability inventory](./device-inventory-capability-inventory.md)
- [Device Inventory Legacy/Profile equivalence](./device-inventory-migration-equivalence.md)
- [Device Inventory parser contract](./device-inventory-parser-contract.md)
- [Device Inventory snapshot contract](./device-inventory-snapshot-contract.md)
- [Command Capability design review](./command-capability-design-review.md)
- `src/netconsole/application/device_detail.py`
- `src/netconsole/services/device_operation_service.py`
- `src/netconsole/services/device_command_profile_service.py`
- `src/netconsole/services/h3c_collect_service.py`
- `src/netconsole/repositories/device_fact_repository.py`
- `src/netconsole/parsers/h3c/interface_parser.py`
- `src/netconsole/parsers/zte/zxr10.py`
- `src/netconsole/parsers/zte/vlan.py`
- `src/netconsole/services/interface_retention.py`

只评估 `device.inventory.collect` 内的接口事实，不接管以下业务：

- Trackside 交换机/AP 业务行、站点范围、身份匹配、正反向光衰或 LLDP 拓扑；
- FIT-AP/AP 侧接口、光模块、LLDP 和 AC/AP 资源关系；
- MR、MESH、Train、车载或任何跨站点业务投影；
- 生产采集、Profile JSON、Collector、Adapter、Parser、DTO、Repository、API、UI、
  数据库、版本、打包和真实设备连接。

## 2. Legacy Interface Discovery

### 2.1 当前路径

当前设备详情刷新链路为：

```text
设备刷新请求
    ↓
DeviceDetailApplicationService.refresh
    ↓
DeviceOperationService.start
    ↓
resolve_device_operation_profile
    ↓
device_detail_collect Worker / run_device_inventory_refresh
    ↓
resolve_device_inventory_profile + command guard
    ↓
collect_h3c_device_details
    ↓
Profile ordered command execution
    ↓
existing vendor Parser
    ↓
interface normalized dict
    ↓
DeviceFactRepository.replace_device_interfaces
```

Worker 要求单次设备详情刷新只包含一台设备，并在执行前重新校验提交的
Profile ID/version。Profile resolver 对 vendor、role、platform、software major 和
profile binding 进行规范化，无法确认时 fail closed；`command_guard` 对最终命令序列、
上下文、危险字符、未授权 pipe 和禁止命令继续执行安全校验。

### 2.2 当前接口命令来源

接口命令不是自由字符串，也不是 Capability 名称直接展开的结果，而是既有
`resources/device_command_profiles.json` 经 resolver 绑定后的有序步骤：

| 设备族 | 当前 selector / step | 命令 | 相关补充输入 |
|---|---|---|---|
| H3C Comware switch / wireless controller | `device.interfaces.collect` → `inventory.interfaces` | `display interface` | 由同一 H3C inventory Profile 选择；不把角色差异抹平 |
| H3C Comware mobile router | `device.interfaces.collect` → `inventory.interfaces` | `display interface` | 仅使用 mobile router Profile 已批准的接口范围；不推导 optical/LLDP |
| ZTE ZXR10 switch | `device.interface-brief.collect` → `inventory.interface_brief` | `show interface brief` | `inventory.switchvlan_config` / `inventory.vlan_table` 由当前 Profile 作为 VLAN enrichment 输入 |

`screen-length disable` 或其它分页准备步骤属于 operation envelope，不是接口 DTO。
ZTE 的 `show running-config switchvlan`、`show vlan` 不是另一套接口身份，它们只能通过
当前已有的 `merge_interface_vlan_facts` 补充接口 VLAN 字段和 warning/status。

### 2.3 Parser 与 normalized result

- H3C `H3CParser.parse_interfaces` 委托现有 H3C interface parser；能够处理完整接口
  输出，也能识别已支持的 brief 形态，产出 `interface_name` 及状态、描述、速率、双工、
  VLAN/IP 等字段。
- ZTE `parse_interfaces` 解析 `show interface brief`，产出
  `interface_name`、`normalized_name`、媒体、双工、带宽/速率、admin/physical/protocol
  状态、`oper_status`、description、category 等字段，并返回 parser status/warnings。
- ZTE VLAN parser 只在相应输入 status 为 `OK` 时参与 merge；PVID 冲突、继承字段和
  unavailable 状态必须保留，不能由 Capability 比较器猜测或消除。
- Parser 不产生 `station_id`、`ap_uuid`、Trackside match、FIT-AP relation 或链路衰耗。

当前生产 collector 不直接把 parser dict 当作新的公共 DTO。设备详情查询将当前事实
映射到 `DeviceInterfaceDTO`；`DeviceDetailDTO.interfaces` 当前以 dict list 承载接口
集合。未来等价比较使用本文定义的 test/design-only normalized DTO，不修改现有 DTO。

### 2.4 Repository 写入点与 retention

唯一的当前接口写入入口是 `DeviceFactRepository.replace_device_interfaces`，其行为为：

| 视图/层 | 当前事实 |
|---|---|
| Current | `device_interfaces` 按 `device_uuid + interface_name` 保存最新接口事实；快照为空或接口名为空时拒绝写入，避免覆盖上一份有效数据；新快照中不存在的接口从 Current 删除 |
| Recent | 当前接口没有独立 `device_interface_recent` 表；活动的 Recent10 语义由接口 retention 的有界 change-only history 提供，不能另造第二份 Recent |
| History | `device_interfaces_history` 只在 `state_fingerprint` 发生有效变化时新增记录，保留该接口最近 10 条有效变化和 `previous_state_json`；重复状态不新增 history |
| Runtime metadata | `collected_at`、`updated_at`、`collect_run_uuid`、`raw_log_path`、`source_revision` 等用于来源/运行和写入追踪，不能变成 normalized DTO 的业务差异 |

接口 state fingerprint 基于现有 `INTERFACE_STATE_FIELDS`；采集时间和运行 ID 不参与
state fingerprint，`vlan_config_collected_at` 也不作为接口状态变化依据。相同有效接口
状态再次写入时，Current 的 last-seen 语义可更新，但不应产生重复 Recent/History。

## 3. Target Capability Path

### 3.1 未来目标路径

未来可在不新增 Operation 的前提下，将接口发现描述为内部 Capability：

```text
same device request and frozen profile context
    ↓
interface.discovery capability resolver
    ↓
existing profile resolver / command guard
    ↓
command execution
    ↓
existing H3C or ZTE interface Parser
    ↓
Interface Discovery Normalized DTO
    ↓
existing DeviceFactRepository write contract
```

Capability resolver 只负责把已确认的设备、厂商、角色、平台、软件版本和接口能力
绑定到现有命令计划；它不能绕过 `resolve_device_inventory_profile`、Profile version、
command guard 或现有取消/错误边界。Command Capability 不是新 Collector、Parser、DTO
或 Repository。

目标路径必须复用现有 Parser 和写入 contract：

- 不复制 H3C/ZTE 正则或用字段同名强行共用 parser；
- 不把 ZTE VLAN enrichment 抽成无来源的通用字段；
- 不把接口结果投影为 Trackside/FIT-AP/AP 关系；
- 不为能力本身增加 `device.interface.collect`、API 或任务类型；
- 不在本阶段实现 resolver、执行器、开关或写入分支。

### 3.2 Profile 与命令安全不变量

未来 capability path 的输入应携带已经冻结的：

1. `operation_id=device.inventory.collect`；
2. `profile_id`、`profile_version`、vendor/role/platform/software selector；
3. 当前 profile 产生的接口命令和顺序；
4. `command_guard` context、超时、分页和取消语义；
5. raw evidence reference 与每个 selector 的 status。

其中 1–4 是 command/profile 等价门，不纳入 normalized DTO 值相等，但缺失或不一致
必须阻止迁移。未知版本、歧义 binding、未授权命令和不支持输出均 fail closed，不向
相似厂商或相似版本 fallback。

## 4. Interface Discovery Normalized DTO Contract

这是未来 Legacy/Profile 等价比较使用的稳定投影，不是生产新增 DTO。顶层只保留接口
事实 section，运行态、原始命令和 Repository 元数据单独处理。

```json
{
  "interfaces": [
    {
      "interface_name": "<stable parser identity>",
      "normalized_name": "<existing normalized identity>",
      "category": "<existing interface category>",
      "link_status": null,
      "admin_status": null,
      "physical_status": null,
      "protocol_status": null,
      "media_attribute": null,
      "media_type": null,
      "speed": null,
      "duplex": null,
      "interface_type": null,
      "port_status": null,
      "port_mode": null,
      "pvid": null,
      "native_vlan": null,
      "tagged_vlans": [],
      "untagged_vlans": [],
      "pvid_source": null,
      "pvid_verified": null,
      "vlan_config_status": null,
      "vlan_warnings": [],
      "description": null,
      "ip_address": null,
      "mac_address": null,
      "vlan": null,
      "last_change": null
    }
  ]
}
```

### 4.1 Required

每个非空接口 record 必须有：

- `interface_name`：已有 Parser/Repository 使用的非空接口身份；
- `normalized_name`：现有接口归一化键；H3C 若当前 parser 结果尚未显式提供，未来
  projection 必须按现有 DTO 映射补齐，不能使用另一套名称算法；
- `category`：现有 `DeviceInterfaceDTO` 的必需分类字段；
- 顶层 `interfaces` collection：空集合必须由明确的空/缺失状态表达，而不是省略
  section。

`DeviceInterfaceDTO` 的 API 字段 `name` 与 normalized contract 的
`interface_name` 是映射关系：未来必须证明 `name == interface_name` 的业务身份不变，
但不能借此修改生产 DTO。

### 4.2 必须比较、但值可为空

下面字段不是当前 Pydantic DTO 的 structural required 字段，但只要当前 Parser 或
Profile 提供了它们，Legacy 与 Capability 必须逐字段一致；一侧有值、另一侧缺失或
变为不同值都算 mismatch：

- `link_status`、`admin_status`、`physical_status`、`protocol_status`；
- `speed`、`duplex`、`media_attribute`、`media_type`；
- `interface_type`、`port_status`、`port_mode`；
- `pvid`、`native_vlan`、`tagged_vlans`、`untagged_vlans`、`pvid_source`、
  `pvid_verified`；
- `vlan_config_status`、`vlan_warnings`、`description`、`ip_address`、`mac_address`、
  `vlan`、`last_change`。

“可为空”只表示当前厂商输出可能没有该字段或值；不表示比较器可以任意忽略字段。
`status` 和 `speed` 属于必须比较的稳定接口事实：若当前一侧产生，另一侧必须产生
相同的 normalized value；不能用“接口名称相同”掩盖状态或速率偏差。

字段值规则：

- `null`、空字符串和缺失字段不是默认等价；只有现有 Parser/DTO projection 已定义
  的归一化才可等价；
- 接口列表顺序沿用现有 normalized contract 的稳定顺序；比较器不读取 raw CLI 来
  重排，也不通过相似名称猜测记录对应关系；
- `normalized_name` 负责身份键，不能用 casefold、前缀或模糊匹配替代现有归一化；
- speed、VLAN、status 的单位、字符串和值域沿用现有 Parser contract，不在迁移时
  隐式换算；
- API DTO 的 `name`、`normalized_name`、`category` 和接口稳定字段必须能从同一条
  normalized record 投影，不能由两个路径分别补默认值。

### 4.3 Ignored

以下字段不参与 normalized DTO 业务事实比较：

- raw command、raw CLI、raw output、raw output reference 和机器路径；
- `collected_at`、`observed_at`、`timestamp`、`started_at`、`ended_at`；
- `duration_ms`、`execution_duration_ms`、`session_id`、`collect_run_uuid`、
  `task_id`、runtime metadata；
- Repository 自身的数据库 `id`、`state_json`、`state_fingerprint` 和写入时间。

忽略 raw command 不等于忽略命令契约：Profile ID/version、selector 绑定、命令顺序、
guard 结果、raw evidence 覆盖和失败语义必须在 DTO 比较之外单独通过 gate 验证。
`source_revision`、history revision 和 current/recent/history effect 也不进入 DTO 值
相等，但必须在 Repository Impact Contract 中比较。

## 5. Shadow Mode 设计

### 5.1 Shadow Flow Diagram

```text
Refresh request
    ↓
Freeze device + operation + profile context
    ├──────────────────────────────────────────────┐
    ↓                                              ↓
Legacy Collector path                         Capability path
    ↓                                              ↓
existing command execution                    read-only command execution
    ↓                                              ↓
existing Parser                               existing Parser
    ↓                                              ↓
Normalized DTO A                              Normalized DTO B
    ↓                                              ↓
Legacy is the only Repository writer          Equivalence Compare
    │                                              ↓
    └────────────── production response        shadow diagnostics only
```

Shadow 的生产不变量是：

- 用户可见结果、任务终态和 Repository current/recent/history 仍来自 Legacy；
- Capability path 旁路只读，不能调用 `replace_device_interfaces`、
  `append_interface_history` 或其它 Repository 写入入口；
- compare 失败只能产生迁移诊断和 gate failure，不得覆盖 Legacy 结果；
- Shadow 不默认启用；当前没有已确认的 Device Inventory 迁移 Feature Flag，本阶段
  不添加任何开关。

### 5.2 Shadow 两级执行

1. Replay shadow：先使用同一 Fixture/selector 输入，让 Legacy/Profile 两侧复用现有
   Parser，比较 normalized DTO、status/warning 和字段缺失。此阶段不连接设备、不写库。
2. Controlled read-only shadow：Replay gate 通过并具备批准的现场 evidence 后，才可在
   受控设备范围内执行两条只读命令路径。两侧应使用同一冻结 profile context，Capability
   侧受独立超时、取消和并发预算约束；新增一次设备连接或命令执行的影响必须单独批准。

Controlled shadow 不是当前任务授权的真实设备测试，也不是本阶段要实现的运行模式。

## 6. Repository Impact Contract

### 6.1 Shadow 阶段

Shadow 阶段严格保持单写者：

| 区域 | Shadow 规则 | 预期影响 |
|---|---|---|
| Current | 只有 Legacy 调用现有 `replace_device_interfaces` | 与未开启 Shadow 的 Current 完全一致 |
| Recent | 不由 Capability 写入；不新增第二个接口 Recent 表 | 无重复 Recent；unchanged state 不产生新记录 |
| History | 只有 Legacy 根据现有 state fingerprint 生成 change-only history | history 数量、previous state 和 bounded limit 不变 |
| Source/revision | Capability 的 run/session/reference 仅进入旁路诊断 | 不改变 Repository state fingerprint 或 history revision |

因此 Shadow compare 的 Repository effect 必须是“Capability 写入调用次数为 0”，而不
是“两个路径都写入后再删除一份”。

### 6.2 未来切换阶段

只有 Shadow gates 全部通过后，才允许把 Capability 作为同一 Repository contract 的
单一写入者；Legacy 和 Capability 不得双写。切换必须回答：

1. **Current 是否会变化？** 只有 normalized DTO 与 Legacy 等价、接口集合和空快照
   保护一致时，Current 才允许产生与 Legacy 相同的更新；路径标签本身不能改变
   Current。
2. **Recent 是否会重复？** 不应重复。接口 Recent10 没有独立表；现有 fingerprint
   只对有效接口 state 变化记录一次。相同状态即使 collect run 不同，也不得插入第二条
   change record。
3. **History revision 是否变化？** 不因 Capability 路径、session 或 run ID 自动
   变化。只有真实接口 state fingerprint 变化才新增一条 history，并携带与 Legacy
   兼容的 `source_revision`；同一状态不得制造虚假 revision。
4. **是否需要去重？** 不新增第二套 dedup。继续使用现有接口身份键和 state
   fingerprint；如果等价结果需要额外去重，说明 DTO 或写入契约尚未冻结，禁止切换。
5. **是否需要 migration window？** 需要。先有 bounded replay/shadow window，再有
   限定设备范围的 single-writer canary window；两个 window 都必须有 owner、开始/结束
   commit、Profile version、失败阈值和回滚点。不能长期保持两个生产 writer。

### 6.3 Current/Recent/History 不变量

- 空接口集合或空接口名不能由 Capability 变成覆盖 Current 的成功快照；继续保留
  `replace_device_interfaces` 的保护。
- 新快照遗漏的接口只在 Legacy 已确认的完整有效快照语义下从 Current 删除；partial、
  parser failed 或 command unsupported 不能被误当作完整空快照。
- 不修改已有 history，不以重新解析或“修正快照”伪造历史 revision；发现错误时走
  受控备份/恢复和数据修复流程，不在 Capability 中添加补偿写入。
- 不恢复 Legacy HistoryStore，不创建独立的 Capability history 表。

## 7. Equivalence Rules

### 7.1 比较输入

```text
Migration Before:
Legacy path
    ↓
existing H3C/ZTE interface Parser
    ↓
Interface Discovery Normalized DTO A

Migration After:
Command Capability interface.discovery
    ↓
existing H3C/ZTE interface Parser
    ↓
Interface Discovery Normalized DTO B
```

两侧必须使用相同的目标 identity、版本/Profile context、Parser contract 和 normalized
projection 规则。比较入口可复用现有 `device_inventory_equivalence` scaffold，但
scaffold 不启动 Collector、不连接网络、不写数据库。

### 7.2 DTO 比较规则

- 比较接口集合的 cardinality、稳定 identity、`normalized_name`、`category` 和所有
  已提供的稳定接口字段；
- status、speed、duplex、VLAN、description 等一侧可为空但必须可解释；值/缺失差异
  不能通过扩大 Ignored 清单消除；
- 保持现有字段类型、单位、列表顺序和 warning/status 表达；不在 compare 阶段做
  vendor fallback、模糊身份匹配、raw 重排或猜测补全；
- `DeviceInterfaceDTO` 的必需字段必须能从两侧投影得到；extra/missing stable field
  默认视为契约差异，因为 API model 使用 `extra="forbid"`；
- 0 个接口必须结合 selector status 判断是合法 EMPTY、MISSING、PARSE_FAILED 还是
  命令失败，不能仅比较空数组。

### 7.3 DTO 之外的等价检查

Normalized DTO 相等不是迁移通过，还必须分别检查：

- Profile ID/version、selector binding、命令顺序和 command guard 结果；
- 每个接口 selector 的 raw evidence、分页完成度、unsupported/缺失原因和 warnings；
- Legacy/Capability 的 task outcome、partial_success、failed、cancel 和 timeout
  语义；
- Legacy 单写与 Capability 零写的 Repository effect；切换后 Current、Recent10、
  history fingerprint/count/previous state 的对照；
- 与 Trackside/FIT-AP/MR/MESH 的零交叉写入和零业务投影变化。

## 8. Failure Strategy

| Legacy | Capability | 生产处理 | 迁移处理 |
|---|---|---|---|
| 成功 | 失败/超时/取消 | 采用 Legacy 结果，正常保留当前生产任务语义 | Capability 只记 shadow failure；不写 Current/Recent/History；gate FAIL |
| 失败 | 成功 | 仍按 Legacy 失败，不能自动把旁路成功升级为生产成功 | 保留两侧 raw/status 供调查；不推广 Capability；gate FAIL |
| 成功 | 成功但 DTO 或 Repository effect 不一致 | 仍返回 Legacy，Capability 不成为写入者 | 记录 mismatch；要求定位字段、命令、版本或 retention 差异后重跑 |
| 失败 | 失败 | 保持当前 Legacy failed/partial/cancel 处理 | 不产生 candidate 写入；按 Legacy 错误责任链调查 |
| 任一侧发生共享取消 | 另一侧可结束 | 不能因旁路取消改变 Legacy 已有终态规则 | Capability 旁路应尽快停止；取消/超时不被标成等价通过 |

Capability path 的连接异常、Parser 异常、字段 mismatch 和 compare 异常都必须被隔离
在 shadow 诊断边界内，不能吞掉 Legacy 错误，也不能以旁路成功掩盖 Legacy 失败。

## 9. Rollback Plan

### 9.1 切换前

- Legacy collector、现有 Profile、Parser、DTO、Repository contract 必须保留；任何
  缺少 Legacy fallback 的候选不得进入生产切换。
- Shadow 阶段只读，任何 mismatch 直接停止候选推进，不需要恢复数据库，因为
  Capability 没有写入。
- 切换前必须由现有数据库/存储治理流程完成受控的 pre-switch backup、Current/Recent10/
  history fingerprint 清单和 writer quiescence；没有可验证的备份、owner 或恢复路径就
  不切换。

### 9.2 切换后发现问题

1. 先停止 Capability writer；如果未来已有合适的 internal switch，则关闭该路径。当前
   未确认存在此专用开关，本阶段不新增 Feature Flag 或 internal switch。
2. 恢复 Legacy 为唯一生产写入者，暂停正在执行的候选 writer，等待任务/连接按现有
   取消和 shutdown 语义收敛。
3. 读取并对照切换前 fingerprint、Current、Recent10/有界 history、history limit 和
   `previous_state_json`；不使用重新采集“修复”历史，不删除未知来源的历史记录。
4. 若候选已经写入并造成数据偏差，按现有受控数据库备份/恢复流程恢复 pre-switch
   snapshot；恢复前后都要验证单写者、数据库完整性、Current、Recent10、history 和
   active site 边界。该恢复不是本契约新增的数据库操作。
5. 回滚后重新执行 Legacy 定向回归和 Repository retention 对照；未能证明恢复完整
   时，保持生产入口在 Legacy，标记迁移阻塞，不继续重试切换。

### 9.3 三类数据保护

- Current：Shadow 不变；切换后异常以 pre-switch snapshot 恢复，不用部分 Capability
  输出覆盖旧 Current。
- Recent：不允许双写或重复 change record；恢复时保持最新 10 条有效变化记录语义。
- History：不清空、不重建、不从 raw command 猜测；只通过已有受控备份/恢复路径回退。

## 10. Migration Gates

以下是未来 `Phase 2D-A` 开始前的门禁定义，不是本阶段已完成的迁移：

| Gate | 必须满足 |
|---|---|
| G1 Replay | H3C Comware 7/9、ZTE 5960X 和已批准的现场脱敏 Fixture 对接口 selector 回放通过；empty/error/partial/truncated/repeatability 均 PASS |
| G2 Golden | Golden snapshot structural contract、Required/Optional/Ignored 字段 contract 和无自动更新规则均 PASS |
| G3 Equivalence | Legacy/Profile normalized DTO 零 unexplained mismatch；接口 cardinality、identity、status、speed、VLAN 和字段缺失均已解释 |
| G4 Command/Profile | `device.inventory.collect` Operation、Profile ID/version、selector、命令顺序、guard、分页和版本 fail-closed 行为一致 |
| G5 Repository impact | Shadow Capability 写入次数为 0；切换候选的 Current、Recent10、history fingerprint、change-only 和空快照保护已完成隔离对照 |
| G6 Shadow | 在批准的 bounded window 内 Legacy 成功结果稳定，Capability 旁路无未解释失败或 mismatch；失败不影响 Legacy 任务终态 |
| G7 Rollback | Legacy fallback、writer stop、pre-switch backup、恢复 owner、quiescence 和恢复后数据校验已演练 |
| G8 Real evidence | 目标 vendor/role/platform/software version 有批准的真实设备证据；离线 replay 不能替代该门禁 |
| G9 Regression | docs/path、相关 Replay、Main Contract 和适用 baseline/consumer gate 绑定同一最终 HEAD，`NEW_FAILURES=0` |

当前状态：已有 Replay、Golden contract 和 equivalence scaffold；G3/G5/G6/G7/G8 尚未
完成生产级验证，因此本阶段只冻结契约，不宣告 Phase 2D 实施就绪。

## 11. Risk Assessment

| 风险 | 概率 | 影响 | 措施 |
|---|---|---|---|
| 命令差异 | 高 | 高 | 继续由现有 Profile resolver 和 command guard 产生精确命令；比较 profile binding、顺序和 raw evidence，不允许 Capability 自由展开 |
| 字段缺失 | 中 | 高 | Required identity 字段缺失立即 mismatch；Optional 字段用明确 null/status 表达，不用默认值掩盖缺失 |
| Parser 偏差 | 中 | 高 | 两侧复用现有 Parser；先 Replay/Golden，再比较 status、warning、字段集和异常输入；禁止复制正则绕过 contract |
| Repository 重复写入 | 中 | 严重 | Shadow 单写者；Capability 零写；切换后也只保留一个 writer，验证 fingerprint 和调用次数 |
| 历史数据污染 | 中 | 严重 | 不把 run/time/source 当 state；沿用 change-only bounded history；切换前备份，回滚不重建/删除历史 |
| 版本差异 | 高 | 高 | 固定 vendor/role/platform/software selector 和 Profile version；未知或歧义版本 fail closed；补齐批准 Fixture/real evidence |
| 回滚困难 | 中 | 严重 | Legacy 永久保留；切换前要求 backup、owner、quiescence 和恢复演练；没有可验证恢复路径则不切换 |

## 12. 本阶段完成边界

本文只完成 Interface Discovery 的未来迁移契约：

- Legacy Path：已定义；
- Capability Path：已设计，未实现；
- Normalized DTO Contract：已定义，未新增生产 DTO；
- Shadow Mode：已设计，未实现、未连接设备；
- Repository Impact：Current、Recent10/有界 history、History 已定义单写者与等价规则；
- Failure Strategy：已定义；
- Rollback Plan：已定义，未执行；
- Migration Gates：已定义，尚未全部满足。

本阶段不修改 `device.inventory.collect`、Collector、Adapter、Parser、DTO、Repository、
API、UI、Profile JSON、Operation、数据库或 Feature Flag，不切换生产入口，不连接真实
设备，不打包、不改版本。
