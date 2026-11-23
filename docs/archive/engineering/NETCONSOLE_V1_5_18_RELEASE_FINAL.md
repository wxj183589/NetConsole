# NetConsole v1.5.18 最终发布执行报告

日期：2026-11-23

## 1. 最终判定

```text
NETCONSOLE_VERSION=1.5.18
RELEASE_STATUS=PARTIAL
AUTOMATED_RELEASE_GATE=PASS
INSTALLER_BUILD=PASS
PORTABLE_BUILD=PASS
PACKAGE_SHA256=PASS
CLIENT_STARTUP=PENDING
REAL_WINDOWS_INSTALL=PENDING
AUTHENTICODE=NOT_SIGNED
PRODUCTION_DATA_MODIFIED=0
DEV_REAL_DATA_MODIFIED=0
DATABASES_REMOVED=0
```

历史文件迁移、完整 Gate、候选分支推送、正式 `main` 快进发布、Installer/Portable 构建、包内 smoke、制品身份和 SHA-256 校验均已完成。

本轮未在全新 Windows 机器或 VM 上执行真实 GUI 安装、首次启动、数据根向导、升级、卸载和跨机验收；Installer 与 Portable 也未做 Authenticode 签名。因此自动化结果不能提升为正式人工安装验收 PASS，最终发布状态保持 `PARTIAL`。

## 2. 历史文件迁移

使用 Git 原生 rename 将两个 v1.5.17 历史文件迁入既有同源调查目录，文件内容和 Git blob 均未改变。

| 原路径 | 迁移后路径 | SHA-256 | Git 结果 |
| --- | --- | --- | --- |
| `NETCONSOLE_V1_5_17_RELEASE_NOTES.md` | `docs/investigations/netconsole-v1.5.17-code-audit-20261121/NETCONSOLE_V1_5_17_RELEASE_NOTES.md` | `9D514DC7DDE9CF426D378516A2335C1146CF4AD782BEAF4A46CC3B3D9B2B297A` | 100% rename |
| `V1_5_17_CHANGELOG.md` | `docs/investigations/netconsole-v1.5.17-code-audit-20261121/V1_5_17_CHANGELOG.md` | `4DB4CAD104D7D9E32ED789FBD7151B05BA3101AEDE21ED83970A385398A7C711` | 100% rename |

引用审计结论：没有源码、CI、构建、安装器、CHANGELOG 同步或 Markdown 相对链接消费者；历史报告保持原始文本，不做批量路径替换。未新增 Root Layout 白名单，未降低任何 Guard。

配套审计文档：

- `docs/archive/engineering/V1_5_17_HISTORICAL_FILES_REFERENCE_AUDIT.md`
- `docs/archive/engineering/V1_5_17_HISTORICAL_FILES_MIGRATION_PLAN.md`

## 3. 完整 Gate

### 3.1 候选分支 Gate

候选提交前从迁移后的实际代码组合重新执行 L4 Full Gate：

| Gate | 结果 |
| --- | --- |
| Root Layout | PASS |
| Workspace Layout | PASS |
| Renderer tests | PASS, 219 files / 1584 tests |
| Renderer typecheck | PASS |
| Renderer production build | PASS |
| Python full | PASS, 5716 passed / 2 skipped / 34 warnings |
| Electron tests | PASS, 41 files / 324 tests |
| Electron typecheck / main build | PASS |
| Architecture Guard | PASS, 12/12 |
| Main contract smoke | PASS, 12 passed |
| Ruff | PASS |
| Docs Path Guard | PASS, 22 passed |
| Git diff check | PASS |
| 版本与发布定向测试 | PASS, 75 passed |
| Python compileall | PASS |
| Qt-free Python environment | PASS |
| 锁定依赖闭包 | PASS, 52 distributions |
| CHANGELOG sync | PASS |

### 3.2 合并后正式 main Gate

在 `main` 的实际发布提交 `f842d7ed1601158b4cc783ad4a0e526d02d0462c` 上重新执行：

```powershell
python -m scripts.quality.local_gate --mode full `
  --base-sha 9e463778f0ece54fb16cb31c877da86ff8bce438 `
  --head-sha HEAD
```

结果：

| Gate | 结果 |
| --- | --- |
| Change Impact | L4 |
| Root Layout | PASS |
| Workspace Layout | PASS |
| Renderer full | PASS, 219 files / 1584 tests |
| Renderer typecheck / production build | PASS |
| Python full | PASS, 5716 passed / 2 skipped / 34 warnings, 1479.55s |
| Electron contract | PASS, 41 files / 324 tests |
| Electron typecheck / main build | PASS |
| Architecture Guard | PASS, 12/12 |
| Main contract smoke | PASS, 12 passed |
| Ruff | PASS |
| Docs Path Guard | PASS, 22 passed |
| Git diff check | PASS |

自动 Gate 使用 `RuntimeMode.TEST` 和 Workspace 隔离测试根。未读取或修改 `D:\NetConsoleData`、`D:\NetConsoleData-dev`，未连接真实设备。

## 4. Git 发布事实

| 项目 | 结果 |
| --- | --- |
| 历史主线基线 | `9e463778f0ece54fb16cb31c877da86ff8bce438` |
| Renderer 架构整改 | `c1a7cbe5` |
| 报告补录 | `abd6ed89` |
| 历史文件迁移提交 | `f842d7ed1601158b4cc783ad4a0e526d02d0462c` |
| 候选分支 | `codex-A/release-v1.5.18-20261123` |
| 远端候选分支 | `github/codex-A/release-v1.5.18-20261123` |
| 合并方式 | 经规则审计后正常 fast-forward push，无 PR、无 bypass、无 force push |
| 正式制品源码提交 | `f842d7ed1601158b4cc783ad4a0e526d02d0462c` |
| 构建时 local main / github/main | 相等 |

