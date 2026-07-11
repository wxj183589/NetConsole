# AP 统一模型评估与迁移边界

## 1. 背景与结论

Job Center、Online MR、SNMP 与 AC Domain 第一阶段迁移完成后，AP 相关风险已经从任务基础设施转向数据身份：同一个物理 AP 在 FIT-AP 资源、扩展信息、光衰、轨旁、MR/Mesh、历史和导出中使用不同标识与降级匹配规则。

本轮仅完成静态评估，不修改生产模型、数据库 schema、Repository 写入语义、业务规则、导出字段或测试期望。

核心结论：

1. 当前仓库已经存在 `ap_entities`，并由 FIT-AP 资源刷新同步维护。后续不应再创建第二张“统一 AP 主表”；应先围绕现有表建立纯 identity 解析与适配层。
2. `ap_uuid` 是站点数据库内已落表 AP 的最佳内部标识，但它可能在首次无法匹配时由 `uuid4()` 生成，且不能直接替代日志中的 Radio/BSSID/Peer 身份。
3. 跨模块关联最通用的键是规范化 AP MAC；序列号更接近硬件资产标识，但覆盖率不足。AP 名称、AC 内 APID、Peer MAC 只能按来源和作用域降级使用。
4. Radio MAC、BSSID/BBSSID、Peer MAC 和 Peer Radio MAC 必须保留为 radio/观测层标识，不能折叠进 AP MAC。
5. MR 原始分析、Mesh 明细、导出、历史查询和页面展示应只读取统一 identity 结果，不应成为 AP 主身份写入者。
6. 阶段 1 已完成：新增小型、纯 Python、无数据库副作用的 identity 工具和 characterization tests，尚未接入生产流程；不得直接迁移轨旁业务。

## 2. 评估范围与静态搜索

本轮检查了以下实际路径：

- `netconsole/core/database.py`
- `netconsole/repositories/ac_repository.py`
- `netconsole/repositories/mesh_mr_repository.py`
- `netconsole/services/ac/`
- `netconsole/services/h3c_ac_collect_service.py`
- `netconsole/services/ap_extension_import.py`
- `netconsole/services/fit_ap_import_export.py`
- `netconsole/services/trackside_ap_business.py`
- `netconsole/services/rail_transit/`
- `netconsole/services/online_mr/`
- `netconsole/services/vehicle_mr_online.py`
- `netconsole/services/ap_radio_mapping_service.py`
- `netconsole/services/mesh_peer_mapping_service.py`
- `netconsole/services/network_tools/trackside_bssid_resolver.py`
- `netconsole/services/mesh_analysis_report.py`
- `netconsole/services/mesh_link_detail_export.py`
- `netconsole/services/online_mr_analysis_report_exporter.py`
- `netconsole/services/export/`
- AC、Online MR、Vehicle MR、Mesh、Trackside 相关测试

按 Python 文件统计的字段覆盖面如下。该计数只用于说明影响面，不代表字段语义一致：

| 字段 | 出现文件数 | 字段 | 出现文件数 |
| --- | ---: | --- | ---: |
| `ap_uuid` | 18 | `ap_id` | 6 |
| `apid` | 12 | `ap_mac` | 37 |
| `ap_name` | 51 | `bssid` | 26 |
| `bbssid` | 7 | `radio_mac` | 6 |
| `peer_mac` | 30 | `peer_radio_mac` | 11 |
| `device_uuid` | 45 | `ac_device_uuid` | 19 |
| `station` | 48 | `site` | 60 |
| `section` | 25 | `mileage` | 15 |
| `direction` | 36 | `lldp` | 17 |
| `optical` | 21 |  |  |

## 3. 当前 AP 数据来源

