# Device Inventory Capability Inventory

## 评审结论

- 评审阶段：`PHASE 2C-PREPARATION`
- 评审范围：仅 `device.inventory.collect` 的内部 Device Inventory 能力
- 评审基线：`codex-A/engineering-hardening`，`13ff2a3eaaf4571cf7423508fcd66857becb168f`
- 本文性质：迁移候选评审，不是迁移实施方案，不改变当前生产路径
- `FIRST_MIGRATION_CANDIDATE=interface.discovery`
- `PHASE2D_READY=NO`

结论中的 `interface.discovery` 是未来 Command Capability 的候选名称，不是新的
Operation ID。当前唯一正式 Operation ID 仍为 `device.inventory.collect`。

## 1. 范围与事实来源

本评审只覆盖设备详情采集产生的本机设备事实：身份/软件、硬件事实、接口、光模块
和 LLDP 邻居证据。以下边界不在评审范围内，也不能由本候选覆盖：

- Trackside AP、FIT-AP 的拓扑、光模块或 LLDP 关联
- MR、MESH 及其业务关联
- 任何跨站点设备身份推断、AP 归属推断或业务状态写入

代码与契约事实来自以下位置：

- 入口链：`src/netconsole/application/device_detail.py`、
  `src/netconsole/services/device_operation_service.py`
- Profile 解析与映射：`src/netconsole/services/device_command_profile_service.py`、
  `resources/device_command_profiles.json`
- 命令安全边界：`src/netconsole/services/command_guard.py`
- 正式采集与解析写入：`src/netconsole/services/h3c_collect_service.py`
- 当前/历史持久化：`src/netconsole/repositories/device_fact_repository.py`
- API DTO：`src/netconsole/models/api/device_management.py`、
  `src/netconsole/models/api/device_detail.py`
- 回放与快照：`tests/support/device_inventory_replay.py`、
  `tests/support/device_inventory_snapshot_contract.py`、
  `tests/support/device_inventory_equivalence.py`

## 2. 当前 operation envelope

当前刷新链路为：

```text
DeviceDetailApplicationService.refresh
    -> DeviceOperationService.start
    -> run_device_inventory_refresh
    -> resolve_device_operation_profile / command guard
    -> collect_h3c_device_details
    -> vendor parser
    -> DeviceFactRepository current + bounded history
```

当前 Profile Catalog 中有四个 `device.inventory.collect` 绑定：

| Profile | Selector | Parser | DTO contract | 现场验证状态 |
|---|---|---|---|---|
| `h3c.comware.switch.generic.device-inventory.v1` | H3C / switch / comware / `*` | `netconsole.h3c.device-inventory.v1` | `netconsole.device-inventory.v1` | `REAL_DEVICE_PENDING` |
| `h3c.comware.wireless_controller.generic.device-inventory.v1` | H3C / wireless_controller / comware / `*` | `netconsole.h3c.device-inventory.v1` | `netconsole.device-inventory.v1` | `REAL_DEVICE_PENDING` |
| `zte.zxr10.switch.generic.device-inventory.v3` | ZTE / switch / zxr10 / `*` | `netconsole.zte.zxr10-switch.v3` | `netconsole.device-detail.v1` | `REAL_DEVICE_VERIFIED` |
| `h3c.comware.mobile_router.generic.device-inventory.v1` | H3C / mobile_router / comware / `*` | `netconsole.h3c.mobile-router-device-inventory.v1` | `netconsole.device-inventory.v1` | `REAL_DEVICE_PENDING` |

Profile 中的 `session.pagination` 只是分页准备步骤，不产生业务 DTO；它不单独构成
迁移候选。`include_zte_optical_detail=True` 产生的
`inventory.optical_detail::<interface>` 是现有采集器的可选动态扩展，不属于普通
Profile 的固定步骤，也不作为第一迁移点。

当前 Profile JSON 没有 `capabilities` 字段。当前 capability API 中的
`DeviceCapabilityDTO` 描述 SSH/Telnet/SNMP 传输支持，并不是 CLI 采集出来的设备库存
事实，因此不把它伪装成 `device.inventory.collect` 的迁移候选。

