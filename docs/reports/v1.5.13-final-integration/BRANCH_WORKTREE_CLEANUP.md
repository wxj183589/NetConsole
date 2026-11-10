# Branch / Worktree Cleanup

## 本轮操作

- 删除本地已合并任务分支：1 条，`codex-A/global-dataroot-disk-policy`。
- 删除方式：`git branch -d`，无 `git branch -D`。
- 本轮回收 Worktree：0 个；任务开始时只有产品根 Worktree，不能把正在使用的主 Worktree 删除。
- 最终产品 Worktree：1 个，根目录分支为 `main`。
- 原脏分支提交：保留于 `refs/archive/netconsole-final-integration/20261111/global-dataroot-disk-policy`。

## 累计可审计结果

本轮开始前，已有 5 条已完成本地任务分支和 3 个集成 Worktree 在之前收口中完成安全回收。本轮再删除 1 条任务分支；因此当前产品本地分支仅保留 `main`，产品 Worktree 仅保留根工作树。

远程的 `github/codex-A/ground-unattended-v2-20261107`、`github/codex-A/mesh-analysis-scope-ui-optimization`、`github/codex-A/v1512-release-report` 等旧引用未删除。它们不是本地 Worktree，且当前没有足够证据确认远程所有权、PR 状态和其他协作者使用情况；保留远程引用是可逆且可审计的选择。

未触碰 `D:\study\fping`、`D:\NetConsoleData`、`D:\NetConsoleData-dev`，也未使用 `git clean`、`git reset --hard`、`git checkout --` 或 force push。
