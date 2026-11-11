# NetConsole v1.5.13 工作区最终收口报告

日期：2026-11-11（Asia/Shanghai）
Agent：codex-A
Codex-Thread：`01a1c697-18fa-7f63-89fb-337c76c7c29d`

## 范围与保护边界

本轮只治理 `D:\study\NetConsole-Workspace` 及产品仓库的 Git 元数据、可重建输出和已结束的 NetConsole 开发服务。未访问、复制、移动、修改或删除以下对象：

- `D:\NetConsoleData`
- `D:\NetConsoleData-dev`
- `D:\study\fping`
- NetConsole-Next、BiaoGan、SmartHub 和其他项目
- 现场设备、用户业务数据和未确认归属的数据库/日志

本轮不修改产品业务代码、不重新打包、不重复 5000+ Python 测试或长稳测试。

## 清理前后容量

容量统计是逻辑文件字节，不等同 NTFS 物理簇；递归盘点跳过 Reparse Point 目标。清理前值由清理后同口径值加逐项删除清单回推，D 盘可用空间另行实测。

| 指标 | 数值 |
|---|---:|
| Workspace 清理前 | 40,666,831,762 bytes（37.873938 GiB） |
| Workspace 清理后 | 38,504,576,004 bytes（35.860181 GiB） |
| 逻辑删除字节 | 2,162,255,758 bytes（2.013758 GiB） |
| D 盘可用空间实测增量 | 2,170,011,648 bytes（2.020981 GiB） |
| Reparse Point 盘点数 | 12,627 |

逐项回收：

| 对象 | 字节 | 处理依据 |
|---|---:|---|
| `D:\study\NetConsole-Workspace\.ruff_cache` | 270 | 仅含可重建 Ruff 缓存 |
| `NetConsole\dist` | 1,274,972,787 | 仓库规则定义的可重建构建输出；正式制品不在此目录 |
| `NetConsole\apps\desktop_electron\dist` | 152,666,083 | Electron 可重建中间输出 |
| `release\v1.5.13\build-20261111-0735-afd1b4fc\NetConsole-1.5.13-portable` | 518,904,222 | 最终 ZIP 的解压/Smoke 副本，含约 1.9 MiB 运行时生成数据，可由保留 ZIP 重建；未被报告引用 |
| `temp\build\v1.5.13-release-integration-prebuild\NetConsole-1.5.13-portable.previous.zip` | 215,712,396 | 旧 Portable 的重复临时副本；同一旧候选仍保留于 `release\v1.5.13\build-20261111-012953-5294f1ea` |
| 空 `temp\git-pack-quarantine` | 0 | 空隔离壳 |
| 空 `worktrees\test-data` 及其空子目录 | 0 | 不是 Git Worktree，无文件、无 Reparse Point |

未使用 `git clean`、`git reset`、`git checkout --`、`git stash`、强制删除或 Git GC/prune。

## Git Worktree 与分支

- 产品仓库清理前本地分支：3；清理后：1（仅 `main`）。
- 删除：`codex-A/v1.5.13-release-integration`（原 HEAD `6bde7526ebab19c9cc91d75e4be722e72e615366`）、`codex-A/v1.5.13-release-report`（原 HEAD `d0490a269014d90071fce22520ee02d8eef0ad57`）。两者均已通过 GitHub PR 实际合并、tip 可达 `main`，使用普通 `git branch -d` 删除。
- GitHub 远端上述两个分支未删除，作为恢复来源保留。
- 产品 Git Worktree：清理前 1、清理后 1；没有待回收的 Git Worktree。非 Git 的空 `worktrees\test-data` 壳已精确移除。
- 当前产品仓库目标：`main`；本轮报告通过短期分支和受保护 PR 提交。

PR 依据：PR #107 已合并到 `afd1b4fc35f2ac2e2ae8d3a52e783ea7b0ac630c`；PR #108 已合并到 `f78db74cda562bdc0d3bf3e74d669a6b33a11725`。

## 进程释放

确认并停止 1 个已结束 NetConsole 渲染服务：

- PID `32812`，`node.exe`，`node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5174 --strictPort`，启动于 2026-11-08 16:43:08。
- 通过启动命令、5174 监听端口和 NetConsole 历史任务时间确认归属；使用正常 `Stop-Process` 结束。
- 停止后 PID 和 5174 监听均不存在。
- 未发现需要停止的 Python、Backend、Electron、fping、PyInstaller 或测试运行器进程。

