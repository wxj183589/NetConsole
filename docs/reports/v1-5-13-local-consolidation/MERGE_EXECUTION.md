# 合并执行记录

1. 审计确认主仓库当前 Worktree 属于 `codex-A/global-dataroot-disk-policy`，存在未提交 DataRoot/共享层修改；未切换、未覆盖、未清理该 Worktree。
2. 复用原有且干净的 `v1-5-13-full-portable` Worktree，先切换到 detached `main` 起点，避免新建 Workspace 目录。
3. 按有效提交关系移植 Ground R2.3.3 的 11 个非重复提交，再移植 v1.5.13 的两个提交。
4. v1.5.13 移植产生 5 个内容冲突，逐文件手工解析后继续 cherry-pick；没有执行 `checkout --ours` 或 `checkout --theirs`。
5. 合并唯一 v1.5.13 changelog 段，重新生成 `src/netconsole/docs/changelog.md`。
6. 在候选上完成定向回归、Renderer/Electron 全量、构建、Ruff、compileall 和 canonical Full Gate。

当前候选功能提交 HEAD 为 `1581662989c5e27f05bcce6ad233a6cc34acbd46`；报告和最终 ancestry reconciliation 提交完成后，`main` 才更新到最终文档化结果。
