# v1.5.13 本地分支清单

日期：2026-11-11

本清单基于本地 `git branch -avv`、`git worktree list --porcelain`、`git cherry` 和工作区状态生成。所有原始分支 tip 已保存在 `refs/archive/netconsole-local-consolidation/20261110/`。

| 分支 | 原始 HEAD | 状态 | 处理 |
| --- | --- | --- | --- |
| `main` | `293377a1` | 未被 Worktree 占用，作为整合起点 | 报告最终提交后原子更新到本轮整合结果 |
| `codex-A/global-dataroot-disk-policy` | `d244ebcc` | 主仓库 Worktree 有 16 个未提交文件，且有 Vite 进程 | 保留；只复用其已提交且等价的历史，不触碰 dirty 修改 |
| `codex-A/mesh-analysis-performance-optimization` | `4d2fb5d3` | 已删除；archive ref 保留 | 其提交由候选等价补丁包含，未重复合并 |
| `codex-A/mesh-analysis-scope-ui-optimization` | `9cd098ed` | 已删除；archive ref 保留 | 其提交由候选等价补丁包含，未重复合并 |
| `codex-A/r2-3-2-ground-unattended` | `d3588c5d` | 已删除；Worktree 已回收 | R2.3.3 历史包含其提交，已完成非强制删除 |
| `codex-A/r2-3-3-ground-unattended` | `18043b99` | 已删除；Worktree 已回收 | 11 个非重复提交已移植，已完成非强制删除 |
| `codex-A/v1-5-13-full-portable` | `201b0bc0` | 已删除；Worktree 待最终 main 更新后回收 | v1.5.13 两个非重复提交已移植，候选仍在此 Worktree |

未扫描或治理独立的 `D:\study\fping`、真实数据根及用户目录数据。