| 数据来源 | 当前写入/产物 | 身份用途 | 推荐所有权 |
| --- | --- | --- | --- |
| AC FIT-AP 资源刷新 | `ac_fit_ap_resources`、`ap_entities`、资源/Radio/LLDP 历史 | 运行态 AP 身份、名称、APID、MAC、序列号、状态、Radio/BSSID | 统一 identity 的主要运行态来源；保持现有 Repository 为唯一写入口 |
| AP 扩展信息导入 | `ap_extension_points`，部分流程按 MAC 更新 `ap_entities` 和 `ac_fit_ap_metadata` | 站点/区间/里程/方向/点位等工程属性 | 工程元数据来源；不能单独宣告物理 AP 身份，未绑定记录允许存在 |
| AC LLDP 采集 | FIT-AP 资源字段、`ac_fit_ap_lldp_history`、`ap_lldp_history` | AP 与交换机/接口的拓扑关系 | 辅助关系来源，不是 AP 主身份来源 |
| AC/AP 光衰采集 | `ac_fit_ap_optical`、光衰历史、`ap_optical_history` | AP 侧/交换机侧光功率、模块和异常状态 | 遥测来源；必须先关联到已有 AP，再写快照/历史 |
| 轨旁 AP 规划导入 | `ac_trackside_ap_plan` | 站点容量、VLAN/端口规划和轨旁范围 | 规划来源，不包含足够的物理 AP 唯一身份 |
| 轨旁业务合并 | 轨旁视图、离线台账、派生缓存/结果 | 组合 switch interface、LLDP、FIT-AP、光衰和工程属性 | 派生消费者；不得反向成为 AP 主身份真源 |
| MR/Mesh Peer 解析 | `mesh_peer_mapping`、resolve cache、解析库中的 peer 字段 | 将观测到的 Peer/Radio MAC 映射到 AP 名称、AP MAC、站点/区间 | 映射/派生来源；只能保存解析证据，不能改写 AP 主身份 |
| 车载 MR 映射导入 | `vehicle_mr_train_mapping` 等车组映射 | 车号、端别、MR 设备映射 | 不是 AP 身份来源；名称相近但职责不同 |
| 无线扫描 | BSSID 观测、扫描结果 | BSSID/Radio 到轨旁 AP 的查询匹配 | 只读观测来源，不写 AP 主身份 |
| 设备管理 | Device `device_uuid`、组和地址 | 标识 AC、交换机、MR 等设备 | 提供 AC/交换机作用域，不等同于 `ap_uuid` |

### 3.1 当前主要写入者

- `AcResourceService`、`H3cAcCollectService` 通过 `AcRepository.replace_fit_ap_resources()` 写 FIT-AP 资源，并同步 `ap_entities` 与历史。
- `FitApImportExportService` 通过 `AcRepository.import_ap_extension_points()` 写 AP 扩展信息；旧元数据模板按规范化 MAC 更新 `ap_entities`。
- H3C 光衰采集和轨旁光衰采集通过 `AcRepository.replace_fit_ap_optical()` 写当前值与历史。
- `AcRepository` 自身负责 UUID 解析、去重、metadata/extension 合并及历史落库。
- Online MR 诊断 parser 只写自己的解析库；Mesh repository 只写 peer 映射和分析派生字段。

### 3.2 当前非理想写入例外

`vehicle_mr_online.backfill_fit_ap_resource_station_from_optical()` 在加载轨旁 AP lookup 时，会按 AP 名称或 MAC 将光衰表中的站点反填至 `ac_fit_ap_resources.site`。这意味着 Online MR 的读取流程存在对 AC 主资源的副作用，并且名称匹配没有显式 AC 作用域。后续阶段应先用 characterization test 固定现状，再将其收敛到明确的 metadata 写入服务；本轮不修改。

## 4. 当前 AP 标识矩阵

