---
name: netconsole-change-review-skill
description: "评审 NetConsole 当前 git diff、在编码前执行 Change Impact Audit、判断 L1-L4 风险、识别共享契约消费者、检查 UI/采集/数据库/命令/编码/导出/AP Identity 回归或评估重构安全性时使用。默认只读并按严重程度报告；用户明确要求直接实现、普通代码解释或格式化文件时不使用本 Skill。"
---

# 目标

作为 NetConsole L3/L4 共享变更的只读入口，对计划或实际 diff 执行证据驱动的 Change Impact/Consumer Audit，找出真实缺陷、兼容风险和验证缺口，不自动修复。

# 触发与反例

触发示例：

- “评审本次修改，看看还有什么遗漏。”
- “改 AP Identity/API Client/Task 前先做影响审计。”
- “检查这次数据库、Feature 或 Electron 重构会伤到哪些消费者。”

不应触发：

- “直接实现这个功能并修好。”
- “解释这段代码”或“只格式化文件”。

# 输入与输出

- 输入：目标需求、计划路径或当前 diff、基线、预期契约、已运行测试、worktree/并行修改和风险关注点。
- 输出：Risk Level、Shared Contracts、Consumers、Compatibility Risks、Required Regression、Parallel Changes、Merge Verification，以及按严重程度排序的 Findings。
- 允许修改生产代码：不允许。只有用户明确转为修复任务后，才调用对应领域 Skill 实施；审计结论本身不授权扩大范围。

# 开始前读取

- `git status --short`、`git diff --name-status`、`git diff --stat`、目标 diff 和基线提交。
- `git worktree list --porcelain`；对可访问 worktree 只读检查分支、状态和与本任务重叠的共享路径。
- `AGENTS.md`、`docs/DEVELOPMENT_RULES.md`、`docs/testing/BASELINE.md`、`docs/architecture/REFACTOR_MAP.md`。
- 存在时读取 `docs/development/CHANGE_IMPACT_FRAMEWORK.md` 和 `config/architecture/change_impact_matrix.json`；机器可读 Registry 优先于静态示例。
- 相关生产代码、调用方、写入方、缓存、DTO、测试、领域文档和目标专业 Skill。

# 风险等级

按行为和共享契约判级，不按行数判级；同一任务取最高等级。路径只提供最低风险提示，实际语义可以升级。

| 等级 | 定义 | 典型变更 | 最低验证 |
| --- | --- | --- | --- |
| L1 LOCAL | 单页面或局部实现，不改变公共契约 | CSS、文案、Tooltip、局部展示 | 当前组件/模块定向测试、lint/typecheck、diff check |
| L2 DOMAIN | 单一领域内部 Service/Repository/Parser/Router/报告 | 只被本领域消费的业务规则 | 领域 unit、API/contract、直接消费者 |
| L3 SHARED | 共享基础设施、公共 DTO/文件契约或多个领域消费者 | API client、NcDataTable、图表、Task/Job/Export、AP Identity | Consumer Audit、全部登记 consumer contracts、不得只测目标模块 |
| L4 PLATFORM | 平台、数据、安全、生命周期、构建发布 | Feature Registry、DataRoot、schema/migration、Electron Main/Preload/IPC、Installer/Packaging | 全局审计、platform contract、关键 main smoke、数据/包安全门和人工缺口 |

以下情况自动升级：公共 DTO/错误/状态/文件格式为至少 L3；schema、迁移、删除、DataRoot、运行时安全或安装器为 L4；共享文件中的“局部十行修改”仍按其契约判级。

# Change Impact Audit

开始审计时逐项回答，未知项必须标记为证据缺口：

1. 当前任务真正修改的领域和业务目标是什么？
2. 改动文件分别属于 L1/L2/L3/L4，最高等级是什么？
3. 是否触碰共享事实源、公共 DTO、状态、文件或生命周期契约？
4. 谁写数据，写入事务和 revision 是什么？
5. 谁读取数据，是否存在批量、分页或旧格式消费者？
6. 谁缓存数据，缓存键、generation 和失效条件是什么？
7. 谁展示数据，空值、错误、部分成功和 stale 如何表达？
8. 谁导出/下载数据，页面与 Artifact 是否冻结同一事实？
9. 谁依赖该状态、终态、身份或 Feature Gate？
10. 是否存在旧 schema、旧数据、旧 DTO、旧客户端或 frozen/package 兼容？
11. 是否有并行 worktree/分支修改相同文件或同一 shared contract？
12. 最终合并 commit 必须重跑哪些 consumer tests、smoke 和人工检查？

L3/L4 未列清消费者、兼容风险、测试矩阵、并行修改和合并后回归时，审计结论不得写成“可以安全修改”或“验证充分”。

# Consumer Matrix

先从机器可读 Registry 和当前调用图确认实际消费者；下表是必须核对的起点，不是替代代码审计的固定真相。

