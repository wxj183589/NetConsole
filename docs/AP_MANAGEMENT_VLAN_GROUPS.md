# 轨旁 AP 逐站规划与 VLAN 分组兼容

## 当前模型

轨旁 AP 规划当前以“一座车站一行”为用户模型和业务事实。每行保存稳定 `station_id`、序号、车站名称、规划 AP 总数量、AP 起始地址、掩码、网关、管理 VLAN 和备注。管理 VLAN 只表示该站 AP 的目标管理 VLAN，不是 AP、站点或区间的身份。

- 每站填写不同 VLAN 表示每站独立；
- 多个站填写相同 VLAN 表示共享 VLAN；
- 全部站填写相同 VLAN 表示全线统一；
- 管理 VLAN 不设唯一约束，也不触发分组、合并或地址计算。

规划 AP 总数量是当前经项目确认后应建设、应上线的有效目标，由用户手工维护，允许为 `0`，也允许按现场情况核减或调整。最初设计数量和核减原因记录在备注中，不另设字段。AC 状态、轨旁 AP 参考资料记录数和 VLAN 兼容模型均不得覆盖该值。AP 起始地址、掩码和网关是规划参考字段；起始地址允许末段 `X/x`，掩码允许前缀或点分十进制格式。这些字段不生成 AP、不修改实际 IP，也不参与 VLAN 自动规划。

## 页面与保存

`/rail-transit/base-data?tab=trackside-ap-planning` 提供两个子页：

- “AP 规划维护”：直接编辑逐站表，支持新增、单行或批量删除、保存、撤销、Excel 多行多列粘贴、简单模板导入预览和已保存规划导出；
- “AP 上线情况概览”：只读展示规划 AP 总数量、实际上线、未上线、上线率和备注，并显示按数量汇总的线路合计。

页面不再展示规划方式、VLAN 组、组边界、拆分合并、revision 或全局阻断问题。字段错误定位到单元格；未分配站点 AP 只显示普通警告和明细入口，不阻止规划维护，也不计入线路合计。

规划编辑仍属于基础资料编辑会话。Renderer 只维护草稿，保存通过 `POST /api/rail-transit/base-data/changes` 进入 `RailTransitBaseDataApplicationService`，与其他基础资料共享 revision 检查和 SQLite `BEGIN IMMEDIATE` 单事务；失败整体回滚。修改规划不会连接 AC 或自动刷新设备状态。

当前用户接口包括：

```text
GET  /api/rail-transit/trackside-ap-business/plan
GET  /api/rail-transit/trackside-ap-business/plan/online-status
POST /api/rail-transit/trackside-ap-business/plan/import/preview
POST /api/rail-transit/trackside-ap-business/plan/export
GET  /api/rail-transit/trackside-ap-business/plan/artifacts/{artifact_id}/download
```

旧 `/plan/auto-group-preview`、`/plan/adjustment-preview`、`/plan/mode-impact-preview`、`/plan/validate`、`/plan/address-preview`、`/plan/effective-network`、`/plan/point-table-preview` 和 `/plan/save` 暂时保留为兼容 API，不再由活动页面调用。专用 `trackside_ap_plan_save` Job 同样只服务旧消费者；当前页面保存入口是基础资料统一事务。

## 上线统计

实际上线数量复用现有 FIT-AP 在线状态，并通过轨旁 AP 参考资料映射到稳定 `station_id`。参考资料记录数本身不作为统计字段或上线率分母：

```text
未上线 = max(规划 AP 总数量 - 实际上线数量, 0)
站点上线率 = 实际上线数量 / 规划 AP 总数量
总上线率 = 实际上线合计 / 规划 AP 总数量合计
```

规划 AP 总数量为 `0` 时上线率为空，由页面显示为 `—`。实际上线超过规划值时保留真实数量、未上线仍为 `0`，状态显示“超规划”，上线率显示 `—`，不得导出 `1200.0%`、`5200.0%` 等误导性比例。参考资料数量与规划值不同只作为轻量数据质量信息，不修改规划、不阻断保存；未匹配有效资料的在线 AP 单独提示且不计入任何站点。统计更新时间来自当前 AP/FIT-AP 数据的最新时间；用户点击“刷新上线状态”时复用现有轨旁 AP 后台任务，只刷新实际上线结果，不修改页面规划草稿。