| 场景 | 当前主标识/匹配顺序 | 稳定性判断 | 结论 |
| --- | --- | --- | --- |
| FIT-AP 资源 | 请求中的已存在 `ap_uuid` → `site_id + serial_number` → `site_id + ap_mac` → `site_id + ac_device_uuid + 唯一 ap_name` → 未命中的请求 UUID 或新 UUID | 已落表 UUID 最稳；序列号/MAC较稳；名称为降级；外部请求 UUID 需谨慎 | 资源页最终以 `ap_uuid` 落表，但采集原始 APID 不是 canonical identity |
| AP 扩展信息 | 内部 `id` → 规范化 AP MAC → 点位码+站点+线别+里程；资源 enrich 为 MAC → 名称 | MAC覆盖最好；点位组合是工程记录身份；名称可变 | 扩展行可在未绑定 AP 时独立存在，不能强制拥有 `ap_uuid` |
| 光衰刷新 | 优先携带/解析 `ap_uuid`，否则按同 AC 下 AP 名称找资源；合并时还会使用 AC+APID、MAC、序列号、名称 | 取决于采集 payload；名称 fallback 有重名风险 | 光衰是 AP 遥测，不应生成新的 AP 真源身份 |
| 轨旁 AP 业务 | switch `device_uuid + interface` 定位轨旁端口；AP 侧综合 serial、MAC、name、UUID、LLDP 历史 | 交换机接口是拓扑行身份，不是 AP 身份；多键优先级不统一 | 轨旁行必须同时保存 AP identity 和 topology identity |
| Online MR | 日志中的 Peer name/MAC/BSSID；lookup 由资源、光衰、metadata、`ap_entities`、cache 合并，名称或 MAC 精确匹配 | 日志标识为观测值；名称/MAC可能缺失或来源混合 | Online MR 应消费带证据的解析结果，不写 canonical identity |
| MR 原始 Mesh 分析 | `source_file_id + radio + sample_time + peer_mac_normalized` 等样本作用域；Peer resolver 映射 AP/Radio | `source_file_id` 是分析库作用域，Peer MAC 是观测身份 | `mesh_links.id`/anchor id 不是跨文件全局身份；必须保留 source file 作用域 |
| Mesh 链路明细 | 行/样本 ID + `source_file_id`，展示 Peer MAC、AP MAC、AP 名称、Peer Radio | 只用于证据展示 | 不应用明细行字段反写 AP 主数据 |
| AP 历史 | `ap_uuid` 为主；部分兼容查询可按 AP 名称 | UUID稳定，名称查询仅兼容 | 新历史接口应要求 UUID；名称只能作为旧数据 fallback |
| 导出报告 | 继承查询行字段或 selection key，常用 UUID/MAC/name/peer | 导出不是身份来源 | 只做展示命名和去重，不创建/修正 identity |

## 5. 标识稳定性判断

### 5.1 `ap_uuid`

- `ac_fit_ap_resources.ap_uuid` 和 `ap_entities.ap_uuid` 均为唯一字段，刷新时通过现有实体解析后复用。
- 它是当前站点数据库内最适合的 canonical key，但不是 AC 设备原生提供的 UUID。
- 当请求携带未命中的 UUID 时，当前 Repository 最终会接受该 UUID；未携带 UUID且序列号、MAC、唯一名称都无法命中时才生成新 UUID。因此外部 UUID、采集缺字段、名称变化或跨库导入都可能产生新实体。
- `site_id` 在部分写入路径缺失时回退为 `demo`；在 identity 工具落地前不能把不同数据库导出的 UUID/MAC 记录无条件合并。

### 5.2 `id`、`ap_id`、`apid`、FIT-AP ID

- 各表的 `id` 是 SQLite 内部行主键，只能定位该表记录。
- `ap_entities.ap_id` 来源于 payload 的 `apid/ap_id`，语义是 AC/H3C 的 APID，不是数据库行 ID。
- `apid`/FIT-AP ID 受 AC 作用域约束，可能复用或变化，只能作为 `ac_device_uuid + apid` 的运行态提示键，不能作为跨 AC 主标识。
- 当前生产 Python 代码中没有独立的 `fit_ap_uuid` 或 `fit_ap_id` 字段；对应语义分别落在 `ap_uuid` 与 `apid/ap_id`。后续不应再增加同义别名。

### 5.3 AP MAC 与序列号

