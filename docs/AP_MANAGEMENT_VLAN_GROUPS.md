# 轨旁 AP 管理 VLAN 分组规划

## 模型与边界

轨旁 AP 管理 VLAN 归属统一建模为“AP 管理 VLAN 组”。本模块只规划“哪个站点或哪几个站点使用哪个 AP 管理 VLAN”。站点和区间描述 AP 的业务位置；VLAN 组描述 AP 的管理 VLAN 归属。两者不得互相推断，VLAN 也不是站点或 AP 的唯一身份。AP 身份仍以 AP MAC、Radio MAC、AP ID 和现有稳定设备 ID 为准。

三种规划方式只决定如何生成初始 VLAN 组。点表和 PVID 核验使用同一个有效 VLAN 组解析流程：

| 规划方式 | 内部值 | 分组规则 |
| --- | --- | --- |
| 全线统一 VLAN | `line_single` | 全线只有一个组，不受 4 站上限限制 |
| 每站独立 VLAN | `station_independent` | 每个站点一个组，兼容旧规划 |
| 按站点分组 VLAN | `station_grouped` | 每组必须包含连续的 1～4 站，不同组大小可以不同 |

所有正式站点必须且只能属于一个 VLAN 组。分组不能遗漏、重复、交叉或跳过中间站；组成员保存稳定 `station_id` 和站序，起止站名称只是展示结果。新增站点保持未分配，直到用户明确加入某组、新建组或重新分组。删除站点仅移除该成员；空组需要用户修复或删除。站序调整使分组不连续时标记为阻断问题，不会静默重组。

## 示例

全线统一 VLAN：29 站均属于一个组，只配置管理 VLAN 71 即可保存，不受 4 站上限限制，也不要求配置 IP、掩码或网关。

4、4、2 自动分组：10 站选择 `station_grouped`、每组 4 站，生成 `01～04`、`05～08`、`09～10` 三组；每组只需维护管理 VLAN。

1、3、4、2 手工分组：可从自动结果拆分或合并相邻组形成 `01`、`02～04`、`05～08`、`09～10`。只有相邻组可合并；合并后超过 4 站时阻断，全线统一模式除外。

## 有效 VLAN 与 IP 参考边界

每个 VLAN 组保存：

- `group_id / group_code / group_name / sequence`；
- `management_vlan`；
- 备注和稳定站点成员；
- 兼容保留的 `network_address / prefix_length / subnet_mask / default_gateway / ap_start_ip / ap_end_ip` 参考字段。

有效 VLAN 组由领域服务统一解析，优先级为 AP 级覆盖、明确站点继承、已保存的区间默认归属、已保存的区间起点默认归属。区间 AP 默认使用起点站所属组时会生成可见、可持久化的 assignment；用户可以改成其他组或 AP 级覆盖。覆盖只改变 VLAN 归属，不修改 AP 的站点、区间、名称、MAC、既有 IP 或设备关系。

IP、网络地址、掩码、前缀、网关和 AP 起止地址只作兼容读取、导入导出或只读参考展示。本模块不生成、不重算、不校验、不修改 AP IP，也不计算地址容量。上述字段为空、格式错误、子网不匹配、范围重叠、容量不足或 IP 重复均不影响 VLAN 规划保存、基础资料保存或 PVID 核验。

不同组使用相同 VLAN 合法且不自动合并；只显示非阻断提示。相邻组 VLAN 相同时提示“如实际属于同一管理域，可考虑合并”。多个站点复用同一 VLAN 不会合并或丢失 AP。

旧 `reallocation_policy`、地址策略和影响 DTO 中的 IP/网关/手工地址计数字段仅为 API 兼容，生产路径忽略地址重算请求并返回 `0`。旧模板中的 IP 或 `X` 占位符可继续作为参考导入；格式异常不升级为 VLAN 规划错误。

## 页面、API 与并发

`/rail-transit/base-data?tab=trackside-ap-planning` 保持“解锁后编辑、保存后锁定”，提供：

- 顶部规划方式、自动每组 1～4 站和模式影响预览；
- VLAN 组视图，只展示组序号、组名称、起止站、站点数、AP 数、管理 VLAN、校验和备注；管理 VLAN 修改使用编辑前快照并经过 Backend 影响预览；
- 按站点视图，展示站点、AP 数、VLAN 组、继承的管理 VLAN、中文来源和备注；
- 拆分组、合并相邻组、新增/删除空组，并用稳定站点 ID 调整成员和分组边界；
- “查看 AP/参考信息”弹窗只读展示组网络、掩码/前缀、网关、AP 起止地址和既有 AP IP，并可维护区间默认组和 AP 级覆盖；弹窗明确说明 VLAN 规划不生成、不校验、不修改 IP；
- 导入预览和导出；
- 原/新 VLAN 组数、受影响站点/AP、管理 VLAN 变化和冲突/提示数量。

