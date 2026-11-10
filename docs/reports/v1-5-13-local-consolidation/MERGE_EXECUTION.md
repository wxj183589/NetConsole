# 合并执行记录

1. 审计确认主仓库当前 Worktree 属于 `codex-A/global-dataroot-disk-policy`，存在未提交 DataRoot/共享层修改；未切换、未覆盖、未清理该 Worktree。
2. 复用原有且干净的 `v1-5-13-full-portable` Worktree，先切换到 detached `main` 起点，避免新建 Workspace 目录。
3. 按有效提交关系移植 Ground R2.3.3 的 11 个非重复提交，再移植 v1.5.13 的两个提交。
4. v1.5.13 移植产生 5 个内容冲突，逐文件手工解析后继续 cherry-pick；没有执行 `checkout --ours` 或 `checkout --theirs`。
5. 合并唯一 v1.5.13 changelog 段，重新生成 `src/netconsole/docs/changelog.md`。
6. 在候选上完成定向回归、Renderer/Electron 全量、构建、Ruff、compileall 和 canonical Full Gate。

7. 在功能提交和报告提交后，使用 `git merge --no-ff -s ours` 将 `codex-A/r2-3-3-ground-unattended` 和 `codex-A/v1-5-13-full-portable` 的原始 tip 记录为候选的祖先关系；这两次 ancestry-only merge 不改变工作树文件，也不覆盖候选内容。
8. 已安全回收两个 Ground Worktree，并在无 dirty Worktree、且原始 tip 已成为候选祖先后，以非强制 `git branch -d` 删除两个 Ground 分支和 v1.5.13 分支；Mesh 两条分支也已安全删除。所有原始 tip 仍由 archive refs 保全。

功能提交后的 ancestry reconciliation：

- `597bc100`：记录 `codex-A/r2-3-3-ground-unattended` 等价移植历史。
- `e83b87e9`：记录 `codex-A/v1-5-13-full-portable` 等价移植历史。

集成候选 HEAD 为 `e83b87e98bd747865ac88ab8e347fe633358ddb1`；报告提交 `ac8697cd` 已在确认 `main` 仍为原始起点后，通过带旧值校验的 `git update-ref` 原子更新本地 `main`，随后候选 Worktree 已安全回收。
