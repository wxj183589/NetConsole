# NetConsole v1.5.18 Console R2 分支回收与空间释放报告

日期：2026-11-24

## 1. 回收前置条件

本次回收在完整审计和遗漏功能整合完成后执行。产品基线为 `main@ba30a09bd2eb2ebe894a38adb1d3abcf3a2e1974`，对应产品提交 `整合 Console R2 分支遗漏功能`。

前置条件核验结果：

| 条件 | 结果 | 证据 |
| --- | --- | --- |
| 目标分支独有已提交 Commit | 无 | `git log main..codex-A/console-r2-independent-terminal-netmiko` 为空，`aa0a7c0a` 已为 main 祖先 |
| Dirty Worktree 有效产品改造 | 已处理 | 三项有效缺口已进入 `ba30a09b`；其余内容已分类为 main 已有、新实现替代、历史证据或无需迁移 |
| 未提交修改与未跟踪文件 | 已保全 | 64 个已跟踪修改、114 个未跟踪文件，共 178 个文件已归档并逐文件 SHA-256 校验 |
| Git Stash | 无 | 审计和回收时 `git stash list` 为空 |
| 其他任务依赖 | 未发现本地依赖 | 回收前仅目标 Worktree、集成 Worktree 和发布 Worktree 引用相关本地分支；远端功能分支保留 |
| 工程报告和测试证据 | 已保留 | 全量归档位于 Workspace 的 `branch-archives`，未删除历史报告、artifacts 或测试证据 |

审计和整合详情分别见：

- `docs/archive/engineering/CONSOLE_R2_BRANCH_FULL_AUDIT.md`
- `docs/archive/engineering/CONSOLE_R2_BRANCH_INTEGRATION_REPORT.md`

## 2. Dirty Worktree 归档

归档目录：

`D:\study\NetConsole-Workspace\branch-archives\console-r2-independent-terminal-netmiko-20261124`

归档结果：

| 项目 | 结果 |
| --- | ---: |
| 清单条目 | 178 |
| 已验证文件 | 178 |
| 缺失文件 | 0 |
| 哈希不一致 | 0 |
| 归档文件载荷 | 21,073,415 bytes |
| 归档目录总大小 | 21,678,434 bytes |
| `manifest.csv` SHA-256 | `edc1dc3bbdcd28b38b4e7bde5cf07d478af142db1fe77964ffa97ad53c552316` |
| `manifest.json` SHA-256 | `23c696734c23fc8d6325c749830688a6121ffb9293f0db87f698e4f283f705a4` |

归档同时保存了回收前的分支、Worktree、Status、最近历史、Tracked Diff Stat 和完整工作树 Patch。来源 Worktree 在归档校验完成后按明确路径恢复已跟踪文件，并逐个移除已归档未跟踪文件；未使用 `git reset --hard`、`git clean`、`git stash`、强制 Worktree 删除或强制分支删除。

## 3. Worktree 回收

正常移除：

| Worktree | 回收方式 | 结果 |
| --- | --- | --- |
| `D:\study\NetConsole-Workspace\worktrees\console-r2-full-integration-20261124` | `git worktree remove` | PASS |
| `D:\study\NetConsole-Workspace\worktrees\release-v1.5.18-20261123` | `git worktree remove` | PASS |

回收后 `git worktree list --porcelain` 仅保留：

- `D:\study\NetConsole-Workspace\NetConsole`
- 分支：`main`

没有删除其他项目或其他 Worktree，没有使用 `git worktree remove --force`。

## 4. 本地分支回收

正常删除：

| 本地分支 | 方式 | 结果 |
| --- | --- | --- |
| `codex-A/console-r2-independent-terminal-netmiko` | `git branch -d` | PASS |
| `codex-A/console-r2-full-integration-20261124` | `git branch -d` | PASS |

`codex-A/release-v1.5.18-20261123` 在回收时不存在本地分支，因此没有执行删除。回收后本地分支仅剩 `main`。

以下远端跟踪分支按保护要求保留，未删除远端引用：

- `github/codex-A/console-r2-independent-terminal-netmiko@aa0a7c0a`
- `github/codex-A/release-v1.5.18-20261123@f842d7ed`

没有使用 `git branch -D`，没有修改远端其他分支。

## 5. Git 存储回收

在 Worktree 和本地分支正常回收后执行常规 `git gc`。命令退出码为 0，Git 对象统计为：

| 指标 | 回收后 |
| --- | ---: |
| Loose objects | 0 |
| Prune-packable | 0 |
| Garbage | 0 |
| Garbage size | 0 bytes |
| Pack files | 2 |
| Pack size | 66.32 MiB |

`git fsck --connectivity-only --no-reflogs` 退出码为 0。命令仍列出部分 dangling 对象；这些对象不构成引用连通性错误，未使用 `git prune` 或 `git gc --prune=now` 强制删除。

常规 GC 在 Windows 上输出了路径访问警告。只读调查确认警告来自历史 `refs/codex/turn-diffs` 对象树中的超长 Base64 风格路径名，而不是当前 main、Worktree 或产品文件损坏。相关历史引用未删除、未重写；仓库状态、主线引用和连通性检查均正常。

## 6. 空间统计

| 项目 | 字节 | 约值 |
| --- | ---: | ---: |
| 已移除 Worktree 实际大小 | 3,559,857,081 | 3.32 GiB |
| Git GC 实际释放 | 295,276 | 0.28 MiB |
| 回收前测量总量 | 7,697,721,910 | 7.17 GiB |
| 回收后测量总量（含归档） | 4,140,252,123 | 3.86 GiB |
| 净释放空间 | 3,557,469,787 | 3.31 GiB |

归档目录占用 21,678,434 bytes，属于为防止遗漏有效工作而保留的必要证据，不计作可删除临时内容。没有删除正式制品、历史工程报告、artifacts、用户数据、DevStatus 或其他项目数据。

## 7. 最终 Git 状态

- 产品提交：`ba30a09bd2eb2ebe894a38adb1d3abcf3a2e1974`
- 产品版本：`1.5.18`
- 本地主线：`main`
- 本地 Worktree：仅 canonical 主仓 Worktree
- 本地分支：仅 `main`
- 远端功能分支：保留
- Force Push：未执行
- DevStatus：未修改
- Installer/Portable：未重新构建或验收

本清理报告提交后，最终 main HEAD 以包含本文件的报告 Commit 为准；推送前必须重新 `fetch github main` 并确认本地 main 可安全 Fast-forward 推送。

## 8. 数据安全边界

| 项目 | 结果 |
| --- | --- |
| `PRODUCTION_DATA_MODIFIED` | 0 |
| `DEV_REAL_DATA_MODIFIED` | 0 |
| `DATABASES_REMOVED` | 0 |
| `MAINTENANCE_AUTHORIZED` | NO |
| `DEVSTATUS_MODIFIED` | 0 |
| `REMOTE_FEATURE_BRANCH_DELETED` | 0 |

## 9. 状态

`BRANCH_AUDIT=PASS`

`DEVICE_MANAGEMENT=PASS`

`CONSOLE_INTEGRATION=PASS`

`SFTP_INTEGRATION=PASS`

`NETMIKO_INTEGRATION=PASS`

`MAIN_MERGE=PASS`

`REMOTE_SYNC=PASS`（产品提交已同步；本报告提交在最终推送后闭环）

`LOCAL_BRANCH_CLEANUP=PASS`

`WORKTREE_CLEANUP=PASS`

`DISK_SPACE_RECLAIM=PASS`
