---
name: netconsole-mesh-analysis-skill
description: "MR 原始 MESH 日志、离线导入、ACTIVE/STANDBY 主备链、Peer/Radio、RSSI、Channel Busy、短时建链、乒乓切换、降采样、图表或 MESH 报告任务时使用。在线 MR SSH 实时采集、普通 SNMP 或非 MESH 光衰分析不使用本 Skill。"
---

# 目标

维护离线 MR MESH 日志的导入、解析、主备链生命周期、切换判定、图表和报告，保证统计与展示规则一致且可追溯。

# 触发与反例

触发示例：

- “主链路建链顺序错误、备份链路为空。”
- “Peer Radio/最小 RSSI/Channel Busy 没识别。”
- “短时建链或乒乓切换判定错误，单 AP 图表闪退。”

不应触发：

- “修改车载 MR 实时 SSH 采集。”
- “普通 SNMP 采集或不涉及 MESH 的 AP 光衰。”

# 输入与输出

- 输入：raw 日志/fixture、分析参数、期望主备链/事件、图表或报告问题。
- 输出：parser/domain/Repository/UI/report 的最小修改、参数与 Identity 边界说明、测试证据。
- 允许修改生产代码：允许，限 MESH 分析链和测试；不得改变在线采集命令、AP 主身份或无关数据库。

# 开始前读取

- `docs/mr_mesh_log_analysis_rules.md`、`docs/MR_MESH_AP_IDENTITY_ASSESSMENT.md`。
- `src/netconsole/backend/api/online_mr_router.py`、`apps/web/src/views/rail-transit/MeshAnalysisView.vue`、`apps/web/src/components/mesh-analysis/`。
- `src/netconsole/services/mesh_chart_payload.py`、`src/netconsole/services/mesh_peer_mapping_service.py`。
- `src/netconsole/parsers/mesh_log_parser.py`、`src/netconsole/services/mesh_log_analysis_service.py`、`src/netconsole/services/mesh_analysis_params_service.py`。
- `src/netconsole/services/mr_mesh_identity_shadow.py`、`src/netconsole/repositories/mesh_catalog_repository.py`、`src/netconsole/repositories/mesh_mr_repository.py`。
- `src/netconsole/models/mesh_log_models.py`、`src/netconsole/models/mesh_analysis_params.py`、`src/netconsole/resources/mesh_quality_rules.json`、`tests/test_mesh_log_analysis.py`。

# 工作流程与规则

1. 从 raw log、参数快照和现有测试重建 ACTIVE 生命周期、主链、备链和主链建链顺序；不凭单条样例猜规则。
2. 分清 Peer Name、Peer MAC、Peer Radio MAC、AP MAC、Radio/BSSID 和同 AP 双射频；不能简单合并为同一身份。
3. 兼容无 Peer Name 但有 Peer MAC、字段缺失、WiFi 4/5/6 和当前 V5/V7/V9 样例。
4. 主链切换时间、短时容差、乒乓窗口和同 AP 双射频规则从 `MeshAnalysisParams`/源文件快照读取，不写死经验值。
5. 乒乓基于 AP 级主链序列和有效返回窗口；超窗往返不算异常，同 AP Radio 往返单独分类。
6. RSSI、最小 RSSI、发送/接收忙度和日志上报时长保持可追溯；显示降采样不得改变统计。
7. 备份链缺失先检查 parser、归一化、source_file_id 和 Identity shadow；AP Identity 当前只读诊断，不接管生产映射。
8. 大导入/解析/图表计算进 Job；报告和链路明细进 Export Process，UI 不做全量 SQL 或 Excel。

# 验证与失败报告

- 覆盖 ACTIVE/STANDBY、主链顺序、双射频、缺字段、短链、临界/普通回切、乒乓、RSSI/Busy、source_file 隔离和降采样不改统计。
- 验证大数据 UI 非阻塞、单 AP/全量图表、报告表头/关键值/列宽和取消清理。
- 无真实多版本日志时明确 fixture 覆盖范围，不声称兼容所有 H3C 版本。
- 输出修改文件、参数来源、数据库/历史导入影响、Identity shadow 影响和测试命令。

# 相关 Skills

- CLI parser：`network-command-parser-skill`。
- AP Identity：`netconsole-ap-identity-skill`。
- 报告：`netconsole-export-report-skill`。
- UI 缺陷：按 `docs/UI_DESIGN_SYSTEM.md` 和 Vue/Element Plus 组件测试处理，不恢复 Qt 页面。
