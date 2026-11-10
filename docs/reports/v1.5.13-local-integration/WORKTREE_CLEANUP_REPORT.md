# v1.5.13 worktree 清理报告

## 审计结果

初始 worktree 共 2 个正式/活动工作树：

1. `D:/study/NetConsole-Workspace/NetConsole`：`codex-A/global-dataroot-disk-policy`，16 个未提交 DataRoot 修改，保留。
2. `D:/study/NetConsole-Workspace/worktrees/r2-3-2-ground-unattended`：`codex-A/r2-3-2-ground-unattended`，14 个未跟踪 Ground 验收文件，保留。

本轮新增临时集成树：

3. `D:/study/NetConsole-Workspace/worktrees/v1.5.13-local-integration-01a1c156`：先承载集成分支，后切换到已合并的 `main`；无未提交 tracked 修改、无未归档业务数据、无本轮运行进程。

## 清理动作

- 临时 worktree 在交付报告提交完成后使用普通 `git worktree remove` 回收。
- 未使用 `--force`、未直接删除 `.git/worktrees`、未触碰其他两个工作树。
- 被测试失败留下的精确 pytest 临时根属于 `D:/study/NetConsole-Workspace/test-data/NetConsole/pytest-31c217b105c742b49a957eac4d50582a`，在确认没有 pytest 进程后退役；未清理其他历史 pytest 根。
- 临时 worktree 的被忽略依赖和 build 输出只为本轮生成，回收前按精确路径退役；不做仓库级 `git clean`。

## 保留条件

活动 DataRoot 和 Ground worktree 仍有用户/并行任务状态，不能回收。旧 MESH 分支无 worktree，但因提交身份差异和远端追踪保留，详见 `BRANCH_INVENTORY.md`。

