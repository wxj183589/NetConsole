# 轨旁 AP 逐站规划与 VLAN 分组兼容

## 当前模型

轨旁 AP 规划当前以“一座车站一行”为用户模型和业务事实。每行保存稳定 `station_id`、序号、车站名称、设计 AP 数量、AP 起始地址、掩码、网关、管理 VLAN 和备注。管理 VLAN 只表示该站 AP 的目标管理 VLAN，不是 AP、站点或区间的身份。

- 每站填写不同 VLAN 表示每站独立；
- 多个站填写相同 VLAN 表示共享 VLAN；
- 全部站填写相同 VLAN 表示全线统一；
- 管理 VLAN 不设唯一约束，也不触发分组、合并或地址计算。

AP 数量是设计值，允许为 `0`，不要求等于实际轨旁 AP 数量。AP 起始地址、掩码和网关是规划参考字段；起始地址允许末段 `X/x`，掩码允许前缀或点分十进制格式。这些字段不生成 AP、不修改实际 IP，也不参与 VLAN 自动规划。

## 页面与保存

`/rail-transit/base-data?tab=trackside-ap-planning` 提供两个子页：

- “AP 规划维护”：直接编辑逐站表，支持新增、单行或批量删除、保存、撤销、Excel 多行多列粘贴、简单模板导入预览和当前草稿导出；
- “AP 上线统计”：只读汇总规划数量、有效 AP 总数、上线、未上线、上线率和备注，并显示加权线路合计。

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

统计从实际有效的轨旁 AP 基础资料读取 AP 集合，并复用现有 FIT-AP 在线状态，不从规划数量生成 AP：

```text
未上线 = max(AP 总数量 - 上线数量, 0)
站点上线率 = 上线数量 / AP 总数量
总上线率 = 上线合计 / AP 总数量合计
```

AP 总数量为 `0` 时上线率为空，由页面显示为 `—`。明确暂停使用、退役或不参与统计的 AP 被排除；单个站点规划数量与实际数量不同不是错误。统计更新时间来自当前 AP/FIT-AP 数据的最新时间；用户点击“刷新上线状态”时复用现有轨旁 AP 后台任务。

## 导入导出

新模板和当前规划导出只包含：

1. 序号
2. 车站名称
3. AP数量
4. AP起始地址
5. 掩码
6. AP网关
7. AP管理VLAN
8. 备注

任务型导出继续通过固定动作、共享用户目标协调器、Export Process 和受控 Artifact 落盘。用户取消保存位置时不创建任务；Artifact 保存失败后可以手工重新另存。

旧 22 列 VLAN 分组模板继续可导入。兼容转换优先读取站点级字段，站点级管理 VLAN 为空时回退旧组级管理 VLAN；组编号、名称、边界、成员和模式不会进入新页面。预览明确提示“已识别旧版 VLAN 分组模板，将转换为逐站 AP 规划。”

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