## 正式制品保留与验证

保留目录：`D:\study\NetConsole-Workspace\release\v1.5.13\build-20261111-0735-afd1b4fc`

| 制品 | 大小 | SHA-256 | 验证 |
|---|---:|---|---|
| `NetConsole-Full-1.5.13.0-afd1b4fc-x64-setup.exe` | 158,267,994 | `cdd345c38220f596b00f564ac1016fae172c21350263df76d651d196bc02af66` | 文件存在，哈希匹配 release manifest |
| `NetConsole-1.5.13-portable.zip` | 215,714,508 | `aa554084a61038b3cd0ef11fe94ec5dc0614b54bd11ee2415a52d13e2427d57a` | 文件存在，7-Zip `t` PASS，1946 files/18 folders |

安装器 manifest 仍为 `published=false`，`package_smoke=PASS`，`real_windows_install_status=PENDING`，`server_installation_status=PENDING`。这不代表真实 GUI、Windows Server 2016 升级、安装/卸载、签名或现场设备验收已经通过。较早 v1.5.13 Portable 候选目录保留作回滚/审计历史。

## 保留对象与未回收原因

- `test-data` 约 23.96 GiB：含当前有效 Fixture、数据库、日志、快照和真实测试记录；既有审计仅完成元数据重复线索，未具备逐项内容/引用确认，保留。
- `diagnostic` 约 3.04 GiB：含故障复现和验收证据，保留。
- `release` 历史版本和旧 v1.5.13 候选：保留回滚与审计能力，未按名称批量删除。
- `.venv`、Renderer `node_modules` 和其他开发依赖：当前开发环境仍有效，未清理。
- Git 对象及 `tmp_pack_*`/正式 pack：未执行对象清理或 GC；来源和引用边界不能仅凭空间判断。
- 顶层 `D:\study\NetConsole-Workspace\docs`：既有历史目录，Workspace Layout 检查仍报告为未登记顶层目录；因内容归属和引用未确认，本轮保留并报告，不强制迁移/删除。

## 验证结果

- `git status --short`：产品主仓清理前干净；报告分支只新增本报告。
- 产品本地 `main` 与 `github/main` 在清理前一致：`f78db74cda562bdc0d3bf3e74d669a6b33a11725`。
- PR #107/#108：GitHub 状态均为 `MERGED`。
- 便携 ZIP：7-Zip 完整性测试 PASS。
- 安装器/便携包：存在性、大小和 SHA-256 PASS。
- `python -m scripts.check_workspace_layout`：FAIL，仅剩既有顶层 `docs` 违规；本轮未新增顶层目录。
- 未重新执行业务回归、全量 Python、长稳、GUI 人工验收或现场验收。

## 状态字段

```text
WORKSPACE_AUDIT=PASS_WITH_EXISTING_LAYOUT_VIOLATION
PRODUCT_MAIN_BRANCH=main
PRODUCT_MAIN_SYNC=PASS_BEFORE_CLOSEOUT
LOCAL_BRANCH_CLEANUP=2_DELETED_OF_3_LOCAL_BRANCHES
WORKTREE_CLEANUP=NO_GIT_WORKTREE_TO_REMOVE;_EMPTY_NON_GIT_SHELL_REMOVED
TEMP_DATA_CLEANUP=SAFE_EXACT_TARGETS_ONLY
BUILD_CACHE_CLEANUP=2_REBUILDABLE_DIST_TREES_REMOVED
PROCESS_CLEANUP=PID_32812_STOPPED;KNOWN_NETCONSOLE_DEV_PORTS_CLEAR
RELEASE_ARTIFACTS_PRESERVED=PASS
INSTALLER_SHA256_VERIFIED=PASS
PORTABLE_SHA256_VERIFIED=PASS
PRODUCT_COMMIT=PENDING_CLOSEOUT_COMMIT
PRODUCT_PR=PENDING
PRODUCT_PUSH=PENDING_PROTECTED_PR
DEVSTATUS_COMMIT=PENDING
DEVSTATUS_PUSH=PENDING
DATA_SAFETY=PRODUCTION_AND_DEV_REAL_DATA_UNTOUCHED
OVERALL_STATUS=READY_FOR_REPORT_PR_AND_DEVSTATUS_UPDATE
```
