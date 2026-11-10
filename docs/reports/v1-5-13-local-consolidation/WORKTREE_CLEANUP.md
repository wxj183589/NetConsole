# Worktree 回收记录

回收前已执行：

- `git worktree list --porcelain`
- 每个 Worktree 的 `git status --short --branch`
- NetConsole 路径进程检查
- 未跟踪文件和报告/测试证据核对

结果：

| Worktree | 状态 | 处理 |
| --- | --- | --- |
| `NetConsole` | dirty，Vite 进程运行 | 保留，不切换、不回收 |
| `worktrees/r2-3-2-ground-unattended` | clean，无进程 | 已使用 `git worktree remove` 回收；无 `--force` |
| `worktrees/r2-3-3-ground-unattended` | clean，无进程 | 已使用 `git worktree remove` 回收；无 `--force` |
| `worktrees/v1-5-13-full-portable` | 集成候选，完成最终报告提交后无进程 | main 原子更新并复核后使用 `git worktree remove` 回收 |
| `worktrees/test-data` | 非 Git 管理目录，用途需单独核验 | 不删除、不作为本轮 Worktree 回收对象 |

未使用 `git worktree remove --force`，未普通删除目录，未删除测试数据根。

回收核验：两个 Ground Worktree 目录和 Git 管理记录已清除；候选 Worktree 在最终 main 更新后回收。主仓库 dirty 状态和活动 Vite 服务始终保留。
