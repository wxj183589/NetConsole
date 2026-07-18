---
name: netconsole-change-review-skill
description: "评审 NetConsole 当前 git diff、检查是否卡 UI、破坏采集/数据库/命令/编码/导出/AP Identity、查遗漏或评估重构安全性时使用。默认只读并按严重程度报告；用户明确要求直接实现、普通代码解释或格式化文件时不使用本 Skill。"
---

# 目标

对当前 diff 或指定改动执行证据驱动的项目级代码评审，优先找真实缺陷、回归风险和验证缺口，不自动修复。

# 触发与反例

触发示例：

- “评审本次修改，看看还有什么遗漏。”
- “检查是否会卡 UI 或破坏在线 MR 采集。”
- “评估这次 Job/数据库/AP Identity 重构是否安全。”

不应触发：

- “直接实现这个功能并修好。”
- “解释这段代码”或“只格式化文件”。

# 输入与输出

- 输入：当前 diff、指定提交/文件、预期行为、已运行测试和风险关注点。
- 输出：Findings、Questions/Assumptions、Verification Gaps、Summary；按严重程度排序并提供文件位置。
- 允许修改生产代码：不允许。只有用户明确转为修复任务后，才调用相应领域 Skill 实施。

# 开始前读取

- `git status --short`、`git diff --name-status`、`git diff --stat`、目标 diff。
- `AGENTS.md`、`docs/DEVELOPMENT_RULES.md`、`docs/REFACTOR_MAP.md`。
- 相关生产代码、测试、领域文档和目标 Skill。

# 评审重点

1. Electron Main/Renderer 事件循环阻塞、受管子进程生命周期、Vue 页面大表/导出重任务和 IPC 越权。
2. JSONL stdout 污染、取消/强制停止双终态、进程/临时文件残留和文件占用。
3. SQLite 跨线程、破坏性迁移、路径越界、自动清理误删和旧数据兼容。
4. 设备命令/顺序误改、raw log 丢失、编码回归和中文替换字符。
5. AP Identity 误接管、Peer/Radio/BSSID 混淆、shadow 异常影响生产终态。
6. Online MR Ping 1/Ping 2、iPerf 生命周期、启动确认、停止打包和受保护 raw 文件。
7. MESH 主备链、同 AP 双射频、短链/乒乓、降采样改统计和报告字段回归。
8. 1080p/1280 遮挡、滚动、i18n、Feature Registry、文档状态和缺失测试。

# 工作流程

1. 先读 diff，再追到调用方、数据边界、测试和文档；不只做模式扫描。
2. 每个 finding 写严重度、文件/位置、具体问题、触发条件、影响和建议方向。
3. 区分已确认缺陷、推断风险和未验证缺口；不把风格偏好当 bug。
4. 无 finding 时明确说明剩余测试/现场/GUI/frozen 风险。

# 验证与失败报告

- 只运行只读静态检查和与评审有关的安全测试；不修改文件、不提交 Git。
- 若工作树存在用户改动，按当前状态评审，不回退、不覆盖。
- 无法获取目标 diff、fixture 或环境时说明阻塞证据，不编造测试结论。

# 相关 Skills

- 根据改动领域组合对应 Skill；不要无条件加载全部 Skills。
- UI 专项审查：结合 Vue/Element Plus 组件测试、Electron Main/Preload 安全边界和 `docs/UI_DESIGN_SYSTEM.md`。
- 文档同步：`netconsole-project-docs-skill`。
