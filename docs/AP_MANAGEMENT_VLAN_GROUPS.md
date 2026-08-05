# 轨旁 AP 逐站规划

## 当前模型

轨旁 AP 规划当前以“一座车站一行”为用户模型和业务事实。用户只维护序号、车站名称、AP 数量、AP 管理 VLAN 和备注；保存时同时绑定稳定 `station_id`。管理 VLAN 只表示该站 AP 的目标管理 VLAN，不是 AP、站点或区间的身份。

- 每站填写不同 VLAN 表示每站独立；
- 多个站填写相同 VLAN 表示共享 VLAN；
- 全部站填写相同 VLAN 表示全线统一；
- 管理 VLAN 不设唯一约束，也不触发分组、合并或地址计算。

“AP数量”是当前经项目确认后应建设、应上线的有效规划值，由用户手工维护，允许为 `0`，也允许按现场情况核减或调整。最初设计数量和核减原因记录在备注中，不另设字段。AC 状态、轨旁 AP 参考资料记录数和 VLAN 兼容模型均不得覆盖该值。AP 起始地址、掩码和网关不再属于活动规划字段；历史数据库列和旧模板值仅为兼容保留，读取后直接忽略。

## 页面与保存

`/rail-transit/base-data?tab=trackside-ap-planning` 是拥有独立锁定、草稿、校验和保存边界的受控子页：

- “AP 规划维护”：直接编辑逐站表，支持从设备管理生成站点、手工维护规划行、单行或批量删除；组件不拥有加载、保存、锁或 dirty 基线，当前页面不提供规划模板导入、模板下载或规划导出；
- “AP 上线情况概览”：只读展示规划 AP 总数量、实际上线、未上线、上线率和备注，并显示按数量汇总的线路合计。

页面不再展示规划方式、VLAN 组、组边界、拆分合并、IP 地址字段、revision 或全局阻断问题。车站名称必须匹配当前基础资料，不能在规划表中临时创建任意站名。字段错误定位到单元格；未分配站点 AP 只显示普通警告和明细入口，不阻止规划维护，不计入任何分站，但计入线路实际上线合计。

规划与上线状态使用独立请求和独立错误状态。规划加载成功后立即展示 Backend 已保存的稀疏规划行并保持可编辑，不等待上线状态；不会按全部站点自动补齐占位规划行。上线状态失败只在概览局部提示并保留最后成功结果。任一请求下次成功只清除自身错误。接口或网络错误不进入规划字段校验，因此“有 N 项需要修正”只统计站点匹配、AP 数量、管理 VLAN、序号和重复项等真实草稿问题。

上线概览只返回站点统计、少量诊断计数、生成时间和来源 revision，不内嵌完整排除项或“基础资料待补充”在线 AP。用户点击对应明细后，页面分别调用 `/plan/online-status/excluded` 和 `/plan/online-status/unmatched` 分页读取；默认页大小为 50，空 MAC 以空字符串返回。概览按规划、FIT-AP、AP Identity、站点交换机绑定、当前 LLDP 和局点元数据 revision 缓存，来源不变时直接复用，`source_revision=0` 仍是合法 revision。缓存命中状态和阶段耗时进入诊断日志，不改变统计口径。

规划编辑只属于规划子页草稿。解锁时以 `scope=trackside_ap_planning` 获取包含正式站点依赖和规划行的编辑快照，并按 `station_id` reconcile：站名修改保留用户值，来源消失或禁用的历史行保留为 `stale`；启用的普通站、车辆段和停车场都可生成规划行，资格不依赖 `participates_in_direction`。保存通过 `POST /api/rail-transit/base-data/changes` 进入 `RailTransitBaseDataApplicationService`，载荷只允许 `trackside_ap_plan`；后端继续执行 revision 检查和 SQLite `BEGIN IMMEDIATE` 单事务，失败整体回滚。修改规划不会保存站点、区间、AP、MR，不连接 AC，也不自动刷新设备状态。

当前用户接口包括（规划模板预览/导出接口仅为历史兼容，不由活动页面调用）：

```text
GET  /api/rail-transit/trackside-ap-business/plan
GET  /api/rail-transit/trackside-ap-business/plan/online-status
POST /api/rail-transit/trackside-ap-business/plan/import/preview
POST /api/rail-transit/trackside-ap-business/plan/export
GET  /api/rail-transit/trackside-ap-business/plan/artifacts/{artifact_id}/download
```

