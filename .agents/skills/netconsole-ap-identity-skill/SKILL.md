---
name: netconsole-ap-identity-skill
description: "AP Identity、CanonicalApIdentity、AP/Radio/BSSID/Peer MAC 归一化、resolver、matched/unresolved/ambiguous、confidence、shadow comparison、diagnostics 或生产接管评审时使用。普通 AP 表格展示、无身份关联的 parser 或名称格式调整不使用本 Skill。"
---

# 目标

维护 AP Identity canonical 模型、适配器、解析证据、shadow 比较和脱敏诊断；默认保护旧生产匹配，不把只读结果误写成已接管。

# 触发与反例

触发示例：

- “这个 Peer MAC 映射到了错误 AP，检查 Identity 证据。”
- “增加 AC/MESH Identity shadow 或只读 diagnostics。”
- “评审当前结果是否允许 AP Identity 接管生产匹配。”

不应触发：

- “只调整 AP 表格列宽。”
- “不涉及身份关联的日志字段解析或 AP 名称显示格式。”

# 输入与输出

- 输入：Candidate/Observation 来源、旧匹配结果、新 resolver 结果、作用域和接管/回滚目标。
- 输出：canonical/adapter/shadow/diagnostics 修改、证据和风险统计、回滚与验证结论。
- 允许修改生产代码：允许新增/修复只读 Identity 工具和 shadow；未经明确接管任务、准入证据和回滚方案，不允许替换生产匹配或写库。

# 开始前读取

- `docs/AP_IDENTITY.md`、`docs/AP_MODEL_ASSESSMENT.md`、`docs/AP_IDENTITY_OBSERVATION_PLAN.md`。
- `docs/AP_IDENTITY_DISPLAY_ASSESSMENT.md`、`docs/AP_IDENTITY_JOB_DETAIL_HOST_ASSESSMENT.md`。
- `docs/TRACKSIDE_AP_IDENTITY_ASSESSMENT.md`、`docs/MR_MESH_AP_IDENTITY_ASSESSMENT.md`、`docs/EXPORT_FIELD_DEDUP_ASSESSMENT.md`。
- `src/netconsole/services/ap_identity/`、`src/netconsole/services/ac/ac_identity_models.py`、`src/netconsole/services/ac/ac_identity_adapter.py`。
- `src/netconsole/services/ac/ac_optical_identity_adapter.py`、`src/netconsole/services/mr_mesh_identity_shadow.py`。
- `src/netconsole/services/rail_transit/trackside_ap_identity_shadow.py`、`src/netconsole/services/export_identity_diagnostics.py`、`src/netconsole/ui/diagnostics/`。
- 相关 `tests/test_*identity*.py`。

# 工作流程与边界

1. 区分 AP UUID、AC 原生 AP ID、AP MAC、Radio MAC、BSSID/BBSSID、Peer MAC/Peer Radio、名称和位置证据。
2. Resolver 明确返回 matched、unresolved 或 ambiguous；多候选不得静默选第一条，fallback 不伪装精确匹配。
3. 名称相同不等于高置信匹配；MAC-like 名称单独处理，缺失 AC/site 作用域时保守降级。
4. shadow/diagnostics 失败返回 unavailable/warning，不改变原任务终态、页面结果、报告字段或写库路径。
5. 诊断样本脱敏，不保存完整 raw、凭据、私有地址或可反推现场身份的数据。
6. 任何生产接管必须比较旧/新结果、满足当前准入文档、明确 feature flag/回滚适配器，并保留对照结果。

# 当前真实状态

- 当前 AP Identity 主要处于 canonical 工具、各领域 shadow comparison 和只读 diagnostics 阶段。
- FIT-AP 扩展、光衰、轨旁、MR/MESH 和导出仍以旧业务结果为生产路径；shadow 不授权覆盖。
- 当前没有统一 Job 详情宿主和安全结果保留层可承载完整 Identity 可见 UI；不得描述为已全面接管。

# 验证与失败报告

- 覆盖精确、无解、多候选、跨 AC 重复、name-only、MAC-like、Radio/BSSID/Peer 语义、shadow 异常不阻塞和删除附加字段可回滚。
- 接管评审必须给出真实观测范围、风险分级、阻断项、回滚和未验证模块；证据不足时结论为不接管。
- 输出修改文件、生产结果是否变化、数据库影响、脱敏方式、回滚路径和测试。

# 相关 Skills

- MESH 身份：`netconsole-mesh-analysis-skill`。
- 数据安全：`netconsole-data-safety-skill`。
- 项目评审：`netconsole-change-review-skill`。