- 规范化 AP MAC 是当前跨资源、扩展、轨旁和 MR 映射覆盖最广的键。
- MAC 可能缺失、格式不同、被 AP 名称字段代填，或者在硬件更换后变化；必须同时保存 raw/display 与 normalized 值，并记录 match rule。
- 序列号更接近物理硬件资产身份，但日志、扩展表和旧数据中常缺失。它适合资源刷新内部的强匹配，不适合作为唯一跨模块入口。

### 5.4 AP 名称

- AP 名称可重命名、复用或被写成 MAC，且不同 AC 下可能重名。
- 仅当 `site/AC` 作用域明确、候选唯一时才可作为降级匹配；不能静默取第一条。

### 5.5 Radio MAC、BSSID/BBSSID、Peer MAC

- Radio MAC、BSSID/BBSSID 标识射频口或 BSS，不标识整个物理 AP。
- H3C 当前映射规则必须保持：MAC 统一为 12 位十六进制；Radio 1 与 AP MAC 前 11 位一致；Radio 2 与 AP MAC 前 10 位一致且第 11 位为 AP MAC 第 11 位加 1，第 12 位不要求一致。
- 精确采集到的 Radio/BSSID 映射优先于派生规则；多候选必须返回 ambiguous/multi-match，不能任选。
- `peer_mac` 是日志观测值：在不同命令/版本中可能是 AP MAC、Radio MAC 或 BSSID。只有 resolver 的来源与 match rule 能说明它的角色。
- `peer_radio_mac` 当前通常在 resolver 判定为 radio/BSSID 时直接等于规范化 `peer_mac`，所以两列重复可能是预期的数据表达，不应被误认为两个不同 MAC。

## 6. 当前 AP 字段矩阵

| 语义 | 当前字段 | 推荐草案字段 | 约束 |
| --- | --- | --- | --- |
| 内部 AP identity | `ap_uuid`、表内 `id` | `identity.ap_uuid` | 当前无独立 `fit_ap_uuid`；只接受已解析的站点库 UUID，表内 `id` 不外溢 |
| AC 原生 AP ID | `apid`、`ap_id` | `identity.source_key` 或 `runtime.ap_id` | 当前无独立 `fit_ap_id`；必须带 `ac_device_uuid`，不得作为全局键 |
| AP 设备 MAC | `ap_mac`、`ap_mac_norm`、`ap_mac_display` | `identity.ap_mac` + raw/display | 统一规范化函数，保留原值和来源 |
| AP 名称 | `ap_name`、Peer name、resolved peer name | `identity.ap_name`、`observation.peer_name` | AP 名称和日志 Peer 名称不能覆盖彼此 |
| AP 序列号 | `serial_number`、`serial` | `identity.serial_number` | 可选强证据，不假设所有来源都有 |
| Radio 身份 | `radio`、`radio_id`、`radio_index`、`rid*` | `radios[].radio_id` | 是 AP 子实体，不并入 AP 主键 |
| Radio/BSS MAC | `radio_mac`、`bssid`、`bbssid`、`rid*_bbssid` | `radios[].radio_mac/bssids` | 保存采集值、派生值和 match rule |
| Mesh Peer | `peer_mac`、`peer_mac_raw`、`peer_mac_normalized` | `observation.peer_mac` | 观测身份，不直接写 AP MAC |
| Mesh Peer Radio | `peer_radio_mac` | `observation.peer_radio_mac` | 与 Peer MAC 相同可存储，展示时去重 |
| 管理 AC | `ac_uuid`、`ac_id`、`ac_device_uuid` | `identity.ac_device_uuid` | `ac_uuid/ac_id` 主要是 Job/UI 参数兼容别名；持久化统一到 Device UUID 语义 |
| 通用设备 | `device_uuid` | `topology.device_uuid` | 可能是交换机、AC 或 MR，必须带角色 |
| 站点/局点 | `site_id`、`site`、`site_name`、`station` | `scope.site_id`、`location.station` | 项目数据根/局点与业务车站分开 |
| 区间归属 | `section`、`section_name`、`belong_section` | `location.section` | 区间存在时站点允许为空 |
| 里程和线别 | `mileage`、`mileage_text/m`、`line_side`、`direction` | `location.mileage`、`line_side`、`direction` | raw + 解析米值并存，不能只存数字 |
| 接口/LLDP | `interface`、`port`、`lldp_*` | `topology.links[]` | 交换机接口关联是时间相关关系，不是 AP identity |
| 光衰 | `optical_*`、rx/tx/alarm/status | `telemetry.optical` | 是快照/历史；异常计算需在线状态上下文 |
| 在线状态 | `state`、`online/offline`、`is_offline` | `status` | 必须带采集时间和来源，不覆盖历史事实 |

