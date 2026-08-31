# 轨旁 AP 业务只读快照

## 结论

轨旁 AP 页面和业务导出共用 `load_trackside_ap_business_snapshot()` 与
`select_trackside_ap_business_rows()`。页面返回一次稳定读取形成的完整业务投影；
导出任务先由 Backend 校验请求契约并创建 Task，再由独立 Export Worker 以只读连接
重建并校验页面 `business_revision`，把基础业务行和工作簿表现行
冻结到受控 staging JSON，随后只读取该文件渲染 XLSX。快照准备失败也属于已创建
Task 的失败终态，不再发生在 Task 生命周期之外。

本契约没有修改数据库 schema、AP/Radio MAC 派生规则、AP Identity 优先级、
`-13.90 dBm` 业务门限、工作表、排序或文件名规则。2026-08 的字段变更调整了
“轨旁AP业务”和“当前异常光衰”的字段契约及主 sheet 表现层填色；当前导出范围契约
进一步将页面异常复选框从冻结快照中移除，但页面业务判定与异常查询保持不变。详细
字段与着色规则见
[轨道交通业务规则](../RULES.md#导出规则)。

## 数据源矩阵

### FIT-AP 多 AC 与 Site 物理投影边界

FIT-AP 采集范围是 AC，轨旁 AP 业务范围是 Site。业务快照先读取当前 Site
下全部 AC 的 `ac_fit_ap_resources`、`ac_fit_ap_optical` 及其 AC 侧事实，再
按 canonical physical identity 聚合；同一 physical AP 跨 AC 出现时物理业务
行只计一台，但保留全部 `ac_device_uuid` 来源证据。

没有车站/AP 定向条件的 Site 更新默认枚举所有纳入范围的 H3C `AC` 或
`wireless_controller`，每台 AC 独立采集和提交；单 AC 更新是局部补采。Site
汇总只表示多 AC 的结果集合，不改变既有轨旁 AP 基础资料/规划过滤。

`ac_fit_ap_optical` 是 AC 光衰 Current 权威；`optical_current` 是 Site 物理
AP/交换机两侧的有界投影，不能反向作为 AC 光衰 Current 的读取来源。类似地，
`fit_ap_radio_current` 只表示 Site 物理范围投影，AC Radio Current 仍由 AC
作用域表提供。

以下存储位置均在当前局点主库，即 `PathResolver.site_db_path(site_id)`；局点上下文
来自 `SiteManager` 管理的局点 metadata。表中“R1/R2”表示数据行不在一个跨来源
事务内长期锁定，而是在构建前后比较来源 revision，发生变化时丢弃本轮结果。

| 数据源 | 存储位置 | revision | 正式读取入口 | 写入入口 | 事务边界 | 导出字段 |
| --- | --- | --- | --- | --- | --- | --- |
| 局点、项目、线路和建设阶段 | 局点 metadata | `scope_context_revision`，只哈希有效作用域字段 | `SiteManager.load_site_metadata()`、`TracksideApScopeContext.from_metadata()` | 局点管理 Service | 读取后纳入 R1/R2 上下文 | 局点范围、显示名称；显示名称只进文件契约，不进业务行 |
| 车站资料 | `ap_extension_points` 的车站辅助行 | `base_data_revision` | `AcRepository.list_ap_extension_points()`、有效范围 Service | 基础资料 Application Service/Repository | R1/R2 | 站名、`station_id`、顺序和范围 |
| 区间资料 | `ap_extension_points` 的区间/位置字段 | `base_data_revision` | 同上 | 同上 | R1/R2 | 区间、起止站、里程和方向 |
| 轨旁 AP 基础资料 | `ap_extension_points` | `base_data_revision` | `AcRepository.list_ap_extension_points()` | 基础资料 Application Service/Repository | R1/R2 | AP UUID、名称、MAC、点位、位置归属 |
| 轨旁 AP 规划 | `ac_trackside_ap_plan`、`ac_trackside_ap_plan_settings`、`rail_ap_vlan_*` | `base_data_revision` | `get_active_trackside_pvid_plan()`、`list_trackside_ap_plan()` | 规划 Application Service/Repository | R1/R2 | PVID、管理 VLAN、VLAN 组和规划状态 |
| 设备管理与投运范围 | `devices`、`device_groups` | `base_data_revision` | `DeviceRepository.list()`、`filter_station_switch_devices()` | 设备管理 Service/Repository | R1/R2 | 交换机 UUID/名称/厂商、设备类型、项目阶段、参与状态 |
| `station_id` 绑定 | `devices.station_id`、`ap_extension_points.station_id/section_id` | `base_data_revision` | 有效范围 Service、`list_trackside_ap_runtime_station_evidence_rows()` | 基础资料和设备管理正式写入口 | R1/R2 | 交换机/AP/规划站点及一致性状态 |
| 交换机接口与身份事实 | `device_facts`、`device_interfaces` | `switch_facts_revision` 内容指纹 | `DeviceFactRepository.list_device_facts/list_device_interfaces()`、`AcRepository.list_trackside_switch_identity_rows()` | 交换机采集 Job/Repository | R1/R2；每个 Repository 连接独立关闭 | 接口、链路、描述、VLAN、sysName、设备/接口 MAC、采集代次和时效 |
| 交换机当前光模块 | `device_optical_modules` | `switch_facts_revision` 内容指纹 | `DeviceFactRepository.list_optical_modules()` | 交换机采集 Job/Repository | R1/R2 | 交换机 RX/TX、原生门限、告警和时效 |
| 当前 LLDP | `device_lldp_neighbors` | `lldp_revision` 内容指纹 | `DeviceFactRepository.list_lldp_neighbors()`、`AcRepository.list_trackside_ap_runtime_station_evidence_rows()` | 交换机采集 Job/Repository | R1/R2 | 本地端口、邻居 MAC/接口/名称、站点证据和采集代次 |
| FIT-AP 当前资源 | `ac_fit_ap_resources`、`ac_fit_ap_metadata`、`ac_fit_ap_unauthenticated` | `fit_ap_resource_revision` 内容指纹 | `AcRepository.list_all_fit_ap_resources_with_metadata()` | AC/FIT-AP 采集与受控管理 Service | R1/R2 | AP 在线状态、稳定身份、AC、AC 侧 LLDP 上联交换机身份、站点元数据和未固化状态 |
| FIT-AP 历史稳定身份 | `ap_lldp_history`、`ac_fit_ap_lldp_history`、`ac_fit_ap_unauthenticated_history` | `ap_history_revision` 内容指纹 | `list_latest_ap_lldp_histories()` 及 FIT-AP metadata enrichment | AC/FIT-AP 与 LLDP 采集 Repository | R1/R2 | 离线 AP 的最后交换机/端口、历史未认证状态 |
| AP Identity | `ap_identity_index_state`、`ap_identity_source_state` 和索引 alias | `ap_identity_revision`，包含 index/source/status | `ApIdentityQueryService.resolve_ap_macs(..., ap_role="trackside")` | AP Identity 正式构建入口；业务查询只读 | distinct MAC 单批只读事务，并由外层 R1/R2复核 | entity、matched/unresolved/ambiguous、匹配规则和批次 revision |
| FIT-AP 当前光衰 | `ac_fit_ap_optical` | `optical_data_revision` 内容指纹 | `AcRepository.list_all_fit_ap_optical()` | AC 光衰采集 Job/Repository | R1/R2 | AP RX/TX、设备模块状态、业务异常和采集时间 |
| 仅工作簿使用的历史 | `ac_fit_ap_resource_history`、`ac_fit_ap_optical_history`、`device_optical_modules_history` | `export_history_revision` 内容指纹 | AC/DeviceFact 历史查询入口 | 对应采集 Repository | 导出外层 R1/R2；不进入页面 `business_revision` | 新上线概览、光衰处置记录、离线台账和历史统计 |
| 施工、调试和业务状态 | `devices`、`device_groups`、`ap_extension_points`、规划表相关状态字段 | 当前共享 `base_data_revision` | 有效范围 Service 和业务投影 builder | 对应正式管理/基础资料入口 | R1/R2 | 范围排除、关联状态、规划缺失和业务状态 |
| 筛选、选择和排序 | API 请求；不持久化到业务库 | 页面查询包含异常筛选；导出冻结 payload 只包含 station/query、稳定 `business_row_id` 选择和固定排序契约 | `select_trackside_ap_business_rows()` | Renderer 只提交受控 DTO | 内存纯函数 | 页面 station/query/异常筛选；导出 station/query/选择行 |
| 资源协调 | 局点 `tasks.db` 的 `resource_keys` | Task 生命周期 | `TaskApplicationService` | Job/Export 提交入口 | 导出不持有实时数据资源锁；光衰更新仍持有自身写任务锁 | 不进入工作簿 |

`base_data_revision` 是现有 SQLite trigger 维护的正式计数器，覆盖
`ap_extension_points`、`devices`、`device_groups`、轨旁规划和相关 VLAN 规划表。
它目前同时承载站点绑定、设备清单、规划和业务状态语义，属于有意保留的粗粒度
revision；本文不把它错误描述成多个独立持久计数器。

## Revision 和稳定读取

页面来源 revision 包含：

- `base_data_revision`，以及引用同一正式计数器的 station/device/planning/business 键；
- `scope_context_revision`；
- `switch_facts_revision`、`lldp_revision`、`fit_ap_resource_revision`；
- `optical_data_revision`、`ap_history_revision`、`ap_identity_revision`。

`business_revision` 是以下规范化 JSON 的 SHA-256：

```text
site_id + business rule/contract version + 页面来源 revisions
```

导出额外读取 `export_history_revision`，并以
`business_revision + 全部导出来源 revisions` 计算 `export_revision`。历史工作簿数据
变化不会让页面业务 revision 无意义失效，但会产生新的导出 revision。

稳定读取最多尝试三次：读取 R1、批量读取事实、单批解析 AP Identity、构建业务行、
读取 R2。R1 与 R2 不同则丢弃整轮结果并短暂退避；连续变化返回
`TRACKSIDE_AP_SNAPSHOT_UNSTABLE`，不返回混合时点的数据，也不持有全局写锁。

稳定快照中的 `rows` 是只读 mapping tuple，`source_revisions` 和查询 MAC 到 entity
的映射也是只读副本，不再引用 builder 的可变 dict。AP Identity 收集每行 AP、
LLDP/Peer、Radio/BSSID 等有效 alias，规范化去重后只调用一次
`resolve_ap_macs(..., ap_role="trackside")`；行关联仍以 LLDP 观测优先、AP MAC 次之，
ambiguous 不选择候选。

基础 AP MAC 和交换机侧“AP MAC 精确邻居”仍是首选关联。两者都未命中时，
查询可消费 FIT-AP 资源已经保存的 AC 侧 LLDP 上联交换机身份，并在当前局点
`devices + device_facts + device_interfaces` 中建立只读索引。匹配优先级为已保存的
交换机 UUID、唯一 Chassis/MAC、唯一管理地址、规范化后唯一 system name、明确设备
别名；名称规范化只处理 NFKC、大小写、FQDN、分隔符及厂商/型号前缀，不做相似度
匹配。任一层出现多个候选即返回冲突，不选择第一条。交换机匹配后只接受有效
`station_id`，或将设备管理 `station` 唯一解析到当前局点正式站点；对应逐站规划
存在时生成 `ac_lldp_switch_identity` 只读运行态投影，不写回设备、规划或基础资料。

页面请求本身每次执行 R1/构建/R2，因此没有可被“设备详情更新”单独唤醒的持久
业务快照。上线概览另有 revision-keyed 进程内缓存，并同样在构建前后复核 revision，
变化时最多重试三次而不发布混合时点结果；其 revision 同时包含 FIT-AP、
交换机 LLDP、`devices`、`device_facts`、`device_interfaces`、规划、基础资料、Identity
和局点 metadata。任一身份事实提交后，下次查询自动 miss 并重算，不要求进入设备
管理点击详情更新。

## 页面契约

`GET /api/rail-transit/trackside-ap-business/rows` 返回 `snapshot_id`、
`business_revision`、来源 revision、Identity revision、快照时间和统计。后续翻页携带
`expected_revision`；revision 已变化时返回 `409 TRACKSIDE_AP_SNAPSHOT_STALE`，前端
回到第一页重新加载，不把两个 revision 的页拼在一起。

页面 `row_count`、`abnormal_count`、`unresolved_count`、`ambiguous_count` 和
`content_sha256` 基于当前 station/query/异常筛选后的全部业务行，不基于当前页；
导出快照的这些字段则基于 station/query/selected row IDs 范围内的完整业务行，完全
忽略页面的 `optical_anomaly_only`。两者都对规范化业务行 JSON 计算，因此相同
revision 和正式范围得到确定性结果。

未完成关联项返回互斥 `association_status/reason_code`，并携带 AP MAC 原始/规范值、
规划记录和站点、LLDP 身份与时间、交换机候选和最终 device ID、失败阶段、来源
revisions、业务 revision 与快照生成时间。页面明细、上线概览分页诊断和 XLSX
“待关联在线 AP”Sheet 复用同一作用域结果，不在前端重新推断分类。

## 导出冻结和 Worker

导出请求只接受 `generated_at`、`suggested_name`、`expected_revision`、`station`、`query`
和稳定 `selected_row_ids`；局点由 Backend 上下文决定。页面异常筛选是展示专用，不能
进入导出范围。旧客户端仍可提交 `optical_anomaly_only` 以兼容解析，但 Backend 和
Export Worker 明确忽略它。Backend 在创建 Task 时原样携带 `expected_revision` 和正式
范围条件，不同步扫描全量来源表。Task 创建后，Export Worker
以只读连接重建稳定快照并比较 `expected_revision`、验证选择；发生
`TRACKSIDE_AP_SNAPSHOT_STALE` 或 `TRACKSIDE_AP_EXPORT_SELECTION_STALE` 时，任务和
Artifact 进入失败终态。准备成功后快照写入：

```text
<data_root>/staging/trackside_ap_business/<site_id>/<task_id>/snapshot.json
```

文件使用临时文件、flush、fsync 和 `os.replace` 原子发布；发布后立即回读校验文件
SHA-256 与 payload SHA-256。失败会清理 `.tmp` 和无效的已发布文件。wrapper 包含
schema version、payload hash 和 payload；payload 同时保存：

- `business_rows`：导出 station/query/selected row IDs 范围内的完整基础业务行，不含页面异常筛选；
- `workbook.rows`：仅增加既有历史展示字段的 Excel 行；
- 其他既有 Sheet 的冻结输入；
- revisions、两个内容 hash、统计、筛选、选择和排序契约。

Worker 在准备阶段完成后，再校验冻结文件 hash、payload hash、schema、基础业务行 hash、工作簿行
hash 和行数。`content_sha256` 对 `business_rows` 计算，
`export_content_sha256` 对 `workbook.rows` 计算。Worker 不创建
第二套业务连接；快照准备使用只读 `DeviceRepository`，渲染阶段不再访问业务 Query
Service，只把冻结数据交给既有 XLSX formatter。

成功结果和 Artifact manifest 保存 `snapshot_id`、`business_revision`、
`export_revision`、`source_revisions`、两个 hash、`row_count`、`export_kind`、
异常/Identity 计数和耗时。Task Center 详情读取同一白名单字段。终态回调清理
snapshot；Backend 重启后的终态恢复也通过受控路径 helper 清理 `snapshot.json`
和 `.tmp`，不会改写其他已完成 Artifact。

## 错误和锁边界

| 错误码 | 语义 | 用户动作 |
| --- | --- | --- |
| `TRACKSIDE_AP_SNAPSHOT_STALE` | 页面 revision 已过期 | 刷新第一页后重试 |
| `TRACKSIDE_AP_SNAPSHOT_UNSTABLE` | 构建期间来源持续变化 | 保留当前表格，稍后重试 |
| `TRACKSIDE_AP_SNAPSHOT_INVALID` | staging schema/hash/行契约无效 | 重新提交导出 |
| `TRACKSIDE_AP_SNAPSHOT_NOT_FOUND` | Worker 或恢复时 staging 缺失 | 重新提交导出 |
| `TRACKSIDE_AP_EXPORT_SELECTION_STALE` | 选择的行不属于当前结果 | 清理选择、刷新后重选 |

`INVALID` 和 `NOT_FOUND` 在 Worker error event 的 `result.error_code` 中结构化保存，
Artifact 拒绝协调不会再清空该错误码。导出从 staging 渲染期间不占用
`site:<site>|trackside_ap_business_data` 或 FIT-AP/LLDP/光衰写资源；该资源键只保留
给真实光衰更新等写任务。Excel 生成不会阻塞实时采集。

## 兼容边界

轨旁 AP 业务工作簿仍使用原文件名、Sheet、MAC 格式、排序、冻结窗格、筛选和样式；
仅“轨旁AP业务”和“当前异常光衰”按 [轨道交通业务规则](../RULES.md#导出规则)
的明确列契约生成。`station_id` 不因本快照契约新增到既有用户列；重命名命令、导入
问题和基础资料导出走原有独立契约。数据库和历史业务数据均不迁移、不改写。
