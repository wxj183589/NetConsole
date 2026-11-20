# NetConsole v1.5.16 L3 主线集成前基线

日期：2026-11-21

状态：`PASS`

## Git 基线

| 项目 | 当前证据 |
| --- | --- |
| 产品仓库远端 | `github = git@github.com:wxj183589/NetConsole.git` |
| 最新 `github/main` | `6671f86ecd8bb9a2d3f12d5b0ccfe6b309cb4998` |
| 产品维护分支 | `codex/netconsole-original-maintenance-20261120` |
| 产品维护 HEAD | `eb161ab1027476242741ad8a8234778f5fdcf290` |
| 产品远端 HEAD | `eb161ab1027476242741ad8a8234778f5fdcf290` |
| Merge base | `6671f86ecd8bb9a2d3f12d5b0ccfe6b309cb4998` |
| `main...maintenance` | main 独有 0，维护分支独有 2 |
| 维护提交 | `c5b9bf1ff4286b60f8a6e78a5dab64dc6374942d`、`eb161ab1027476242741ad8a8234778f5fdcf290` |
| DevStatus 分支 | `codex-A/netconsole-v1516-maintenance-status-20261120` |
| DevStatus HEAD / 远端 | `5eaff9bbbebf3c96bbdf7de5516942b423994aa8` |

`github/main` 是维护分支 HEAD 的直接祖先。重新 fetch 后远端 main 仍为历史基线，未出现主线漂移；因此没有需要合入维护分支的新提交，也不创建无意义的 merge commit。`git merge-tree` 未发现冲突，产品差异为 55 个文件、1004 行新增、441 行删除。

## Worktree 与并行状态

| Worktree | 状态 | 处理 |
| --- | --- | --- |
| `NetConsole` / `main` | 存在 9 份既有未跟踪 `docs/investigations/sql-architecture-review-20261118/` 文档 | 保留，不在该工作树执行合并、切分支、清理或提交 |
| `netconsole-original-maintenance-20261120` | clean，HEAD 与产品远端一致 | 本轮产品与 PR 操作使用此隔离工作树 |
| `syslog-phase5-main-20261119` | detached HEAD，clean | 不修改、不回收 |
| DevStatus 维护工作树 | clean，HEAD 与 DevStatus 远端一致 | 仅在产品合并与 post-merge 验收后单独更新 |

当前未发现运行中的 NetConsole Backend、Electron、Renderer 或测试进程。主工作树的未跟踪文档与维护分支 55 个文件无路径重叠，但其所有权未由本任务取得，因此不得移动、删除或纳入提交。

## 影响与消费者

最高风险按任务约定为 `L3 / task-center`。共享契约包括 Ground API DTO、Heartbeat 持久配置与 Supervisor、Syslog VERIFY/JOIN/EXIT 安全状态、Task 关闭快照、Storage Audit 状态、Ground Renderer API/类型、MR 动态图与路由导航。

必须覆盖的消费者：

- Ground Profile、Repository、Application Service、Heartbeat/Syslog Supervisor 与 FastAPI DTO；
- Heartbeat、Settings、MR Monitoring、AC Mesh-Link 与 Storage Audit Renderer；
- Task Center 关闭阶段和缺表恢复；
- Electron 生命周期与版本身份；
- Renderer 动态图 series/viewport/resize/dispose；
- Architecture、Main Contract、Change Impact、Consumer 与 Full Gate。

兼容边界：旧 Profile 显式值继续读取；新增 Heartbeat exclusions 默认只排除明确取消的列车；检查模式必须保持只读；JOIN/EXIT 只接受后端精确白名单；Storage Audit 必须区分未生成和真实零容量；旧路由只做安全重定向。真实设备、真实 Win10、人工 GUI 和 8 小时长稳不是自动化消费者门禁可替代的证据。

## GitHub PR 门禁现状

- 当前分支尚无 PR。
- GitHub `main` 的 branch protection API 返回 `404 Branch not protected`。
- 当前仓库规则说明 GitHub Actions 已退役，最终权威证据为合并后本地 `python -m scripts.quality.local_gate --mode full`。
- 本轮仍通过正常 PR 创建、评审和 GitHub 合并，不直接 push main；不存在的 Required Checks 不得报告为 PASS，也不使用管理员绕过。

## Layout 与格式基线

首次从维护 worktree 调用 `./.venv/Scripts/python.exe` 因该 worktree 没有独立 `.venv` 而失败；未修改文件。随后使用主仓库现有共享虚拟环境执行同一仓库模块：

```text
WORKSPACE_SCOPE=REPOSITORY_ONLY
WORKSPACE_LAYOUT_CHECK=PASS
REPARSE_POINTS=NOT_FOLLOWED
DESTRUCTIVE_ACTIONS=NONE
```

`git diff --check github/main...HEAD` 和 Root Layout Gate 通过。最初按猜测调用的
`tests/test_docs_structure.py`、`tests/test_docs_paths.py` 不存在，结果为 `NOT RUN`；读取
`scripts/quality/local_gate.py` 后按 canonical docs/path guard 入口执行
`tests/test_project_docs_layout.py tests/quality/test_directory_readmes.py`，结果为 `22 passed`
（1.18 秒）。后续任何产品提交都必须保持工作树 clean、普通 push 且远端 SHA 一致。

## 数据与原始证据基线

```text
PRODUCTION_DATA_MODIFIED=0
DEV_REAL_DATA_MODIFIED=0
DATABASES_REMOVED=0
USER_FILES_MODIFIED=0
REAL_DEVICES_ACCESSED=0
DEVICE_CONFIG_WRITES=0
ORIGINAL_RAR_HASH_PRESERVED=1
EXTRACTION_DIRECTORY_PRESERVED=1
```

原始 RAR SHA-256：`B785746E5C9299C5795DD375C5118308F854AAEA8275F492CF070DA5C347A383`。

只读提取目录保持为 `D:\study\NetConsole-Workspace\temp\analysis\netconsole-v1.5.16-maintenance-20261120`，此前记录为 1103 个文件、416760785 bytes。本轮不再次清理、迁移、覆盖或删除该目录。

## 集成判断

`PRE_INTEGRATION_BASELINE=PASS`。当前维护分支可直接提交本基线证据并普通 push，随后创建以 `main` 为目标的正常 PR。合并前仍需重新 fetch 并确认 `github/main` 未前进；若主线前进，则先在隔离维护工作树以普通 merge 集成并重新执行冲突与消费者审计。