## 3. Device Inventory Capability Inventory

下表的“迁移风险”是未来将该能力从现有采集器路径抽取为 Command Capability 时的风险，
不是当前实现的缺陷评级。当前入口均仍归属于同一个既有 Operation；表中列出的内部
entry/selector 是已有映射，不是要新增的 Operation ID。

| Capability | 当前入口 | 命令来源 | Parser | DTO | 持久化 | 错误模型 | Replay 覆盖 | 迁移风险 |
|---|---|---|---|---|---|---|---|---|
| Device identity / software version | `device.sysname.collect` → `inventory.sysname`；`device.version.collect` → `inventory.version` | H3C：`display current-configuration \| include sysname`、`display version`；ZTE：`show version` | H3C `parse_sysname`、`parse_device`；ZTE `parse_zte_device_identity` | `DeviceFactDTO` 的 `system_name`、`model`、`software_version` 等 | `upsert_device_fact`；身份字段同步 `DeviceRepository` | Profile 解析或 guard 失败则 fail closed；版本/身份不可识别可造成失败或 partial；无有效事实时整体失败 | H3C Comware 7/9、ZTE 5960X synthetic；ZTE C89E-4 `REAL_CAPTURE` 覆盖 version | Medium：身份事实被多个后续 resolver 使用，不适合作为最先隔离的写入面 |
| Hardware / slot / manufacturing facts | `device.slot.collect` → `inventory.device`；`device.manufacturing.collect` → `inventory.manuinfo` | H3C：`display device`、`display device manuinfo`；ZTE Profile 不提供同名步骤 | H3C `parse_device`、`parse_manuinfo` | `DeviceFactDTO` 及 Repository `FACT_FIELDS` 中的 model/serial/vendor 等 | `upsert_device_fact` 与 dynamic fact change 记录 | H3C 各事实块独立捕获 parse error；可能仍返回其他成功事实；无有效 facts 时整体失败 | H3C 7/9 synthetic；没有对应 H3C 现场 Fixture | High：H3C 专有输出和字段空值语义较多，且事实与身份/版本合并写入 |
| Boot loader / image facts | `device.boot-loader.collect` → `inventory.boot_loader` | H3C：`display boot-loader`；ZTE Profile 无同名步骤 | H3C `parse_boot_loader` | `DeviceFactDTO.bootrom_version` 及已有事实字段 | `upsert_device_fact`；没有独立表或新字段 | 该解析块单独记录 parse error；保留已有 bootrom 值的行为由当前 collector/repository 语义决定 | H3C Comware 9 Fixture 有命令；无现场证据 | High：输出版本差异大、业务价值窄，不适合承担首个迁移试点 |
| Interface inventory | `device.interfaces.collect` → H3C `inventory.interfaces`；ZTE `device.interface-brief.collect` → `inventory.interface_brief` | H3C：`display interface`；ZTE：`show interface brief`，并可选 `show running-config switchvlan`、`show vlan` 做 VLAN enrichment | H3C `parse_interfaces`；ZTE `parse_zte_interfaces`、`parse_zte_vlan_*`、`merge_interface_vlan_facts` | `DeviceInterfaceDTO`（必需 `name`、`normalized_name`、`category`）；详情响应当前承载为 dict list | `replace_device_interfaces`；current + bounded history，拒绝空快照并删除已不在新快照的 current 名称 | 命令失败可形成 partial；解析/写入异常记录 parse error；H3C 空接口快照被 Repository 拒绝并保留上一份有效数据；ZTE 仅在接口结果 OK 且非空时写入 | H3C 7/9、ZTE 5960X synthetic；C89E-4 `REAL_CAPTURE` 覆盖 `interface_brief`；有 empty/error/partial/truncated/repeatability 边界测试 | Low–Medium：输出边界明确、DTO 必需字段少、与业务拓扑无直接写入；主要风险是 H3C/ZTE 命令和 VLAN enrichment 差异 |
| Transceiver / optical evidence | `device.transceivers.collect` → H3C `inventory.transceivers`；ZTE `device.optical-brief.collect` → `inventory.optical_brief`；H3C 另有 manuinfo/diagnosis；ZTE 另有可选 detail | H3C：`display transceiver interface`、`display transceiver manuinfo interface`、`display transceiver diagnosis interface`；ZTE：`show opticalinfo brief`；detail 为可选动态命令 | H3C `parse_optical_repository`；ZTE `parse_zte_optical_summary`、detail merge、`merge_zte_optical_snapshot` 及 severity/threshold 语义 | `DeviceTransceiverDTO`（必需 `interface_name`、`normalized_interface_name`、`severity`）；Repository `OPTICAL_MODULE_FIELDS` 承载 vendor/threshold/DOM 字段 | `replace_optical_modules`；current + bounded history；ZTE 做 snapshot merge/preserve-existing | 命令或解析异常可 partial；空光模块快照被拒绝；ZTE 依赖 summary/detail 状态并可能保留上一快照；阈值、severity、设备报告状态都可能影响健康展示 | H3C 7/9、ZTE 5960X synthetic；C89E-4 `REAL_CAPTURE` 覆盖 optical brief；未覆盖动态 optical detail 的完整现场语义 | Medium–High：字段多、阈值和 snapshot/history 语义复杂，错误会改变设备健康证据 |
| LLDP / neighbor evidence | H3C `device.lldp-summary.collect` / `device.lldp-detail.collect` → `inventory.lldp_list` / `inventory.lldp_verbose`；ZTE 对应 `lldp-summary` / `lldp-detail` | H3C：`display lldp neighbor-information list`、`display lldp neighbor-information verbose`；ZTE：`show lldp neighbor brief`、`show lldp entry` | H3C `parse_lldp`；ZTE `parse_zte_lldp_*` 并按 brief/detail 状态合并 | `DeviceLldpNeighborDTO`（必需 `local_interface`、`normalized_local_interface`；可选 neighbor/association 字段） | `replace_lldp_neighbors`；按 local interface merge current + bounded history，可保留未观察项的显式缺失语义 | 列表/详情可分别失败；ZTE 按 brief/detail/NO_NEIGHBOR 选择快照；错误时整体可 partial；不能把邻居证据自动升级为业务关联 | H3C 7/9、ZTE 5960X synthetic；边界含空、错误、截断、重复；C89E-4 现场 Fixture 的 LLDP 输出为空，不构成现场 LLDP 证据 | Medium–High：解析可回放，但 list/detail 合并、邻居键和缺失语义需要先冻结；不能越过 Trackside/FIT-AP 边界 |

