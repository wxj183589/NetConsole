---
name: netconsole-rail-base-data-skill
description: "NetConsole 轨道交通基础资料、线路、站点、区间、设备站点绑定、轨旁 AP 基础资料/逐站规划、列车/车载 MR、模板导入导出、编辑 scope、revision 冲突或单事务保存任务时使用。轨旁 AP 运行态、Ground 或 Online MR 采集不使用本 Skill。"
---

# 目标

维护轨交基础资料唯一编辑聚合、稳定身份和 revision 事务，确保查看、草稿、导入来源与 AC/MESH 等运行态严格分层。

# 触发与反例

触发示例：

- “修改线路、站点、区间、列车或 MR 基础资料。”
- “从设备管理生成站点，处理 station_id/revision 冲突。”
- “调整轨旁 AP 基础资料、逐站规划或 XLSX 导入导出。”

不应触发：

- “修改轨旁 AP 在线、LLDP、光衰或业务快照。”
- “修改 Ground Unattended 或 Online MR 实时采集。”

# 输入与输出

- 输入：目标 scope、正式资料、来源候选、稳定 ID、base revision、校验/保存/回滚与文件契约。
- 输出：Application/Query Service、Repository、API/Vue 草稿链的最小修改、事务和兼容性说明、测试证据。
- 允许修改生产代码：允许，限基础资料纵向链和测试；不得把 AC/FIT-AP、MESH、Ground 或 Online MR 运行态写回正式资料。

# 开始前读取

- `docs/RAIL_TRANSIT_BASE_DATA.md`、`docs/rail-transit/TRACKSIDE_AP_DOMAIN_MODEL.md`、`docs/AP_MANAGEMENT_VLAN_GROUPS.md`。
- `src/netconsole/application/rail_transit/base_data_application_service.py`、`src/netconsole/services/rail_transit/base_data_query_service.py`。
- `src/netconsole/services/rail_transit/base_data_import_service.py`、`src/netconsole/services/rail_transit/base_data_write_guard.py`。
- `src/netconsole/repositories/rail_transit_base_data_repository.py`、`src/netconsole/backend/api/rail_transit_base_data_router.py`。
- `apps/desktop_renderer/src/views/rail-transit/RailTransitBaseDataView.vue`、对应 Store/组件/API 和相关测试。

# 当前架构事实

- `/rail-transit/base-data` 是站点、设备绑定、区间、轨旁 AP、逐站规划、列车和 MR 的唯一编辑入口；不建立第二套基础资料数据库。
- 页面按子页 scope 独立 `VIEW/EDITING/DIRTY/VALIDATING/SAVING/SAVE_FAILED/READ_ONLY`；只有显式解锁才读取编辑快照和创建草稿。
- 关系使用稳定 `station_id/section_id/device_uuid`；站名、区间名、VLAN、设备名和 IP 只是属性或来源证据。
- 普通 GET 使用只读查询，不初始化 schema、不迁移、不写缓存、不触发 AP Identity rebuild 或设备采集。
- 正式资料、导入来源和 AC/FIT-AP/MESH/Online MR 运行态必须分层；运行态只用于展示或候选提示。

# 工作流程

若变更触及 schema/revision、AP Identity、共享导入导出、Feature 或 DataRoot，编码前先组合 `netconsole-change-review-skill` 完成消费者审计。

1. 先确认变更属于哪个 scope，列出该 scope 可读依赖、允许写入实体、稳定 ID、base revision 和离开/失败行为。
2. 编辑基线只来自同 revision 的服务端 edit snapshot，不从分页、筛选、Pinia 查看缓存或运行态拼接草稿。
3. 站点来源只使用当前局点“车站”分组设备的 `devices.station`；不得从 `name/system_name/location/IP` 或模糊文本推断站点。
4. 校验站点顺序、引用、MAC/IP、规划 VLAN 和 scope 边界；revision 不一致返回冲突并保留草稿，不自动覆盖或重放。
5. 按站点 -> 设备绑定 -> 区间 -> 轨旁 AP -> 逐站规划 -> MR 在一个 `BEGIN IMMEDIATE` 事务提交；任一步失败整体回滚。
6. AP Identity 只在已提交的来源 revision 变化后以独立事务收口一次；查询、预览和页面刷新保持只读。
7. 导入先解析到预览/草稿，保留来源、哈希、冲突和空值 KEEP 语义；用户明确保存当前 scope 后才写正式资料。
8. 用户可见模板、导入和导出复用统一文件交互与 Export Process；取消保存不创建任务或显示成功。

# 禁止模式与不变量

- 不用名称、VLAN、里程接近、当前 Mesh 关联或设备 IP 猜测稳定关系。
- 不在逐站规划子页临时创建站点；缺少正式 `station_id` 时回到站点与区间 scope 维护。
- 不让轮询、GET、导入预览或页面加载修改数据库、revision、Identity 或正式资料。
- 不把运行态在线、RSSI、光衰、当前关联或未保存草稿写入正式基础资料。
- 不在测试中读取机器级指针或正式数据根；写入测试只使用隔离根或明确副本。

# 验证与失败报告

- 覆盖各 scope 锁定/解锁、脏状态、切页保护、revision 冲突、作用域拒绝、事务回滚、稳定 ID 和 GET 只读指纹。
- 覆盖设备站点来源、冲突/合并/删除预检、区间生成、轨旁 AP/规划/MR 校验、旧模板和导入空值。
- 运行受影响的 base data Query/API/Edit pytest、Repository 测试和 `RailTransitBaseDataView`/Store/组件定向 Vitest。
- 报告 scope、写入顺序、schema/正式数据影响、Identity 刷新、导入导出、回滚和正式局点人工限制。

# 相关 Skills

- L3/L4 影响审计：`netconsole-change-review-skill`。
- 轨旁 AP 运行态：`netconsole-trackside-ap-skill`。
- 设备来源：`netconsole-device-management-skill`。
- 身份与数据安全：`netconsole-ap-identity-skill`、`netconsole-data-safety-skill`。
- 文件交互和导出：`netconsole-user-file-interaction-skill`、`netconsole-export-report-skill`。
