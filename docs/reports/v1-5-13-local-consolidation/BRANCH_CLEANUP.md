# 分支回收记录

本轮先保留所有原始 tip 的 archive refs，避免 cherry-pick 后失去恢复点。

可安全删除的前提是原始 tip 已进入集成候选/最终 `main` 的祖先关系且无 dirty Worktree。由于本轮采用了经过 patch-equivalence 审计的 cherry-pick，候选另以 ancestry-only merge 记录了原始 tip；删除动作均使用非强制 `git branch -d`。

- `codex-A/global-dataroot-disk-policy`：保留。主仓库 Worktree 有 16 个未提交修改和活动 Vite 服务。
- Mesh performance/UI 分支：代码已由候选等价覆盖，已使用非强制 `git branch -d` 删除；原始 tip 由 archive refs 保全。
- `codex-A/r2-3-2-ground-unattended`：R2.3.3 原始历史包含其提交，已在 Worktree 回收后使用非强制 `git branch -d` 删除。
- `codex-A/r2-3-3-ground-unattended`：Ground 11 个非重复提交已移植，已使用非强制 `git branch -d` 删除。
- `codex-A/v1-5-13-full-portable`：v1.5.13 两个非重复提交已移植，已使用非强制 `git branch -d` 删除。

结果：本轮删除 5 条已完成本地分支；保留 1 条带 dirty Worktree 的 DataRoot 分支。archive refs 不删除，用于恢复和审计。

禁止使用 `git branch -D` 掩盖非祖先历史。
