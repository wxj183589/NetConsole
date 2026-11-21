# R5.0.4 本地空闲分支清理审计

## 审计命令

```text
git branch -avv
git branch --merged main
git worktree list
git status --short --branch
```

审计基于产品提交 `a11a8ebf`，当前分支为 `codex/netconsole-r5.0.4-mr-timeline-ux-20261122`。

## 决定

本轮没有满足全部安全条件的可回收分支，因此没有执行 `git branch -d`。所有分支均保留；没有使用 `-D`、`worktree remove --force`、reset 或 clean，也没有删除远端分支。

| 分支 | 最后提交 | Worktree | 合并状态 | 操作 |
| --- | --- | --- | --- | --- |
| `main` | `d58fdcf6` | 主仓库另有当前工作树 | 基线 | 保留 |
| `codex/netconsole-r5.0.4-mr-timeline-ux-20261122` | `a11a8ebf` | 当前工作树 | 未合并 | 保留 |
| `codex/netconsole-r5.0.3-syslog-gui-acceptance` | `ff222884` | 未使用 | 未合并到 `main`，仍是 R5.0.4 提交祖先 | 保留 |
| `codex-A/netconsole-v1516-post-merge-20261121` | `36a29cdb` | 正在使用 | 已合并到 `main` | 保留，Worktree 活跃 |
| `codex/netconsole-original-maintenance-20261120` | `6d8a7918` | 正在使用 | 未作为清理目标 | 保留，Worktree 活跃 |
| `codex/netconsole-r5.0-collection-playback-20261121` | `c4e4b285` | 正在使用 | 已合并列表中但 Worktree 活跃 | 保留，Worktree 活跃 |
| `codex/netconsole-r5.0.1-dev-runtime-gui-20261121` | `ea751b23` | 正在使用 | 已合并列表中但 Worktree 活跃 | 保留，Worktree 活跃 |
| `codex/netconsole-v1.5.17-maintenance-20261121` | `6dc938c7` | 正在使用 | 已合并列表中但 Worktree 仍 ahead `github/main` | 保留，Worktree 活跃 |
| detached `syslog-phase5-main-20261119` | `6671f86e` | 正在使用 | detached 历史验证树 | 保留 |

## 保护项

当前产品工作树原有未跟踪截图和 `docs/investigations/sql-architecture-review-20261118/` 均未纳入本次清理，保持不变。`LOCAL_BRANCHES_RECOVERED=0`、`UNMERGED_BRANCHES_PRESERVED=PASS`、`ACTIVE_WORKTREES_PRESERVED=PASS`、`MAIN_PRESERVED=PASS`、`CURRENT_BRANCH_PRESERVED=PASS`。