旧 `/plan/auto-group-preview`、`/plan/adjustment-preview`、`/plan/mode-impact-preview`、`/plan/validate`、`/plan/address-preview`、`/plan/effective-network`、`/plan/point-table-preview` 和 `/plan/save` 暂时保留为兼容 API，不再由活动页面调用。专用 `trackside_ap_plan_save` Job 同样只服务旧消费者；当前页面保存入口是基础资料统一事务。

## 上线统计

实际上线数量复用现有 FIT-AP 在线状态。基础 AP 资料中的完整 MAC 与稳定 `station_id` 是首选关联；没有任何基础 AP 资料命中时，允许使用“当前车站交换机 LLDP 完整邻居 MAC = FIT-AP 完整 MAC”的唯一精确证据进行只读运行态站点投影。交换机已有有效 `station_id` 时直接使用；缺失时，设备管理 `station` 必须与当前正式站点规范化后唯一对应，多候选或空值不得投影。站点范围来自当前有效站点与逐站规划，不依赖 AP 参考资料或 FIT-AP 资源是否已经导入。参考资料记录数本身不作为统计字段或上线率分母：

FIT-AP 运行态只把 AC 的 `R/M`、`R/B` 计为在线，其余明确状态计为离线；状态字段全部缺失时保留未知且不计入在线。轨旁业务明细只对最新有效 AP Rx 使用固定维护线：严格低于 `-13.90 dBm` 标记“功率异常”，等于该值仍为正常，空值、无效值或过期值为未知。交换机侧和 AP 设备模块状态继续按照各自模块门限判断；业务综合状态组合端口、交换机模块和 AP 业务光衰，但不让固定门限改写设备状态。

```text
未上线 = max(规划 AP 总数量 - 实际上线数量, 0)
站点上线率 = 实际上线数量 / 规划 AP 总数量
总上线率 = 实际上线合计 / 规划 AP 总数量合计
```

规划 AP 总数量为 `0` 时上线率为空，由页面显示为 `—`。实际上线超过规划值时保留真实数量、未上线仍为 `0`，状态显示“超规划”，上线率显示 `—`，不得导出 `1200.0%`、`5200.0%` 等误导性比例。缺少规划的有效站点仍显示为 `planning_missing`，而有规划但没有匹配 FIT-AP 时实际为 `0`、未上线等于规划数量。参考资料数量与规划值不同只作为轻量数据质量信息，不修改规划、不阻断保存；未匹配有效资料的在线 AP 进入独立“基础资料待补充”诊断，不计入任何分站，也不计入真正排除项，但会作为独立行计入线路实际上线合计。轨旁 AP 业务导出的概览合计备注同时列出 AC AP 资源、已关联上线和基础资料待补充数量，避免把已关联上线数误认为全部当前 AP。统计更新时间来自当前 AP/FIT-AP 数据的最新时间；用户点击“刷新上线状态”时复用现有轨旁 AP 后台任务，只刷新实际上线结果，不修改页面规划草稿。

上线概览不是轨旁 AP 业务明细的数据源。页面查询、业务明细导出和上线概览共享同一解析结果，但业务明细以设备管理中的站点交换机候选端口为骨架，直接使用 AC FIT-AP 与光衰运行态补充 AP 侧事实；AP 基础资料只在精确命中时补充稳定站点和工程属性。交换机尚未绑定基础资料 `station_id` 时仍按设备管理 `station` 展示候选端口，在线 AP 尚未匹配基础资料时仍可通过精确 LLDP MAC 进入业务行。该运行态组合不新增或修改 AP 基础资料、规划及 AP Identity，也不把交换机接口当作 AP 身份。当前局点/项目及显式建设阶段匹配、当前工作状态为 `included` 的站点交换机不因缺少 AP 资料而消失。暂不参与、跨项目、明确排除、阶段不匹配、站点关联不唯一才进入排除项；LLDP 同一完整 AP MAC 指向多个站点或完全无精确证据时只保留候选端口并显示基础资料待补充诊断，不按 VLAN、站名、AP 名称或邻居 IP 猜测稳定归属。
业务明细和导出按车站交换机自然升序、接口逻辑自然升序排列；站点字段保留基础资料的编号展示。

## 来源