上线概览不是轨旁 AP 业务明细的数据源。页面查询、业务明细导出和上线概览都先解析同一“当前项目有效轨旁 AP 范围”：当前局点/项目及显式建设阶段匹配、投运状态为在用、具有有效 `station_id` 和稳定 AP 身份。暂停、停用、退役、跨项目、明确排除、站点关联不唯一及未匹配在线资源进入排除项；同一 AP 按 UUID、MAC 或受控唯一名称去重。没有显式建设阶段时不按站名猜测一期或延长线。

## 导入导出

“下载模板”生成 `轨旁AP逐站规划模板.xlsx`。可见工作表只有 `AP规划`，固定包含：

1. 序号
2. 车站名称
3. 规划AP总数量
4. AP起始地址
5. 掩码
6. AP网关
7. AP管理VLAN
8. 备注

模板首行是表头并冻结、启用筛选，不使用合并单元格或复杂公式。序号、规划 AP 总数量和 AP 管理 VLAN 写为整数，掩码、`X/x` 地址和备注保留文本语义，备注自动换行。隐藏 `_netconsole_meta` 使用 `template_type=trackside_ap_station_plan`、`schema_version=2`，并记录生成时间、项目和线路标识。

“导出当前”只读取已保存规划，生成 `<线路名>_轨旁AP规划及上线概览_<YYYYMMDD>.xlsx`：

- `AP规划`：与模板相同的 8 列，可重新导入；
- `AP上线情况概览`：归属站点、规划 AP 总数量、实际上线、未上线、上线率和备注，并包含加粗合计行；上线率保存为真正的百分比数值且保留一位小数；
- `_netconsole_meta`：隐藏文件契约，不影响用户填写。

导入 XLSX 时只读取 `AP规划`，忽略 `AP上线情况概览`，因此实际上线、未上线和上线率不能覆盖规划草稿。导入预览仍可直接修改 8 个规划字段，应用时一次性进入页面草稿，之后继续统一保存。

轨旁 AP 业务导出的“轨旁AP业务明细”和“AP上线情况概览”复用同一个已解析范围对象。概览只汇总明细所对应的当前项目有效 AP，不得再次合并全线路基础站点或 AC 返回的全量 FIT-AP。

任务型导出继续通过固定动作、共享用户目标协调器、Export Process 和受控 Artifact 落盘。用户取消保存位置时不创建任务；Artifact 保存失败后可以手工重新另存。

旧工作表名“轨旁AP规划”、旧表头“AP数量”和旧 22 列 VLAN 分组模板继续可导入。兼容转换优先读取站点级字段，站点级管理 VLAN 为空时回退旧组级“管理VLAN”；组编号、名称、边界、成员、模式、手工锁定和 revision 不进入新页面。预览只显示一次非阻塞提示“已识别旧版 VLAN 分组模板，将转换为逐站 AP 规划。”

## PVID 与历史兼容层

PVID 候选和核验优先读取当前逐站规划的 `management_vlan`。多个站使用相同 VLAN 合法；核验不能把 VLAN 当作唯一站点身份，也不能通过 VLAN 反推 AP 归属。AP 身份仍由现有 AP MAC、Radio MAC、AP ID 和稳定设备 ID 解析。

`devices.db` 继续保留以下历史表及数据，不执行破坏性删除：

- `rail_ap_vlan_plans`
- `rail_ap_vlan_groups`
- `rail_ap_vlan_group_members`
- `rail_ap_vlan_assignments`
- `rail_ap_vlan_allocations`

这些表是旧 VLAN 分组 API、旧点表和回滚的兼容层，不再由活动 UI 编辑。当前逐站事实保存在扩展后的 `ac_trackside_ap_plan(mode='unified')`；无逐站记录时，读取链可把旧 VLAN 组投影为逐站行。用户在新页面保存后只替换逐站记录，不覆盖或删除历史分组数据。

旧数据库初始化会幂等增加 `station_id`、`sequence_no`、`subnet_mask` 和 `management_vlan`，补齐旧值，并为有效 `station_id` 和正序号建立局部唯一索引。旧库序号为零或重复时按既有顺序确定性重排后再建索引。迁移、索引和 schema version 写入位于同一初始化事务，失败整体回滚；验证只能使用临时数据库或真实数据库备份副本。
