---
name: netconsole-project-docs-skill
description: "NetConsole README、docs、架构说明、REFACTOR_MAP、Job/Export、AP Identity、Online MR、MESH、SNMP、数据目录、UI 规范或 Codex Skills 文档同步任务时使用。只实现代码且无文档影响、纯错别字或用户报告生成不使用本 Skill。"
---

# 目标

根据当前代码、测试和 diff 同步项目文档，清楚区分已完成、兼容层、shadow、部分迁移、未迁移和规划，不把历史方案写成现实。

# 触发与反例

触发示例：

- “同步本次 Job Center 架构改造文档。”
- “更新 README、docs 索引和 REFACTOR_MAP。”
- “整理项目级 Codex Skills 的路由说明。”

不应触发：

- “只实现一个没有文档影响的内部函数。”
- “生成一次性用户报告或只改一个错别字。”

# 输入与输出

- 输入：当前 diff、生产代码、测试结果、目标文档和已确认的状态边界。
- 输出：最小 Markdown 修改、链接/事实验证和未同步风险。
- 允许修改生产代码：不允许；文档任务默认只改 Markdown/Skill。发现代码问题时报告，不为迁就文档改业务代码。

# 开始前读取

- `README.md`、`AGENTS.md`、`docs/README.md`、目标专题文档。
- `src/netconsole/core/version.py`、`src/netconsole/core/feature_registry.py`、`src/netconsole/core/paths.py`。
- 与任务相关的 `src/netconsole/services/job_center/`、`src/netconsole/services/export/` 和测试。

# 工作流程

1. 按“生产代码 > 测试/断言 > 当前 diff > 当前专题文档 > Git 近期提交 > 历史规划”确认事实。
2. 检查 README、docs 索引、架构、开发规则、REFACTOR_MAP 和受影响领域专题。
3. 明确标注已完成、保留兼容层、shadow/diagnostics、部分迁移、尚未迁移、规划中或禁止接管。
4. 读取 `src/netconsole/core/version.py`、Feature Registry 和 PathResolver，不手写可能漂移的版本、入口或路径。
5. 使用仓库相对链接，不创建大小写不同的重复文档，不复制整份源码或整套 docs 到 Skill。

# 项目约束

- 不编造命令、路径、测试结果或功能状态；不写开发机绝对路径、真实账号、密码、community、IP 或 MAC。
- Windows Go Agent V1 已位于 `apps/agent/`，包含 HTTP API、内嵌 Web、iPerf/fping、MR sidecar、目标管理、任务事件和采集包；不能再写成“无 Go Agent 实现”。CentOS 离线部署、主动注册、多 Controller 和完整 Traffic Web 页面仍未实现。
- AP Identity 不得写成已全面接管；`legacy_tasks.py` 存在时不得写成全部任务已迁移。
- 产品 changelog 只记录实际用户功能变化；纯 Codex Skill 工作不伪装成产品功能。

# 验证与失败报告

- 检查 Markdown 相对链接、文件名、索引覆盖、版本/路径来源和 diff whitespace。
- 未运行测试时只引用已有可核实结果，不写“测试通过”。
- 源码与文档冲突时报告差异并以代码/测试为准；无法确定时标注待确认。
- 输出修改文档、事实来源、链接检查和仍可能过期的内容。

# 相关 Skills

- 项目级评审：`netconsole-change-review-skill`。
- Skill 创建/升级：`skill-creator`。