## 7. 主要消费者与读写边界

| 模块 | 当前消费内容 | 目标权限 |
| --- | --- | --- |
| AC 管理页/AC Domain | 资源、Radio、LLDP、光衰、metadata | 通过 Repository 写运行态主数据和本领域历史 |
| AP 扩展导入/导出 | 工程属性和 AP MAC/name | 只写 extension/metadata；通过显式绑定更新 profile，不创建隐式 AP 主实体 |
| 轨旁 AP 业务与页面 | 资源、交换机接口、LLDP、光衰、扩展、历史 | 只读 canonical profile；可写自己的处置、规划、缓存和历史，不写主 identity |
| Online MR | Peer/name/MAC 到站点/区间映射 | 只读 identity resolver；写 MR 自己的状态、事件和解析结果 |
| 原始 Mesh/MR 分析 | Peer、Radio、样本、source file | 只读 resolver；写带来源的解析快照，不回写 AP 主数据 |
| 无线扫描/BSSID resolver | BSSID 到 AP/Radio 的候选 | 只读；返回匹配状态、候选和证据 |
| 离线 AP 台账/历史查询 | UUID/MAC/name 与历史 | 只读 identity/profile；写独立处置记录时引用 `ap_uuid` 和快照 |
| 导出/报告/OmniPeek 名称表 | 展示字段和分析证据 | 严格只读；只做格式化、别名和重复展示抑制 |
| Job Center/Worker | 序列化参数和结果 | 不拥有 AP 业务 identity；只传可序列化引用和结构化结果 |

## 8. 业务规则与不可破坏约束

后续任何 identity 迁移必须保持：

1. PIS 场景通常不区分红网/蓝网；只有信号系统业务明确要求时才区分，不能把 `network_domain` 设为所有 AP 的必填主键部分。
2. 归属区间可以存在而归属站点为空；不能用 station 空值否定 section 归属。
3. 里程原文和方向语义必须保留：
   - `!Z!D!K##+###`：左线。
   - `!Y!D!K##+###`：右线。
   - `!C!D!K##+###`：出段线。
   - `!R!D!K##+###`：入段线。
4. 光衰异常必须结合 AP 在线/离线状态判断。
5. 交换机无光但 AP 未离线时，不直接计入 AP 光衰异常。
6. AP 离线与光衰异常的关联、H3C CLI 命令、解析字段和阈值规则保持原样。
7. AP MAC/Radio MAC 的 H3C 映射规则和多候选处理保持原样。
8. `source_file_id` 必须参与 MR/Mesh 样本和图表定位；本地 link/anchor ID 不是跨解析库全局键。
9. Peer Radio MAC 与 Peer MAC 相同时，底层可保留原始证据，但导出/展示不应重复表达同一个值。
10. 统一 identity 不能改变已有页面列、导出表头、MR/Mesh 规则或历史查询语义。

## 9. 字段冲突与已发现风险

### 9.1 语义冲突

