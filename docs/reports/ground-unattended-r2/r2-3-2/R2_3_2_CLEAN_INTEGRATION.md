# R2.3.2 干净集成候选

## 候选

- Worktree：`D:\study\NetConsole-Workspace\worktrees\r2-3-2-ground-unattended`
- Branch：`codex-A/r2-3-2-ground-unattended`
- 基线：`de7ca957d371cd8bc29b60d05f69f4c85d8b2190`
- 首次检查：`WORKSPACE_LAYOUT_CHECK=PASS`，Worktree 初始 clean。
- 候选提交：`a91a1916`（集成验证工具与 Worktree 路径修复）。

## 修复内容

Worktree 位于 `Workspace\worktrees\<name>` 时，Electron development runtime、dev runtime、package smoke、package 构建和 Electron 测试 setup 原先把 `worktrees\test-data` 当作数据根。候选修复统一识别 Workspace 根，使用 `Workspace\test-data\NetConsole`；package 构建同时支持共享主仓库 `.venv`。增加了对应 packaging 断言。

验证：Electron 定向测试 30 passed、typecheck/build passed；候选 `git status` 在提交前为 clean。分支仅在本地设置跟踪 `github/main` 以便解析安装器身份，未 push。

## 数据边界

所有运行根均为 Workspace 下单次隔离目录；没有复制 Site、生产数据库或开发真实数据。完整 Raw、SQLite 和长稳日志保留在外部测试证据目录，不进入 Git 报告目录。