### 当前能力与非能力边界

`DeviceFactRepository` 的 current、bounded history、raw log 和 collect run 是采集
基础设施。它们不是可以随意共享的通用 Capability DTO：current/recent/history 的
更新语义必须随候选逐项验证。尤其是 `replace_optical_modules` 与
`replace_lldp_neighbors` 的保留/删除/缺失语义不能仅凭解析结果等价推出。

`DeviceCapabilityDTO` 与设备库存事实分开处理。它只表达可用传输能力；本评审不把
SSH/Telnet/SNMP capability metadata 排名，也不将其作为新增 CLI capability。

## 4. Capability Migration Score

评分采用“风险评分”：`Low` 表示该维度迁移风险较低，`High` 表示必须先补充门禁或
证据。`Replay coverage` 的 `Low` 也表示覆盖不足；不是代码质量分数。

| 排名候选 | 生产影响范围 | Parser 稳定性 | Replay 覆盖程度 | DTO 稳定程度 | 真实设备证据 | 版本差异风险 | 回滚难度 | 综合判断 |
|---|---|---|---|---|---|---|---|---|
| `interface.discovery` | Low | Medium | Low（覆盖充分） | Medium | Medium | Medium | Low | 最适合首个试点，但仍需 H3C 现场证据和双路径写入对照 |
| `neighbor.discovery` | Medium | Medium | Low（覆盖充分） | Medium | High（不足） | High | Medium | 可作为第二候选；先冻结 list/detail、邻居键和缺失语义 |
| `transceiver.read` | Medium | Medium–High | Low（覆盖充分） | Medium | Medium | High | High | 延后；DOM/threshold/severity 与 current/history 需要更强护栏 |