- **Peer MAC vs Peer Radio MAC**：前者是日志观测字段，后者是 resolver 对其角色的解释；当前可能完全相同。
- **AP MAC vs Radio MAC**：AP MAC 标识物理设备，Radio/BSSID 标识射频子实体；只有明确映射规则可以关联。
- **AP Name vs Peer Name**：AP Name 是资源属性，Peer Name 是日志当时观测/解析名称；不能互相覆盖。
- **站点 vs 区间**：两者不是互斥字段；`section != empty` 不推出 `station != empty`。
- **site vs station**：site 既被用作站点展示，也与数据根/局点概念混用；统一草案必须拆成 scope 和 location。
- **device UUID vs AC UUID**：`device_uuid` 是通用设备身份；`ac_device_uuid` 是 AP 管理作用域；轨旁行中的 device UUID 通常是交换机。
- **AP ID vs FIT-AP ID**：表内 `id` 是行号，`ap_id/apid` 是 AC 运行态 ID；字段名相似但不可互换。

### 9.2 一致性风险

1. `ap_entities` 已存在但并非所有消费者使用，继续新增平行模型会形成第二真源。
2. identity 优先级不一致：资源实体解析采用 UUID/序列号/MAC/唯一名称，资源去重采用 MAC/序列号/名称，部分轨旁查找采用序列号/MAC/名称/UUID，历史去重又采用 UUID/序列号/MAC/名称。
3. AP extension enrich 的 MAC/name index 没有显式 AC 作用域；同站点多 AC 或重名 AP 需要歧义检测。
4. 光衰 payload 的资源 fallback 主要依赖同 AC 下 UUID 或名称；无法关联时生成 UUID 的路径可能形成孤立/重复 identity。
5. metadata 对名称的兼容 join 可能在重名时产生错误富化，尤其是多 AC 共用站点库时。
6. `trackside_ap_view_cache` 的行身份是 `site_id + switch_uuid + interface_name`，描述拓扑视图而非 AP；AP 移动端口后不能把 cache row 当作 AP identity。
7. Online MR lookup 加载带有对 FIT-AP `site` 的反填副作用，读写边界不清晰。
8. `ApRadioMappingService` 在缺少显式 Radio MAC 时可回退为 Peer MAC，调用者必须查看 source/match rule，不能只看值。

### 9.3 记录但本轮不修复的明显问题

- `online_mr_analysis_report_exporter.py` 的 Mesh 链路明细查询目前把同一个 `peer_mac` 同时填到 “AP MAC” 和 “Peer Radio MAC”，与“重复时不重复展示”的既有规则不一致。
- `vehicle_mr_online.py` 的 AP lookup 读取流程会直接更新 `ac_fit_ap_resources.site`，并按 AP 名称或 MAC join；这应在后续迁移中变成显式、可测试、可回滚的 metadata 操作。
- Mesh 物理 AP key 的不同实现存在降级顺序差异；统一前不能改 MR/Mesh 分析结论，只能先做 shadow comparison。

## 10. 推荐统一模型草案

以下仅是边界草案，不落地为生产模型：

```text
CanonicalApIdentity
  ap_uuid: str | None               # 站点数据库内已解析身份
  ap_mac: str | None                # 12 位规范化 AP 设备 MAC
  ap_name: str | None
  serial_number: str | None
  ac_device_uuid: str | None        # 管理 AC 的 Device UUID
  site_id: str | None               # 数据作用域，不等于业务车站
  source_kind: str
  source_key: str | None            # 例如 AC+APID、extension row id
  match_rule: str
  confidence: int | None

CanonicalApRadioIdentity
  ap_uuid: str | None
  radio_id: int | None
  radio_mac: str | None
  bssids: list[str]
  source_kind: str
  match_rule: str

CanonicalApLocation
  belong_type: station | section | yard | unknown
  station: str | None
  section: str | None
  section_start_station: str | None
  section_end_station: str | None
  mileage_raw: str | None
  mileage_m: float | None
  line_side: str | None
  direction: str | None

CanonicalApProfile
  identity: CanonicalApIdentity
  radios: list[CanonicalApRadioIdentity]
  location: CanonicalApLocation
  status: snapshot + source + collected_at
  interfaces: topology relations
  optical: telemetry snapshot
  lldp: topology snapshot
  updated_at: datetime | None
```

设计约束：

