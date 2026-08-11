---
name: netconsole-trackside-ap-skill
description: "NetConsole 轨旁 AP 业务、逐站规划关联、FIT-AP/LLDP/交换机端口、光衰、H3C/ZTE 采集、AP Identity 消费、外部终端、业务快照/导出或明确的 WPS 云文档同步任务时使用。基础资料通用维护、普通 AC 资源或无轨旁作用域的 Identity 不使用本 Skill。"
---

# 目标

维护轨旁 AP 从稳定基础资料、规划、交换机与 FIT-AP 运行事实到页面、更新任务和导出的只读业务投影，禁止用模糊关联掩盖身份和 revision 缺口。

# 触发与反例

触发示例：

- “修复轨旁 AP 规划/上线统计、LLDP 关联或光衰更新。”
- “增加 H3C/ZTE 交换机采集、外部终端或业务导出字段。”
- “用户明确要求调整轨旁 AP WPS 云文档同步。”

不应触发：

- “只维护线路、站点、区间或列车基础资料。”
- “普通 AC/FIT-AP 页面或无轨旁作用域的 AP Identity。”

# 输入与输出

- 输入：局点与作用域、稳定 ID、来源 revisions、AP/交换机证据、查询/选择范围、更新或导出目标。
- 输出：轨旁 Application/Query Service、Job/API/Vue/Export 的最小修改、关联证据、兼容风险和验证。
- 允许修改生产代码：允许，限轨旁 AP 业务及其直接适配；不得借此改写 AP Identity 基础规则、AC 主数据或基础资料所有权。

# 开始前读取

- `docs/rail-transit/TRACKSIDE_AP_DOMAIN_MODEL.md`、`docs/AP_MANAGEMENT_VLAN_GROUPS.md`、`docs/TRACKSIDE_AP_BUSINESS_SNAPSHOT.md`。
- `docs/RAIL_TRANSIT_BASE_DATA.md`、`docs/AC_MANAGEMENT.md`、`docs/AP_IDENTITY.md` 和当前消费者审计。
- `src/netconsole/services/trackside_ap_business.py`、`src/netconsole/services/rail_transit/trackside_ap_business_query_service.py`。
- `src/netconsole/services/rail_transit/trackside_ap_business_snapshot.py`、`src/netconsole/services/rail_transit/trackside_ap_update_job.py`。
- `src/netconsole/backend/api/trackside_ap_business_router.py`、目标 DTO、Repository、Vue/API 和相关测试。
- 仅在用户明确要求 WPS 云同步时读取 `docs/WPS_TRACKSIDE_AP_SYNC.md` 和 `src/netconsole/services/wps_trackside_ap_sync.py`。

# 当前架构事实

- 正式站点、区间、轨旁 AP 基础资料和规划由基础资料 Application Service 拥有；轨旁 AP 业务没有第二套主表，是多来源稳定快照的只读组合。
- 关系使用 `device_uuid/station_id/section_id/AP UUID/Identity entity ID/完整 MAC`；站名、VLAN、AP 名称、邻居 IP 和相似度不能直接识别 AP。
- FIT-AP `R/M`、`R/B` 表示在线；AP Rx 严格小于 `-13.90 dBm` 才是业务光衰异常，等于门限正常；规范化型号 `WA6522` 为不适用。
- 页面和导出共用稳定业务投影；导出 Worker 必须按 expected revision 重建、冻结并验证 staging 快照，不能消费页面当前页或可变对象。
- WPS 云文档是独立、显式启用的在线能力；普通轨旁导出默认只走本地 Export Process，不得顺手引入 WPS API/KDocs 同步。

# 工作流程

若变更触及 AP Identity、Task/Job、Export/Artifact、共享快照或设备采集契约，编码前先组合 `netconsole-change-review-skill` 完成消费者审计。

1. 列出基础资料、规划、设备范围、交换机事实、LLDP、FIT-AP、光衰、Identity 和历史导出来源，以及各自 revision、写入者和读取边界。
2. 对站点/AP/交换机关联只使用稳定 ID 或唯一精确证据；多候选、跨站冲突、来源缺失和陈旧快照保留结构化 unresolved/ambiguous/reason code。
3. AP Identity 在每个请求固定一次 revision，批量解析去重 MAC；查询只读索引，不触发 rebuild，不选 ambiguous 第一项。
4. 保持在线、光衰、位置/端口和规划为独立事实维度；不得让光衰异常、LLDP 冲突或规划覆盖 FIT-AP 在线状态。
5. 轨旁更新按目标类型调用现有 H3C/ZTE Profile/Job，保留命令、接口规范化、最近有效 VLAN 和部分来源失败语义。
6. 页面携带 expected revision 分页；revision 变化时清空旧选择并从第一页重载，不拼接不同 revision 的结果。
7. 导出范围只接受 station/query/稳定 row IDs，先由 Worker 冻结 snapshot，再由既有 formatter 生成 Artifact；页面“仅光衰异常”不改变正式导出范围。
8. 外部终端只提交业务投影中已确定的交换机 UUID 或 `ac_device_uuid + ap_uuid`，复用设备/AC 受控预检，不从名称或 MAC 再查询。
9. 仅在明确 WPS 任务中维护 Binding、部署身份、异步恢复和同一冻结 Workbook；Token 不进入任务、日志或 API，远端结果未知时不得重复 POST。

# 禁止模式与不变量

- 不做跨站、模糊名称、VLAN、邻居 IP、MAC 前后缀或“第一条候选”关联。
- 不让业务 GET、上线概览、LLDP 投影或 Identity 查询写回基础资料、规划、设备绑定或 AP Identity。
- 不把页面当前页、复选框或异常筛选作为 XLSX 真源，不在 Renderer 生成工作簿。
- 不擅自改变 `-13.90 dBm`、WA6522、FIT-AP 在线状态、工作表或旧文件兼容契约。
- 不因普通本地导出需求新增 WPS 云能力，也不远程替用户编辑或发布 AirScript。

# 验证与失败报告

- 覆盖 exact/unresolved/ambiguous、站点一致性、LLDP snapshot stale、交换机身份冲突、FIT-AP 在线/未知、门限边界和 WA6522。
- 覆盖 R1/R2 稳定读取、expected revision、分页/选择 stale、冻结 staging 哈希、Worker 重启清理和导出字段/排序。
- 运行受影响的 `test_trackside_ap_*`、`test_effective_trackside_ap_scope.py`、目标 H3C/ZTE/AC 测试及 `TracksideApBusinessView` 定向 Vitest。
- 报告消费者、来源 revision、关联规则、命令/阈值是否变化、数据库/导出/WPS 影响和真实设备/Excel/WPS 未验证边界。

# 相关 Skills

- L3/L4 影响审计：`netconsole-change-review-skill`。
- 基础资料：`netconsole-rail-base-data-skill`。
- AC/FIT-AP 与 AP Identity：`netconsole-ac-management-skill`、`netconsole-ap-identity-skill`。
- 设备采集/终端：`netconsole-device-management-skill`。
- Job、导出和数据：`netconsole-job-center-skill`、`netconsole-export-report-skill`、`netconsole-data-safety-skill`。
