---
name: netconsole-ap-identity-skill
description: "AP Identity、CanonicalApIdentity、AP/Radio/BSSID/Peer MAC 归一化、resolver、matched/unresolved/ambiguous、confidence、shadow comparison、diagnostics 或生产接管评审时使用。普通 AP 表格展示、无身份关联的 parser 或名称格式调整不使用本 Skill。"
---

# 目标

维护 AP Identity canonical 模型、局点统一索引、批量 Query、消费者投影、解析证据、shadow 和脱敏诊断；保护已接管生产消费者，也不把尚未收口的路径误写成全面接管。

# 触发与反例

触发示例：

- “这个 Peer MAC 映射到了错误 AP，检查 Identity 证据。”
- “增加 AC/MESH Identity shadow 或只读 diagnostics。”
- “评审当前结果是否允许 AP Identity 接管生产匹配。”

不应触发：

- “只调整 AP 表格列宽。”
- “不涉及身份关联的日志字段解析或 AP 名称显示格式。”

# 输入与输出

- 输入：Candidate/Observation 来源、当前 consumer、批量 Query/revision、旧匹配结果、新 resolver 结果、作用域和接管/回滚目标。
- 输出：canonical/index/query/consumer projection/shadow/diagnostics 修改、证据和风险统计、回滚与验证结论。
- 允许修改生产代码：允许修复现有 Identity 基础设施和已接管消费者；新增消费者接管必须有明确范围、consumer audit、准入证据和回滚边界，不得顺手扩大到其他领域。

# 开始前读取

- `docs/AP_IDENTITY.md`、`docs/AP_IDENTITY_CONSUMER_AUDIT.md`、`docs/AP_MODEL_ASSESSMENT.md`、`docs/AP_IDENTITY_OBSERVATION_PLAN.md`。
- `docs/AP_IDENTITY_DISPLAY_ASSESSMENT.md`、`docs/AP_IDENTITY_JOB_DETAIL_HOST_ASSESSMENT.md`。
- `docs/TRACKSIDE_AP_IDENTITY_ASSESSMENT.md`、`docs/MR_MESH_AP_IDENTITY_ASSESSMENT.md`、`docs/EXPORT_FIELD_DEDUP_ASSESSMENT.md`。
- `src/netconsole/services/ap_identity/`、`src/netconsole/services/ac/ac_identity_models.py`、`src/netconsole/services/ac/ac_identity_adapter.py`。
- `src/netconsole/services/ac/ac_optical_identity_adapter.py`、`src/netconsole/services/mr_mesh_identity_shadow.py`。
- `src/netconsole/services/rail_transit/trackside_ap_identity_shadow.py`、`src/netconsole/services/export_identity_diagnostics.py`、`src/netconsole/models/diagnostics_summary.py`。
- 相关 `tests/test_*identity*.py`。

# 工作流程与边界

1. 区分 AP UUID、AC 原生 AP ID、AP MAC、Radio MAC、BSSID/BBSSID、Peer MAC/Peer Radio、名称和位置证据。
2. Resolver 明确返回 matched、unresolved 或 ambiguous；多候选不得静默选第一条，fallback 不伪装精确匹配。
3. 名称相同不等于高置信匹配；MAC-like 名称单独处理，缺失 AC/site 作用域时保守降级。
4. 已接管消费者必须固定同批 `revision/index_status`，保留 matched/unresolved/ambiguous/invalid；GET 或显示刷新不得重建索引，identity-only remap 不改 raw 事实。
5. shadow/diagnostics 失败返回 unavailable/warning，不改变原任务终态、页面结果、报告字段或写库路径。
6. 诊断样本脱敏，不保存完整 raw、凭据、私有地址或可反推现场身份的数据。
7. 新生产接管必须比较旧/新结果、满足当前 consumer audit、明确单模块回滚边界，并保留对照结果。

# 当前真实状态

- 局点级 `devices.db` 统一索引、批量 Query、revision 和诊断基础设施已进入生产。
- MESH、Ground、Online/Vehicle MR、Wireless 和轨旁 AP 业务/导出的高频 Peer/BSSID/物理 AP 解析已经按消费者使用统一入口；这些路径不能再按“仅 shadow”维护。
- AC Mesh-Link、轨旁基础资料搜索、其他报告读取以及设备/LLDP topology binding 仍处于 P1/P2 收敛范围；FIT-AP/AC 搜索虽使用统一查询，领域业务仍由 AC 负责。
- 统一任务窗口只展示受控摘要；部分消费者接管不等于全系统接管，GET 不得修复 stale projection 或触发 rebuild。

# 验证与失败报告

- 覆盖精确、无解、多候选、跨 AC 重复、name-only、MAC-like、Radio/BSSID/Peer 语义、shadow 异常不阻塞和删除附加字段可回滚。
- 接管评审必须给出真实观测范围、风险分级、阻断项、回滚和未验证模块；证据不足时结论为不接管。
- 输出修改文件、生产结果是否变化、数据库影响、脱敏方式、回滚路径和测试。

# 相关 Skills

- MESH 身份：`netconsole-mesh-analysis-skill`。
- 数据安全：`netconsole-data-safety-skill`。
- 项目评审：`netconsole-change-review-skill`。
- 轨旁、Ground 和基础资料消费者：`netconsole-trackside-ap-skill`、`netconsole-ground-unattended-skill`、`netconsole-rail-base-data-skill`。