- `CanonicalApProfile` 是查询聚合/ViewModel，不等于一张宽表。
- identity、location、topology、telemetry、observation 分层；任何字段合并都保存 source/match rule。
- 现有 `ap_entities` 是内部 identity/profile 基础，`ac_fit_ap_resources` 仍是 AC 运行态资源真源。
- Radio/BSSID/Peer observation 不写入 `CanonicalApIdentity.ap_mac`。
- 匹配失败返回 unresolved，候选多于一个返回 ambiguous，不隐式创建或任选实体。

## 11. 推荐场景化标识优先级

不要建立一条覆盖所有领域的全局优先级，按场景使用：

### 11.1 已落表对象

1. 已验证属于当前站点数据库的 `ap_uuid`。
2. 当前站点下精确序列号或规范化 AP MAC。
3. 当前站点 + AC 下唯一 AP 名称。
4. 无唯一候选时返回 unresolved/ambiguous；只有 AC 资源写入入口可以创建新 UUID。

### 11.2 跨模块匹配

1. `site_id + normalized_ap_mac`。
2. 有可靠覆盖时使用 `site_id + serial_number` 交叉确认。
3. `site_id + ac_device_uuid + apid` 仅作同 AC 运行态提示。
4. AP 名称只在作用域明确且唯一时降级匹配。

### 11.3 日志、Radio 与 BSSID

1. 保留原始 Peer/BSSID 和 source file/sample 作用域。
2. 精确 Radio MAC/BSSID 映射。
3. 现有 H3C Radio 1/2 派生规则。
4. 精确 AP MAC。
5. 作用域内唯一 Peer/AP 名称。
6. 多候选返回 ambiguous，不改变原始分析数据。

### 11.4 轨旁和光衰

- 轨旁行同时使用 AP identity 与 `switch device_uuid + interface` 拓扑 identity，再结合站点、区间和里程；不能用单个键替代整个关系。
- 光衰优先使用已解析 `ap_uuid`，并携带 AC、AP、交换机接口、采集时间和在线状态；异常判断继续由现有 Domain 规则完成。

## 12. 分阶段迁移方案

| 阶段 | 修改范围 | 主要风险 | 验证方式 | 数据库迁移 | 回滚方式 |
| --- | --- | --- | --- | --- | --- |
| 0：评估 | 本文、迁移地图和开发规则 | 遗漏消费者 | 静态搜索、UTF-8、Markdown、diff 检查 | 否 | 删除本轮文档增量 |
| 1：统一 identity 工具（已完成） | 新增纯 Python normalizer、identity key、resolution result；未接入写流程 | 优先级写成全局规则、错误折叠 Radio | 36 个 characterization tests 覆盖格式化、歧义、跨 AC、Radio/BSSID、Peer 和空值 | 否 | 移除工具；生产链路尚未依赖 |
| 2：AC FIT-AP + extension 适配（已完成） | AC adapter 读取资源/扩展 row，preview/commit/refresh/save 附加 shadow；Repository SQL、写入 key 和原字段保持不变 | UUID 漂移、扩展误绑定、重名覆盖 | 旧/新 shadow compare；15 个 adapter/Job 兼容测试 | 否 | 删除 handler 附加字段并切回保留的 legacy helper |
| 3：光衰适配 | 光衰 service 只通过 identity adapter 解析 AP | 离线/光衰规则被误改、孤立 UUID | 批量/单 AP、离线关联、无光不误判、历史快照对比 | 否 | 保留旧 UUID/name fallback 并切回 |
| 4：轨旁只读接入 | 轨旁业务读取统一 identity/profile，保留 switch-interface 拓扑键与现有缓存 | AP/端口误关联、站点/区间丢失 | 全量轨旁 golden rows、双击定位、离线台账、光衰状态、里程方向回归 | 否 | feature flag/adapter 切回原 lookup |
| 5：MR/Mesh 匹配增强 | resolver 返回 canonical identity、radio identity 和证据；不改分析判定 | 解析结果变化导致切换/乒乓结论漂移 | 同一日志旧/新结果 shadow compare；source_file 隔离；双 Radio 和多候选样例 | 默认否；如需持久化新字段，另立 additive migration | 关闭新 resolver，继续使用旧映射缓存/字段 |
| 6：导出命名与去重 | 统一展示别名；Peer/Peer Radio 相同只展示一次；保持兼容表头策略 | 下游模板依赖、列含义变化 | Golden XLSX/CSV、WPS/Excel 打开、表头和行值对比 | 否 | 使用旧 formatter/兼容导出模板 |