表中“Replay 覆盖程度”按风险记分：四个基础 Fixture、Golden contract 和边界测试已
使三项候选的回放维度达到“覆盖充分”，所以显示为风险 `Low`。这不等于真实设备或
生产写入已经验收。

## 5. 候选能力分析

### 5.1 Interface Inventory — `interface.discovery`

这是推荐的首个迁移点，理由是它可以保持在单设备、单证据域内：

- H3C 只有一个主要接口输出 `display interface`；ZTE 以
  `show interface brief` 为主，VLAN enrichment 是已有的独立输入，不需要把
  Trackside 或 AP 关联带入。
- H3C 与 ZTE 已有解析器和确定的接口归一化边界，实际 API DTO 的必需身份字段只有
  `name`、`normalized_name`、`category`。
- Repository 已经有非空快照保护、current/history 写入和删除遗漏 current 的明确
  语义，未来可在等价验证中逐项比较，且不需要数据库字段变更。
- Replay 已覆盖 H3C 7/9、ZTE 5960X 和 C89E-4 现场脱敏接口片段，并覆盖空、错误、
  partial、截断和可重复性边界。

主要风险仍然存在：H3C 现场验证待补，ZTE VLAN enrichment 不能被误简化为接口
基础事实，接口名称归一化和空快照保护必须在迁移前保持不变。首个迁移只应先覆盖
既有 `inventory.interfaces` / `inventory.interface_brief` 输入；不要顺带迁移
动态 optical detail、LLDP 或跨域关联。

候选回退：新路径在双路径阶段不得独立写入生产 current/history；比较失败即保留
现有采集器作为唯一写入路径。若未来已有受控的 inventory 内部开关，则关闭新路径；
当前未发现专用迁移开关，本阶段不新增开关。

### 5.2 LLDP / Neighbor Evidence — `neighbor.discovery`

LLDP 可以作为第二个候选，因为它的产物是设备本地邻居证据，能够与接口能力按
`local_interface` 进行有限的同设备验证，并且已有 list/detail 两类输出和回放素材。

但它不能直接覆盖 Trackside LLDP 或 FIT-AP topology：

- `neighbor_device_uuid`、业务归属、站点边界和 AP 身份不是 CLI 邻居解析自然产生的
  DTO 字段，不能用模糊匹配或跨站点推断补齐。
- H3C list/verbose 和 ZTE brief/entry 是不同格式；详情缺失、无邻居和部分成功的
  合并语义必须保持，而不是仅比较邻居数量。
- 当前 C89E-4 现场 Fixture 的 LLDP 输入为空，因此 Replay 通过不代表现场 LLDP
  证据充分。

候选回退：任何邻居键、缺失状态或 association 字段差异都阻止新路径写入；恢复
Legacy collector 后只保留原有 Device Inventory LLDP current/history。Trackside 和
FIT-AP 的关联服务、快照和状态不由此候选触碰。

### 5.3 Transceiver / Optical Evidence — `transceiver.read`

光模块能力可以独立命名，但风险明显更高：

- H3C 需要 transceiver、manufacturing、diagnosis 三组命令拼接；ZTE 以 optical
  summary 为基础，还存在可选 per-interface detail。
- `DeviceTransceiverDTO` 的 `severity` 是必需字段，Repository 还保存阈值、DOM、
  设备报告状态和多个 vendor 字段；字段存在并不等于阈值解释等价。
- H3C 空快照保护、ZTE summary/detail merge、previous snapshot 保留、current/history
  更新共同决定页面看到的设备健康证据。只比较归一化列表可能漏掉“本次未观察到”
  与“保留上一份有效值”的差异。

