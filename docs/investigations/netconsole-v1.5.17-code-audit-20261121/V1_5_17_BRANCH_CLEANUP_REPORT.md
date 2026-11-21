# v1.5.17 本地分支回收报告

日期：2026-11-21

## 审计原则

仅按任务完成、无 dirty 修改、无有效独有提交、无活动 Worktree 且可由主线/PR 证据恢复的条件评估；不删除远端分支，不使用 `-D`，不回收其他项目引用。

## 结果

盘点时本地分支 `4` 个、产品 Worktree `6` 个；`github/main` 已合并列表只有 `main`，其余三个均为未合并显示。尝试 `git branch -d` 删除 v1.5.16 post-merge 与 original-maintenance 分支均因仍被活动 Worktree 使用而拒绝，未使用 `-D`。

本轮没有删除分支。当前 v1.5.17 分支包含本地未 Push 的有效提交，必须保留；`main`、其他未合并/dirty/活动 Worktree 分支和无法确认安全的历史分支均保留。PR squash 后的三个 v1.5.16 报告 blob 已与 `github/main` 逐项相同，但分支仍保留远端备份和活动 Worktree，避免未经单独授权回收。

临时短路径构建 worktree `D:\study\NetConsole-Workspace\w1517` 仅用于本次本地打包，待确认没有进程占用和需要保留的输出后再由 Git `worktree remove` 回收；它不是产品分支，也不涉及远端删除。
