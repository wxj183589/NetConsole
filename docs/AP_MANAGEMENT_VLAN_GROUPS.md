# 轨旁 AP 逐站规划

## 当前模型

轨旁 AP 规划当前以“一座车站一行”为用户模型和业务事实。用户只维护序号、车站名称、AP 数量、AP 管理 VLAN 和备注；保存时同时绑定稳定 `station_id`。管理 VLAN 只表示该站 AP 的目标管理 VLAN，不是 AP、站点或区间的身份。

- 每站填写不同 VLAN 表示每站独立；
- 多个站填写相同 VLAN 表示共享 VLAN；
- 全部站填写相同 VLAN 表示全线统一；
- 管理 VLAN 不设唯一约束，也不触发分组、合并或地址计算。

“AP数量”是当前经项目确认后应建设、应上线的有效规划值，由用户手工维护，允许为 `0`，也允许按现场情况核减或调整。最初设计数量和核减原因记录在备注中，不另设字段。AC 状态、轨旁 AP 参考资料记录数和 VLAN 兼容模型均不得覆盖该值。AP 起始地址、掩码和网关不再属于活动规划字段；历史数据库列和旧模板值仅为兼容保留，读取后直接忽略。

## 页面与保存

`/rail-transit/base-data?tab=trackside-ap-planning` 提供两个子页：

- “AP 规划维护”：直接编辑逐站表，支持从设备管理生成站点、手工维护规划行、单行或批量删除、保存、撤销和多行多列粘贴；当前页面不提供规划模板导入、模板下载或规划导出；
- “AP 上线情况概览”：只读展示规划 AP 总数量、实际上线、未上线、上线率和备注，并显示按数量汇总的线路合计。

页面不再展示规划方式、VLAN 组、组边界、拆分合并、IP 地址字段、revision 或全局阻断问题。车站名称必须匹配当前基础资料，不能在规划表中临时创建任意站名。字段错误定位到单元格；未分配站点 AP 只显示普通警告和明细入口，不阻止规划维护，也不计入线路合计。

规划与上线状态使用独立请求和独立错误状态。规划加载成功后立即展示 Backend 已保存的稀疏规划行并保持可编辑，不等待上线状态；不会按全部站点自动补齐占位规划行。上线状态失败只在概览局部提示并保留最后成功结果。任一请求下次成功只清除自身错误。接口或网络错误不进入规划字段校验，因此“有 N 项需要修正”只统计站点匹配、AP 数量、管理 VLAN、序号和重复项等真实草稿问题。

上线概览只返回站点统计、少量诊断计数、生成时间和来源 revision，不内嵌完整排除项或待关联在线 AP。用户点击对应明细后，页面分别调用 `/plan/online-status/excluded` 和 `/plan/online-status/unmatched` 分页读取；默认页大小为 50，空 MAC 以空字符串返回。概览按规划、FIT-AP、AP Identity 和局点元数据 revision 缓存，来源不变时直接复用，`source_revision=0` 仍是合法 revision。缓存命中状态和阶段耗时进入诊断日志，不改变统计口径。

规划编辑仍属于基础资料编辑会话。Renderer 只维护草稿，保存通过 `POST /api/rail-transit/base-data/changes` 进入 `RailTransitBaseDataApplicationService`，与其他基础资料共享 revision 检查和 SQLite `BEGIN IMMEDIATE` 单事务；失败整体回滚。修改规划不会连接 AC 或自动刷新设备状态。

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

实际上线数量复用现有 FIT-AP 在线状态，并通过轨旁 AP 参考资料映射到稳定 `station_id`。站点范围来自当前有效站点与逐站规划，不依赖 AP 参考资料或 FIT-AP 资源是否已经导入。参考资料记录数本身不作为统计字段或上线率分母：

```text
未上线 = max(规划 AP 总数量 - 实际上线数量, 0)
站点上线率 = 实际上线数量 / 规划 AP 总数量
总上线率 = 实际上线合计 / 规划 AP 总数量合计
```

规划 AP 总数量为 `0` 时上线率为空，由页面显示为 `—`。实际上线超过规划值时保留真实数量、未上线仍为 `0`，状态显示“超规划”，上线率显示 `—`，不得导出 `1200.0%`、`5200.0%` 等误导性比例。缺少规划的有效站点仍显示为 `planning_missing`，而有规划但没有匹配 FIT-AP 时实际为 `0`、未上线等于规划数量。参考资料数量与规划值不同只作为轻量数据质量信息，不修改规划、不阻断保存；未匹配有效资料的在线 AP 进入独立“待关联在线 AP”诊断，不计入站点，也不计入真正排除项。统计更新时间来自当前 AP/FIT-AP 数据的最新时间；用户点击“刷新上线状态”时复用现有轨旁 AP 后台任务，只刷新实际上线结果，不修改页面规划草稿。

上线概览不是轨旁 AP 业务明细的数据源。页面查询、业务明细导出和上线概览共享同一解析结果，但分为三层：站点/交换机工作范围决定候选端口，AP 基础资料用于身份和站点关联，FIT-AP 运行态用于在线统计。当前局点/项目及显式建设阶段匹配、当前工作状态为 `included` 的站点交换机不因缺少 AP 资料而消失；AP 参考资料按有效 `station_id`、UUID/MAC/受控唯一名称去重。暂不参与、跨项目、明确排除、阶段不匹配、站点关联不唯一才进入排除项；在线但未关联基础资料的资源进入 `unmatched_online_items`。没有显式建设阶段时不按站名猜测一期或延长线。

## 来源

活动页面不提供轨旁 AP 规划模板导入、模板下载或规划导出。站点来源统一来自设备管理中“车站”分组设备的 `station` 字段：点击“从设备管理生成站点”后先展示候选、匹配和冲突，用户确认后只写入基础资料编辑草稿，最终由统一保存事务提交。这样每条规划行都能绑定正式站点的稳定 `station_id`，不会因为站名文本差异丢失身份。

旧规划 XLSX 解析、导出和对应 API 不属于当前活动 UI，也不参与当前规划读取；不再新增模板格式或兼容字段。轨旁 AP 业务页仍可按自身契约导出业务明细和上线概览，但不改变规划维护来源。

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
