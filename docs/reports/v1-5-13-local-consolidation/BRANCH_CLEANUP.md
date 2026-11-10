# 分支回收记录

本轮先保留所有原始 tip 的 archive refs，避免 cherry-pick 后失去恢复点。

可安全删除的前提是原始 tip 已进入 `main` 的祖先关系且无 dirty Worktree。由于本轮采用了经过 patch-equivalence 审计的 cherry-pick，原始提交 ID 不天然成为 `main` 祖先；在不使用强制删除的前提下，原始分支删除结果按最终 `git branch -d` 结果记录。

- `codex-A/global-dataroot-disk-policy`：保留。主仓库 Worktree 有 16 个未提交修改和活动 Vite 服务。
- Mesh performance/UI 分支：代码已由 `main` 等价覆盖，但原始 tip 非祖先；不使用强制删除，保留分支和 archive refs。
- `codex-A/r2-3-2-ground-unattended`：R2.3.3 原始历史包含其提交；若 `git branch -d` 在最终 ancestry reconciliation 后通过则删除，否则保留并记录阻断。
- `codex-A/r2-3-3-ground-unattended`：Ground 11 个非重复提交已移植；按 `git branch -d` 结果处理。
- `codex-A/v1-5-13-full-portable`：v1.5.13 两个非重复提交已移植；按 `git branch -d` 结果处理。

禁止使用 `git branch -D` 掩盖非祖先历史。
