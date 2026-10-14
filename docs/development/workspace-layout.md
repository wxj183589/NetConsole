# NetConsole Workspace 目录规范

本文件是 NetConsole Workspace 的唯一项目级目录权威规则。`AGENTS.md`、`D:\study\AGENTS.md` 和 `D:\study\DEVELOPMENT_STORAGE_POLICY.md` 只引用并执行本文件，不复制另一套完整规则。规则适用于开发、测试、分析、构建、发布以及 Codex Worktree。

## 1. 固定根目录和允许的顶层目录

Workspace 固定为：

```text
D:\study\NetConsole-Workspace
```

允许的顶层目录只有：

```text
NetConsole
NetConsole-DevStatus
worktrees
test-data
release
reports
temp
archives
```

已有历史例外允许保持原状，但不得作为新目录模板：

```text
.idea
diagnostic
field-validation-recovery-20260920-full
field-validation-recovery-20260920-full-fixed
```

例外是保留登记，不是新建许可。其他既有目录不自动删除；必须先核验用途、依赖、Git 状态和保留批准结果，再登记为明确例外。

未经用户明确批准，不得新增 Workspace 顶层目录，也不得创建 `NetConsole-copy`、`NetConsole-new`、`NetConsole-test`、`NetConsole-backup`、`package-worktrees`、`devstatus-worktrees`、`new-release`、`test-data-copy` 或同类副本目录。

## 2. Git Worktree

所有新 Codex Worktree 必须使用：

```text
D:\study\NetConsole-Workspace\worktrees\<task-id-or-branch-name>
```

创建前必须检查分支是否已有 Worktree、目标目录是否同名或等价、Git Common Directory 是否正确，并确认目标属于 `worktrees` 容器。已有对应 Worktree 优先复用。

任务合并后进入回收候选检查；未合并、dirty、有未跟踪成果、存在活动进程或用途不明的 Worktree 不得自动删除。Git Worktree 只能使用 `git worktree add/remove` 管理，不能用普通目录移动或删除替代。

## 3. 测试数据、构建和报告

| 用途 | 规范路径 |
| --- | --- |
| 共享样本和隔离测试运行数据 | `test-data\fixtures\`、`test-data\mesh\`、`test-data\device\`、`test-data\integration\` |
| 历史测试证据 | `test-data\historical\`，保持原状 |
| 正式发布制品 | `release\<version>\` |
| 临时构建输出 | `temp\build\<task-id>\` |
| 安装器验收临时目录 | `temp\installer-test\<task-id>\` |
| 临时分析 | `temp\analysis\<task-id>\` |
| 构建日志 | `reports\build\<task-id>\` |
| 诊断报告 | `reports\diagnostic\<task-id>\` |
| 测试报告 | `reports\tests\<task-id>\` |
| 维护报告 | `reports\maintenance\<task-id>\` |

已有 `temp\git-pack-quarantine\` 属于历史维护隔离容器，保持现状；新临时任务不得以此作为普通输出目录。

每个临时任务必须带任务 ID、归属、创建时间和用途，并在结束后检查可回收性。未确认安全的内容保留。不得复制完整真实数据根，不得用硬链接共享可写 SQLite，不得通过通配符清空 `temp` 或 `worktrees`。正式安装包、历史恢复资料和真实测试记录不因目录日期或名称自动删除。

## 4. 主仓库顶层

主仓库固定为 `NetConsole`。源码、测试、文档和脚本进入现有 `apps/`、`src/`、`tests/`、`docs/`、`scripts/` 等职责目录；仓库内部详细职责继续见 [`repository-layout.md`](./repository-layout.md)。未经用户明确确认，不得新增主仓库顶层目录，也不得创建 `new_app/`、`test_new/`、`backup_src/`、`temp_code/`、`old_version/` 或 `new_framework/` 等模糊目录。

## 5. 链接和正式数据边界

目录检查器不解析 Junction、Symlink 或其他 Reparse Point；遇到链接只报告并跳过。任何指向 Workspace 外部、正式运行环境或用途不明的链接都必须人工确认，禁止跟随。

`D:\NetConsoleData` 及其所有别名永远不属于 Workspace 治理范围。本规则、检查脚本和普通开发任务不得访问、扫描、统计、读取或修改该目录，也不得修改正式数据根配置。真实开发 Authority `D:\NetConsoleData-dev` 同样不是测试副本，不能整体复制到 Worktree、test-data、diagnostic 或 temp。

## 6. 自动检查

只读检查入口：

```powershell
python -m scripts.check_workspace_layout
```

脚本检查 Workspace 顶层目录、主仓库顶层目录、Git Worktree 位置、重复仓库入口、Git Common Directory 边界、标准容器边界上的 Reparse Point，以及常见非标准输出目录。违规返回非零状态，并显示路径、规则、期望位置和建议动作；脚本不删除、不移动、不修改权限，也不解析链接目标。

Local Quality Gate 的 FAST/FULL 路径和 `engineering-hardening` CI 会执行仓库内检查。CI checkout 没有本机 D 盘 Workspace 时只执行仓库范围检查；本机在标准路径运行时执行 Workspace + 仓库检查。该机制不能从操作系统层面阻止未接入的程序创建目录，也不引入后台常驻监控服务或 Windows ACL。

任何开发代理在创建目录、工作树、测试副本或构建输出之前，必须检查本文件。发现规则冲突时停止操作并请求确认，不得自行绕过。