| 共享契约 | 至少核对的消费者 | 路由 Skill |
| --- | --- | --- |
| Renderer API client/runtime binding | 所有 Renderer API、Feature loading、Backend restart | `netconsole-electron-desktop-skill`（涉及 runtime 时）+ 受影响领域 Skill |
| NcDataTable/table preference | Devices、AC/FIT-AP、Trackside、MESH、Online MR、Ground、Tasks、Config/File/Network | 受影响领域 Skill；动态图另用 `dynamic-chart-stability` |
| Dynamic chart/timeline | MESH RSSI、Online MR、fping RTT/loss、iPerf、Channel Busy、接口速率 | `dynamic-chart-stability` + 对应领域 Skill |
| AP Identity/normalization/resolver | MESH、Ground、Online/Vehicle MR、Wireless、Trackside、FIT-AP、AC Mesh-Link、Report | `netconsole-ap-identity-skill` + 对应消费者 Skill |
| Task/Job/Worker | Devices、AC、Config、File、MESH、Online MR、Ground、Trackside、Network、Export | `netconsole-job-center-skill` + 对应领域 Skill |
| Export/Artifact/file contract | Devices、FIT-AP、Trackside、MESH、Online MR、Config、Network、Task Center | `netconsole-export-report-skill` + `netconsole-user-file-interaction-skill` |
| Feature Registry/snapshot | 全部导航、FeatureGate、Full/Customer、Settings、Electron production、Packaging | `netconsole-release-packaging-skill` + 受影响领域 Skill |
| DataRoot/SQLite/migration | Site、devices/tasks/agents DB、MESH/Online MR/Ground 派生数据、Installer | `netconsole-data-safety-skill`; 安装器再加 `netconsole-release-packaging-skill` |
| Electron Main/Preload/IPC/lifecycle | 所有受管窗口、Renderer runtime、Backend、Bridge、download/save、tray | `netconsole-electron-desktop-skill` |

领域路由：设备管理用 `netconsole-device-management-skill`；轨交基础资料用 `netconsole-rail-base-data-skill`；轨旁 AP 用 `netconsole-trackside-ap-skill`；地面无人值守用 `netconsole-ground-unattended-skill`；发布制品用 `netconsole-release-packaging-skill`。只有真实跨域时组合，不无条件加载全部 Skill。

# 共享高风险路径

至少将以下路径视为热点，并通过当前代码扩展到同一契约的关联文件：

- `apps/desktop_renderer/src/api/client.ts`
- `apps/desktop_renderer/src/components/table/`
- `apps/desktop_renderer/src/components/charts/`
- `src/netconsole/core/feature_registry.py`
- `src/netconsole/services/ap_identity/`、`src/netconsole/repositories/ap_identity_repository.py`
- `src/netconsole/services/job_center/`、`src/netconsole/background_worker.py`、`src/netconsole/export_worker.py`
- `src/netconsole/core/paths.py`、SQLite schema/migration/upgrade 路径
- `apps/desktop_electron/src/main/`、`apps/desktop_electron/src/preload/`、`apps/desktop_electron/src/shared/`
- 正式导入导出文件契约、Feature/edition/installer/build 配置

# 工作流程

1. 固定需求、比较基线和 diff；区分本任务修改、用户既有修改、merge 带入和生成产物。
2. 按最高风险判级，列出 changed contracts；不能以“只改一个模块”覆盖共享路径事实。
3. 追写入方 -> 存储/协议 -> 读取方 -> 缓存 -> 展示 -> 导出，核对每个消费者现有测试和兼容入口。
4. 检查 API/DTO、schema/revision、状态终态、缓存 generation、错误码、文件格式、IPC/安全和旧数据兼容。
5. 用 `git worktree list --porcelain` 与各 worktree 的只读 status/diff 查重叠；同文件或同契约并行修改要列出分支、路径和冲突风险。
6. 若业务分支合并 main 时出现不属于当前领域的共享文件冲突，标记 out-of-scope conflict；不得把顺手解决的冲突继续按原 L1/L2 验证。
7. 为每个 consumer 绑定当前存在的具体测试/脚本；不存在时写缺口，不编造命令，不用 one-off test 数量代替 contract coverage。
8. 对实际 diff 逐项报告 confirmed defect、inferred risk 和 verification gap；Findings 按严重程度并给出文件位置、触发条件、影响和建议方向。

# 合并后回归

- 分支旧测试结果只证明旧组合。L3/L4 合并 main、rebase、cherry-pick 或解决冲突后，必须在最终集成 commit 重新运行 Change Impact Guard 和 consumer matrix。
- L3 至少重跑全部登记 consumer contracts；L4 还要跑 platform/data/package gate、主线关键 smoke 和政策要求的完整基线。
- 本地统一执行入口是 `python -m scripts.quality.local_gate`：`--mode auto` 按风险选择 FAST/CONSUMER/FULL，`--mode consumer` 执行 Registry 套件，`--mode full` 执行最终平台基线。Gate 会强制 `RuntimeMode.TEST`、唯一 `D:/study/NetConsole-Workspace/test-data/NetConsole/<run-id>` 和 `.local-reports/` 报告。
- GitHub Actions 是可选远端复核，不替代本地 Gate；合并后必须在最终 commit 重新运行 `python -m scripts.quality.local_gate --mode full`。
- 自动化完成不替代真实 Electron GUI、安装包、现场局点、真实设备或长时间运行。未执行项标记 `NOT RUN/PENDING`，不得写成 PASS。

# 验证与失败报告

- 本 Skill 只运行只读静态检查和与评审有关的安全测试，不修改文件、不提交 Git。
- 工作树有用户修改时按当前状态评审，不回退、不覆盖；无法取得目标 diff、Registry、fixture 或环境时说明证据缺口。
- L3/L4 输出必须包含：影响消费者、兼容性风险、回归矩阵、并行修改、合并后重跑项、实际结果和人工缺口。
- 无 finding 时明确说明“未发现已确认缺陷”，同时保留测试、GUI、设备、frozen/package 和 merge 后残余风险。

# 输出格式

1. `Findings`：按严重程度，提供文件/位置、问题、触发条件、影响和建议方向。
2. `Change Impact`：Risk、Contracts、Consumers、Compatibility、Parallel Changes。
3. `Regression Matrix`：每项检查标记 PASS/FAIL/NOT RUN，并区分 branch 与 final integrated commit。
4. `Questions/Assumptions`、`Verification Gaps`、简短 `Summary`。

# 相关 Skills

- 本 Skill 负责只读影响审计；修复或实现由上表和领域路由中的专业 Skill 承担。
- 文档同步：`netconsole-project-docs-skill`。