这里的 Device Optical 仅指 `device.inventory.collect` 产生的本机光模块证据。它
不包括 FIT-AP Optical、Trackside Optical、AP 业务状态或任何拓扑关联；这些域的
collector、snapshot、status 和持久化边界均不得在未来该候选中修改。

候选回退：在新路径完成 summary/detail 的 raw evidence、severity、阈值以及
current/recent/history 等价验证之前，新路径只读比较、不写入。比较失败时保持
Legacy collector 写入；若已在受控开关下运行，则关闭新路径并确认旧 snapshot 仍是
唯一事实源。

## 6. Legacy/Profile Equivalence 设计

未来 Phase 2D 只能按现有迁移等价契约开展。Legacy 在此处指当前正式采集器路径，
不是要在本阶段退役或重新引入 Legacy HistoryStore。

```text
Migration Before:

Legacy path (existing collector)
    ↓
existing vendor Parser
    ↓
normalized DTO / existing repository write contract

Migration After:

Command Capability (same operation/profile binding)
    ↓
existing vendor Parser
    ↓
normalized DTO / existing repository write contract
```

### 6.1 比较对象

只比较与业务事实有关的 normalized DTO sections：

```text
device_identity
model
version
interfaces
optical_modules
neighbors
capabilities
```

其中 `capabilities` 只有在输入结果确实包含该 section 时才比较；当前 CLI inventory
回放不会把传输支持 metadata 当作 CLI 输出。以下运行时或来源字段不进入 normalized
DTO 等价判断：`raw`、`raw_output`、`raw_output_ref`、文件路径、采集/观察时间、
duration、session/collect/task ID 和运行 metadata。

### 6.2 必须同时验证的非 DTO 条件

Normalized DTO 相等不是迁移通过。候选切换前还必须保留并比较：

1. Profile ID、Profile version、selector 绑定，以及命令顺序和实际命令文本。
2. 每个 selector 的 raw evidence、缺失/不支持命令和分页结果。
3. 成功、partial_success、failed 的状态及首个/聚合错误信息。
4. `DeviceFactRepository` 的 current、recent、bounded history 的增删改结果，尤其
   是接口空快照、LLDP 未观察项和光模块 previous snapshot 语义。
5. 只影响当前设备 Device Inventory，不触碰 Trackside、FIT-AP、MR、MESH 或跨站点
   关联。

推荐的验证顺序是：冻结 Legacy 基线 → 对同一 Fixture 或同一受控输入执行两条只读
路径 → 复用现有 Parser → 生成 normalized DTO → 比较 raw/error/status → 在隔离
数据库 candidate 上比较 Repository effect → 通过全部门禁后才讨论生产切换。

当前已有 `device_inventory_equivalence` helper、Golden contract 和 CLI replay，
它们提供比较脚手架；它们没有替代生产双路径执行、Repository current/history 对照
或现场版本证据。

## 7. 回滚设计

所有候选共享以下回滚不变量：

- 保留当前 Legacy collector、Parser、Repository contract 和 Profile；本阶段不删除
  或替换它们。
- 双路径阶段新路径默认只读比较；任何 mismatch、未识别命令、字段漂移或持久化差异
  都禁止新路径成为生产写入方。
- 当前代码中未确认存在专用于 Device Inventory 迁移的 Feature flag/internal
  switch；不能把新的开关作为本阶段变更。若 Phase 2D 开始前已有合适的受控开关，
  只沿用该开关关闭新路径；否则保留 Legacy 为生产写入路径，并以版本/分支级回退
  作为最终保险。
- 不新增数据库字段，不迁移历史表，不清理旧 current/history，不修改其他业务域。