VLAN 分组规则位于 Python 领域服务，Vue 不复制规则。FastAPI 只适配 DTO，Application Service 编排站点/AP 上下文、预览、保存和导出，Repository 在事务内保存。接口覆盖查询规划、自动分组、调整/模式影响、校验、兼容地址预览、点表预览、有效 VLAN 查询、导入预览、保存和导出。兼容地址预览不再分配地址。新模板导入优先按“组成员站点 ID/名称”的同序映射恢复稳定成员，旧模板回退按名称匹配；同一文件中相同组编号的管理 VLAN 必须一致，IP 参考值不一致不阻断预览。线路规划保存带整数 `revision`；revision 不一致返回冲突，禁止后提交静默覆盖。

规划与基础资料一起保存时，VLAN 组、成员、assignment、allocation 和旧站点级兼容投影位于同一个 SQLite 事务，任一写入失败整体回滚。

## 点表、导入导出与 PVID

点表的管理 VLAN、组 ID 和组名称来自 AP 的有效 VLAN 组；AP IP 优先读取既有 AP `management_ip` 等独立资料，兼容 allocation 参考值只作回退。本模块不生成点表 IP。点表不能通过 VLAN 反推站点；VLAN 规划本身有效但某个 AP 无法解析有效 VLAN 组时，点表预览单独拒绝该 AP，不影响 VLAN 规划保存。IP 为空、非法或重复不阻止点表输出。

新模板同时包含规划方式、VLAN 组编号/名称/起止站、成员稳定 ID、管理 VLAN、网络/掩码、网关、组地址范围、分配顺序、锁定状态和备注，并保留原有车站名称、AP 数、AP 起始地址、掩码、网关和管理 VLAN 列。旧模板缺少组字段时逐站转换为 `station_independent`，不会因相邻站参数相同而自动合并。导出继续由独立 Export Process 写临时文件并原子提交。

端口候选发现可以使用全线已规划 VLAN 集合，但最终 PVID 核验必须在 AP 身份已解析后执行：

```text
端口实际 PVID
    对比
已识别 AP 的有效 VLAN 组 management_vlan
```

不得用交换机或端口所属站点收窄为“该站唯一 VLAN”。同组跨多个站点 PVID 相同、全线统一 VLAN 下大量端口 PVID 相同均为正常。核验结果保留交换机、端口、AP、站点、规划 VLAN、VLAN 组和 `matched / mismatched / unresolved` 状态。现有交换机侧没有正式的厂商配置生成器，本次不臆造设备命令；未来配置导出必须复用同一有效 VLAN 组解析器，且不得覆盖业务 VLAN、Trunk、Hybrid Tag、视频 VLAN 或非轨旁 AP 端口。

## 数据库迁移

`devices.db` 保留：

- `rail_ap_vlan_plans`：线路级模式、自动分组参数、兼容地址策略和 revision；
- `rail_ap_vlan_groups`：VLAN 组核心字段及兼容 IP 参考列；
- `rail_ap_vlan_group_members`：稳定站点成员；
- `rail_ap_vlan_assignments`：区间默认与 AP 覆盖；
- `rail_ap_vlan_allocations`：兼容 AP/IP 参考缓存，不是 VLAN 或 AP IP 的事实源。

初始化时若新表尚无规划且旧 `ac_trackside_ap_plan(mode='unified')` 有数据，则在当前数据库初始化事务中迁移：每个旧站点生成一个组、模式设为 `station_independent`，完整保留 VLAN、掩码、网关、起始地址、备注和站序。存在正式 `node_uid` 时由其派生稳定站点 ID，否则使用规范站名的兼容稳定 ID。新规划存在时不重复迁移；初始化失败整体回滚。旧 allocation 表的 `planned_ip` 唯一约束会在同一初始化事务中移除并原样复制既有记录，使重复参考 IP 不再阻止保存。`ac_trackside_ap_plan` 继续作为旧消费者的站点级有效值投影，不再是新模型事实源。

迁移验证只使用测试数据库或真实数据库备份副本，禁止直接操作正式数据根。