阶段 1～6 都不应顺带拆 `legacy_tasks.py`、替换页面模型或调整数据库 schema。只有前述 shadow comparison 表明确认现有 `ap_entities` 无法承载需求后，才单独评估 additive schema migration。

## 13. 不建议立刻迁移的范围

- 不创建新的 AP 宽表或第二套 canonical repository。
- 不批量替换 `dict`、页面字段、导出表头和测试 fixture。
- 不迁移轨旁 AP 规则、离线台账、处置流程或双击定位逻辑。
- 不修改光衰异常、AP 在线/离线关联、H3C 命令、parser 或阈值。
- 不修改 MR/Mesh 主链路、同 AP 双 Radio、短链、乒乓和 source-file 规则。
- 不把 Radio MAC/BSSID/Peer MAC 直接回写成 AP MAC。
- 不把 PIS 强制拆红/蓝网，也不要求 section 数据必须同时有 station。
- 不修改 SNMP、AC 采集、Online MR 采集、Job Center 或 Worker 协议。
- 不修复本评估记录的现有问题；分别纳入后续小阶段并建立回归证据。

## 14. 后续测试策略

阶段 1 首先增加 characterization tests，而不是修改现有业务期望：

1. MAC 格式统一：H3C、冒号、短横线、纯 12 位、非法和空值。
2. 作用域：同名跨 AC、同 MAC 跨站点、相同 APID 跨 AC。
3. 优先级：已有 UUID、序列号、MAC、唯一名称、重名、无候选。
4. Radio：精确 Radio/BSSID、Radio 1/2 派生、AP MAC 精确、多候选、Peer name fallback。
5. location：station 为空但 section 有值、PIS 无网络域、信号红/蓝网、四类里程前缀。
6. optical：在线/离线关联、交换机无光但 AP 在线、历史与当前快照一致。
7. trackside：AP identity 与 switch-interface topology 分离，AP 移动端口和历史 LLDP 场景。
8. MR/Mesh：`source_file_id` 隔离、Peer/Peer Radio 重复、同 AP 双 Radio，不改变分析结论。
9. 导出：表头兼容、重复 MAC 展示抑制、原始证据仍可追溯。
10. 每次接入都执行旧/新 resolver shadow compare，并记录 unmatched、ambiguous、identity-changed 数量；任何非预期变化阻止迁移。

## 15. 阶段 1/2 完成状态与阶段 3 准入

阶段 1 已完成并满足：

- 工具位于 `services/ap_identity`，只包含 frozen model、normalizer、保守 resolver 和只读 row adapters。
- 未新增数据库表/列，未修改 Repository SQL、生产模块或业务规则。
- AP、Radio/BSSID、Peer observation、位置和拓扑作用域保持分层。
- resolution result 包含 `matched/unresolved/ambiguous`、候选、Evidence 和 warnings。
- Peer 只命中 AP MAC时保留低置信证据并返回 unresolved，不强行绑定。

阶段 2 已完成：AC adapter 对 FIT-AP Candidate 与扩展 Observation 执行 old/new shadow comparison；preview/commit/refresh/save 只新增 `identity_shadow`，旧 helper、Repository SQL、写入 key、原 result 字段和 UI 流程保持不变。

可以评估阶段 3，但只允许光衰 Domain Service 读取 identity 适配结果并做 shadow comparison。不得修改离线关联、无光判断、阈值、历史写入或页面字段，也不得跳到轨旁迁移。具体规则见 [AP_IDENTITY.md](AP_IDENTITY.md)。