| 候选 | 失败判定 | 回滚动作 |
|---|---|---|
| `interface.discovery` | 接口身份字段、归一化名称、VLAN enrichment、空快照或 current/history 任一差异 | 禁止新路径写入；继续 Legacy `display interface` / `show interface brief` 采集；丢弃 candidate 输出 |
| `neighbor.discovery` | list/detail 合并、local key、无邻居/未观察项、association 字段或错误状态差异 | 关闭新路径或不启用；恢复 Legacy LLDP 写入；不修复、不重算 Trackside/FIT-AP topology |
| `transceiver.read` | summary/detail、severity、threshold、previous snapshot、current/history 任一差异 | 在受控开关下关闭新路径；保持 Legacy optical 写入和既有快照；不把 Device Optical 结果传播到 FIT-AP/Trackside |

## 8. Candidate Ranking 与推荐

| 排名 | Capability | 推荐等级 | 原因 |
|---|---|---|---|
| 1 | `interface.discovery` | Recommended for Phase 2D design | 单设备接口证据，DTO 和 Repository 边界最小；H3C/ZTE/现场片段已有回放基础；可以先做只读双路径，不需要跨域关联 |
| 2 | `neighbor.discovery` | Conditional | 证据边界清晰但 list/detail、缺失和邻居身份键风险高；当前现场 Fixture 没有 LLDP 证据 |
| 3 | `transceiver.read` | Deferred | 光模块字段、阈值、severity、summary/detail 和快照历史语义耦合；误差会改变健康证据，回滚难度最高 |

因此：

```text
FIRST_MIGRATION_CANDIDATE=interface.discovery
```

这只是未来第一个试点的评审结论，不授权现在修改 `device.inventory.collect`，也不
授权新增 Operation ID、Profile 字段、生产开关或任何 Collector/Parser/DTO。

## 9. 风险清单

1. 命令差异：H3C、ZTE 及不同软件版本的命令文本、分页和 unsupported 输出不同。
2. Parser 行为变化：接口、LLDP list/detail、光模块 summary/detail 的合并和空结果
   语义可能漂移。
3. DTO 字段变化：必需 identity/category/severity 字段、归一化名称和 vendor 字段
   不能因 Capability 抽取而改变。
4. 真实设备版本差异：当前 H3C Profile 仍为 `REAL_DEVICE_PENDING`；ZTE 现场片段
   只覆盖文件中明确存在的命令。
5. Golden 不足：Synthetic 和单个 C89E-4 `REAL_CAPTURE` 不能代表全部平台、版本和
   partial/error 组合。
6. 回滚困难：光模块和 LLDP 的 current/recent/history、保留上一快照及删除遗漏项
   的语义一旦写错，单纯重新解析无法保证恢复。
7. 生产采集影响：连接、命令 guard、任务取消、raw log、collect run 和 Repository
   写入都是现有生产链路；迁移候选不得绕过它们或扩大采集范围。

## 10. Phase 2D 进入条件

本评审可以安全地选出候选，但当前不能宣告 `PHASE2D_READY=YES`，原因是：

- H3C 真实设备证据仍待补充，且本阶段明确禁止真实设备连接。
- 当前已有的是 replay、Golden contract 和 equivalence scaffold，不是生产双路径
  执行与 current/recent/history 写入对照。
- 尚未冻结 `interface.discovery` 的未来 capability schema、Profile version、
  命令顺序和 VLAN enrichment 归属。
- 未确认已有可用于库存迁移的 Feature flag/internal switch；本阶段不新增。
- `PHASE2_COMMAND_PROFILE_READY` 当前仍不是可直接进行生产迁移的状态。

进入 Phase 2D 前至少要补齐：候选命令/版本契约、批准的 H3C 现场或等价证据、同输入
双路径回放与 Repository effect 对照、失败/partial/取消回滚演练，以及绑定同一最终
HEAD 的 docs/path、replay、main contract 和 baseline 结果。

## 11. 本阶段变更边界

本文为本阶段唯一新增文件。评审不修改生产代码、Collector、Adapter、Parser、DTO、
Profile、Operation、数据库 schema、API、UI、版本、安装包或真实数据；不建立真实设备
连接，不改变 Trackside/FIT-AP/MR/MESH。