GitHub `main` ruleset 在执行时只禁止删除和非快进更新，没有强制 PR、Review 或 Status Check。候选提交已经在完整 Gate 后推送，随后以正常 fast-forward 发布到 `github/main`。

主仓库 Worktree 中存在另一任务的 Console/SFTP dirty 修改。本轮只在独立 release Worktree 操作，未修改、暂存、提交、清理或回滚该并行状态。

## 5. Windows 制品

正式制品目录：

`D:\study\NetConsole-Workspace\release\v1.5.18\build-0-f842d7ed`

| 制品 | 字节数 | SHA-256 | 自动验证 |
| --- | ---: | --- | --- |
| `NetConsole-Full-1.5.18.0-f842d7ed-x64-setup.exe` | 158475377 | `a40b08fb7c7c0c7d753b19b58d1550842a2623ec680f48148a3499b962dfc01d` | PASS |
| `NetConsole-1.5.18-portable.zip` | 215956642 | `87858314fea601fe3feabc35be0fcf0e2d02ee127eab2a5610fc0b3b16c538e4` | PASS |

### 5.1 Installer

- `version=1.5.18`，`file_version=1.5.18.0`，Build Number `0`。
- NSIS subtype：`NSIS-3 Unicode`。
- Installer/Backend/Frontend commit 均为 `f842d7ed1601158b4cc783ad4a0e526d02d0462c`。
- `packaged_dirty=false`，`edition=full`，`feature_profile=full`。
- `admin_unlock_configured=false`。
- 包内 package smoke PASS，冻结时区、设备兼容 Profile、数据库迁移/查询、Ground、MESH 重名导入、Worker 中文协议、NOTICE/SBOM 和无 Qt 残留均通过。
- 最终 EXE 由完整 7-Zip 26.03 直接解析并复核。

### 5.2 Portable

- ZIP 完整性 PASS：18 folders / 1948 files。
- 包含 `NetConsole.exe`、`portable.mode`、冻结 Backend、runtime build metadata 和 Full feature profile。
- `version=1.5.18`，`file_version=1.5.18.0`，Build Number `0`。
- Backend/Frontend commit 均为 `f842d7ed1601158b4cc783ad4a0e526d02d0462c`。
- `build_source=git-release`，`packaged_dirty=false`。
- `edition=full`，`feature_profile=full`，`admin_unlock_enabled=false`。
- 对 Portable `win-unpacked` 执行 canonical package smoke：PASS。
- 默认数据根与 `portable-data-root.json` 行为已由 Electron 全量测试覆盖；真实解压后 GUI 首次启动仍为 PENDING。

### 5.3 归档纠正记录

正式 Installer 构建本体和 manifest 正确，但 `package_local.ps1` 在共享虚拟环境的 editable install 下仅在归档目录名读取到旧 `v1.5.17`，从而把本轮新建的 `build-0-f842d7ed` 暂时归入 `release\v1.5.17`。经核对该目录完全由本轮生成、目标 `v1.5.18` 尚不存在后，将整个 build 目录原子移动到 `release\v1.5.18`，并修正本轮 `BUILD_SUMMARY` 的版本字段。既有 v1.5.17 制品未修改；最终两个制品的 SHA-256 与原始 manifest 均保持一致。

## 6. 人工验收缺口

以下项目没有自动化替代物，本轮未在隔离的全新 Windows 机器或 VM 中执行：

- NSIS GUI 安装、程序首次启动、Backend/Renderer 可见加载；
- 数据根不存在、空目录、含普通文件、合法旧根四种安装向导路径；
- HKLM 32/64 位 DataRoot 指针核对；
- 安装版与 Portable 数据互不污染；
- Portable 解压后真实 GUI 首次启动和自定义数据根；
- 升级、修复、普通卸载、清洁卸载；
- 无 Python/Node/pnpm/Git/Go/源码的新机器；
- 普通用户、中文用户名、中文安装路径和中文数据路径；
- Windows Server 支持矩阵；
- Authenticode 签名与签名信任链；
- 真实或仿真 H3C 设备和长时间运行。

因此：

```text
CLIENT_STARTUP=PENDING
REAL_WINDOWS_INSTALL=PENDING
SERVER_INSTALLATION=PENDING
AUTHENTICODE=NOT_SIGNED
```

## 7. 分支与 Worktree

- 正式发布 Worktree 已从候选分支切换到 `main`。
- 当前正式制品来源为 clean、已推送的 `main@f842d7ed`。
- 本地候选分支 `codex-A/release-v1.5.18-20261123` 已完全合并，但按“全部发布验收成功后再回收”的条件暂时保留，因为真实 GUI 安装/启动/卸载和签名仍未完成。
- 未删除远端候选分支，未删除其他分支，未修改其他 Worktree。
- 未修改 `NetConsole-DevStatus`。

## 8. 后续发布门

要将 `RELEASE_STATUS` 从 `PARTIAL` 提升为 `PASS`，必须使用上述两个固定哈希制品，在隔离的全新 Windows 机器或 VM 中完成项目文档规定的 GUI 安装、启动、数据根、Portable、升级/卸载和签名验收，并保存可复核证据。全部通过后，才可安全删除本地候选分支并进行后续 Tag/GitHub Release 操作。