活动页面不提供轨旁 AP 规划模板导入、模板下载或规划导出。站点来源来自设备管理中“车站”分组设备的 `station` 字段：点击“从设备管理匹配正式站点”后先展示候选，但只允许选择已有 `matched_station_id` 的候选。缺少正式 ID 的候选必须前往“站点与区间”子页维护；规划页不创建、不解锁、也不保存站点。这样每条新规划行从进入草稿开始就绑定正式站点的稳定 `station_id`。

旧规划 XLSX 解析、导出和对应 API 不属于当前活动 UI，也不参与当前规划读取。兼容格式 schema v4 增加必填“车站ID”；旧分组模板只有在文件本身携带可一一对应的“组成员站点ID”时才可转换，只有站名必须报错。轨旁 AP 业务页仍可按自身契约导出业务明细和上线概览，但不改变规划维护来源。

完整主数据边界见 [轨旁 AP 主数据与关联模型](rail-transit/TRACKSIDE_AP_DOMAIN_MODEL.md)。

## 运行态与拓扑快照一致性

轨旁 AP 的三个事实维度保持独立：FIT-AP `state/raw_state` 只决定 AP
`online/offline/unknown`；AP/交换机光模块只决定光衰健康；站点和端口是
当前拓扑投影。光衰异常、LLDP 冲突、Mesh Radio 状态和规划资料不得覆盖
FIT-AP 在线状态。

业务查询以只读 `TracksideApRuntimeSnapshot` 记录本次使用的来源时间和
`collect_run_uuid`。LLDP 早于 FIT-AP 时状态为 `lldp_stale`，在线 AP 分类
为 `lldp_snapshot_stale`/“等待 LLDP 同步”，不再伪装成基础资料缺失。当前
LLDP 只取每台交换机最近一次成功批次；旧接口留在历史，接口迁移后新接口
是 current，历史冲突不会污染当前冲突。`merged` 与 `ap_direct_lldp` 表达
同一事实时先去重。

“基础资料待补充”只表示真实的 station master、AP 主资料或规划缺失。新增
上线 AP 以 `identity_entity_id` 优先、物理 AP MAC 其次比较历史在线状态，
站点尚未解析时仍可计入新增上线。

本节替代上文将所有未关联在线 AP 统称为“基础资料待补充”的兼容描述。活动
页面、上线概览和导出必须分别列出 FIT-AP 总数、实际在线/离线/未知、已关联
上线、等待 LLDP 同步、当前 LLDP 冲突和真实基础资料缺失；旧 DTO 中的
`fit_ap_matched_count` 只表示已关联资源数，实际在线使用
`fit_ap_matched_online_count`/`fit_ap_online_total_count`。

## PVID 与历史数据边界

PVID 候选和核验只读取当前逐站规划的 `management_vlan`。完成 AP 身份解析后，只按 AP 自身的 `station_id` 读取所属站点 VLAN。多个站使用相同 VLAN 合法；核验不能把 VLAN 当作唯一站点身份，也不能通过 VLAN 反推 AP 归属。

`devices.db` 继续保留以下历史表及数据，不执行破坏性删除：

- `rail_ap_vlan_plans`
- `rail_ap_vlan_groups`
- `rail_ap_vlan_group_members`
- `rail_ap_vlan_assignments`
- `rail_ap_vlan_allocations`

这些表只作为历史数据留存，不再由活动 UI 编辑，也不参与当前规划、上线概览、PVID 或共享范围查询。当前逐站事实只保存在 `ac_trackside_ap_plan(mode='unified')`；0 行就是明确的空规划，不会把旧 VLAN 组投影成“复活”的规划行。用户在新页面保存后只替换逐站记录，不覆盖或删除历史分组数据。

数据库初始化会幂等确保 `station_id`、`sequence_no`、`subnet_mask` 和 `management_vlan` 字段以及有效 `station_id`、正序号的局部唯一索引，但不会在逐站规划与历史 VLAN 表之间复制数据。`ap_start_address`、`mask_length`、`subnet_mask`、`ap_gateway` 和 `ap_management_vlans` 等历史列不删除，但活动页面和当前 DTO 不再使用。序号为零或重复时按既有顺序确定性重排后再建索引。字段、索引和 schema version 写入位于同一初始化事务，失败整体回滚；验证只能使用临时数据库或真实数据库备份副本。
