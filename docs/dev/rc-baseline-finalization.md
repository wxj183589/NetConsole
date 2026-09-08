# RC Baseline Finalization

日期：2026-09-08
阶段：Phase 2D-E2
Agent：codex-A
Codex-Thread：01a06938-7fc7-7741-a94c-c1007d93899b

## 结论

本阶段完成正式 main、merge、package source 的 provenance reconciliation，并从正式 `github/main` clean tree 重建 Full/Customer 安装器。工程回归和 packaged smoke 通过；真实 C7 复验因本阶段没有重新明确的维护窗口批准而未连接，实际 NSIS 安装 smoke 因当前执行会话不是管理员而阻塞。因此本阶段不宣布 RC baseline ready，也不执行 Production Backup 或 Cutover。

```text
PHASE2D_E2_STATUS=PASS_WITH_REAL_DEVICE_GATE
PROVENANCE_RECONCILED=PASS
RC_SOURCE_HEAD_FIXED=YES
RC_TREE_SHA_FIXED=YES
RC_BASELINE_READY=NO
PHASE2D_E_READY=NO
PHASE2D_READY=NO
REAL_DEVICE_REVALIDATION_REQUIRED=YES
REAL_DEVICE_CONNECTION_ATTEMPTED=NO
PRODUCTION_ACTIVATION_EXECUTED=NO
PRODUCTION_DATA_TOUCHED=NO
```

## Git Provenance

```text
FORMAL_MAIN_REMOTE=github
REMOTE_MAIN_HEAD_START=bc9c00f09d2e6698a2c25391ea917ef3872ff98e
REMOTE_MAIN_HEAD_FINAL=bc9c00f09d2e6698a2c25391ea917ef3872ff98e
FORMAL_WORKTREE_HEAD=bc9c00f09d2e6698a2c25391ea917ef3872ff98e
FORMAL_WORKTREE_TREE=fe8637f30d7a518bda483d3bc768f0d38a5c793d
MERGE_COMMIT=ab2f4c649887db34c9c6d510bf541eb8ca2a6178
MERGE_COMMIT_TREE=5f1a302c564b76d97d7656afb009b429f7e1b6bc
OLD_PACKAGE_SOURCE_HEAD=b2b6a18e691abf44c6c3f3fe65aa2579056b13ed
OLD_PACKAGE_SOURCE_TREE=24603d744004a33bbafeb2d15a63e6cbe0f6cf02
```

在 2026-09-08 Phase 2D-E2 验收当时，`bc9c00f0` 是正式 main；`ab2f4c64` 是先前的 no-ff merge commit；`b2b6a18e` 是上一轮报告收口 commit。三者 tree 均不同，且 `b2b6a18e` 与当时正式 main 之间包含报告/门禁收口差异，不能按 tree equivalent 复用旧 installer。旧包仅保留为 `OLD_VALIDATION_ARTIFACT`，不进入当时的最终 RC provenance。

```text
RC_SOURCE_HEAD=bc9c00f09d2e6698a2c25391ea917ef3872ff98e
RC_TREE_SHA=fe8637f30d7a518bda483d3bc768f0d38a5c793d
RC_SOURCE_IS_FORMAL_MAIN=YES
REMOTE_MAIN_HEAD_MATCH=YES
RC_MAIN_DRIFT=NO
PACKAGE_COMMIT_DIFFERS_BUT_TREE_EQUIVALENT=NO
```

本次没有发现 E1 之后新的 remote main 漂移；E0 之后的既有 H3C/SSH Relay 语义漂移仍要求真实设备复验，不能由离线回归替代。

## RC Packages

Full 和 Customer 均从 `RC_SOURCE_HEAD` clean tree 重建，使用同一版本、同一 build timestamp、同一 source head/tree，且 `packaged_dirty=false`。版本未递增，未发布 GitHub Release、tag 或自动更新 metadata。

| Flavor | Source SHA | Source tree | Build | Size | SHA-256 | Package smoke | Install smoke |
|---|---|---|---|---:|---|---|---|
| Full | `bc9c00f0` | `fe8637f3` | PASS | 157059455 | `869d24f342b25682bcc5f464b2007e4d5923a5f4248ec06a446010ec3f9c8f5a` | PASS | BLOCKED_ADMIN_REQUIRED |
| Customer | `bc9c00f0` | `fe8637f3` | PASS | 157059775 | `96926992897a2729fb3b56fca7d59e0d9190d56e0603d3ac5a17825c27a358cf` | PASS | BLOCKED_ADMIN_REQUIRED |

```text
APP_VERSION=1.5.5
VERSION_BUMPED=NO
PUBLISHED=false
FULL_PACKAGE_SOURCE_HEAD=bc9c00f09d2e6698a2c25391ea917ef3872ff98e
FULL_PACKAGE_SOURCE_TREE=fe8637f30d7a518bda483d3bc768f0d38a5c793d
CUSTOMER_PACKAGE_SOURCE_HEAD=bc9c00f09d2e6698a2c25391ea917ef3872ff98e
CUSTOMER_PACKAGE_SOURCE_TREE=fe8637f30d7a518bda483d3bc768f0d38a5c793d
FULL_CUSTOMER_SAME_SOURCE_HEAD=YES
FULL_CUSTOMER_SAME_SOURCE_TREE=YES
FULL_PACKAGE=PASS
CUSTOMER_PACKAGE=PASS
PACKAGE_SMOKE=PASS
VERSION_CONSISTENCY=PASS
```

包内 Backend/Frontend/health build metadata、NSIS subtype、Feature Profile、NOTICE/SBOM、7-Zip 解包完整性和 Full/Customer policy 均通过。`package-smoke` 是 managed Backend/Electron/Renderer 的 packaged smoke，不等价于管理员权限下的实际 NSIS 安装验收。

## Installer / Lifecycle

实际 NSIS fresh install 需要管理员权限写入 per-machine 安装和 `HKLM\Software\NetConsole\DataRoot`。当前会话不是管理员；尝试使用临时隔离 DataRoot 启动 elevated smoke 时在 UAC 等待阶段停止，未完成 Full/Customer 安装、启动、卸载链，因此不标记安装 PASS。临时指针已恢复为原值，隔离安装/数据根已清理。

```text
FULL_INSTALL_SMOKE=BLOCKED_ADMIN_REQUIRED
CUSTOMER_INSTALL_SMOKE=BLOCKED_ADMIN_REQUIRED
BACKEND_STARTUP=PASS_PACKAGED_SMOKE_ONLY
RENDERER_LOAD=PASS_PACKAGED_SMOKE_ONLY
DATA_ROOT_ISOLATION=PASS_PACKAGED_SMOKE_ONLY
UPGRADE_SMOKE=BLOCKED_ARTIFACT_NOT_AVAILABLE
UNINSTALL_SMOKE=BLOCKED_ADMIN_REQUIRED
RELEASE_POLICY_GATE_STATUS=HOLD
```

当前没有可用于正式 upgrade smoke 的上一版独立 installer；旧 `b2b6a18e` 包来源不是本 RC tree，不能充当本阶段 upgrade fixture。正式 release policy 中的真实 Windows 安装/升级/卸载仍保持人工验收缺口。

## Regression

```text
SCOPED_ROUTING=PASS
ENVELOPE=PASS
CAPABILITY_PRIMARY=PASS
FALLBACK=PASS
SINGLE_WRITER=PASS
ROLLBACK=PASS
SHADOW=PASS
B1_REHEARSAL=PASS
REPLAY=PASS
REPOSITORY=PASS
DEVICE_INVENTORY=PASS
TASK_CONTRACT=PASS
MAIN_CONTRACT=PASS
DOCS_PATH=PASS
ARCHITECTURE=PASS_WITH_BASELINE_DEBT
BASELINE_AUDIT=PASS
RUFF=PASS
COMPILE=PASS
DIFF_CHECK=PASS
CI_SELECTION=PASS
```

RC tree 上的 baseline-aware Python 全量为 `4760 passed, 2 skipped, 4 deselected`，`NEW_FAILURES=0`；Renderer 为 `180 files / 1290 tests`，Electron 为 `37 files / 298 tests`。原始 full-gate 入口仍会命中 manifest 中登记的 4 个 baseline 节点，另外一次顺序敏感 Ground 单测异常已在 20 个全新隔离数据根上全部通过，均如实保留，不修改 baseline 清单。

Architecture 仍为既有 baseline debt，`NEW_ARCHITECTURE_FINDINGS=0`。本阶段未修改 production source、Parser、DTO、Repository schema、Command Profile 或 Task state machine。

远程 `34161458613` 的 attempt 1 曾出现一次并发顺序敏感失败，`--failed` 重跑的 attempt 2 以 8/8 jobs PASS 收口；该历史没有改写为“从未失败”。本阶段正式 RC tree 的本地 baseline-aware 重跑也以 PASS 收口。

## C7 Real-device Revalidation

目标严格冻结为 `DEVICE-NB10-C7-01`。此前 3-cycle Shadow evidence 只绑定旧工程基线，不能单独作为本 RC 的真实证据。E2 要求维护窗口不能继承旧批准；本次上下文没有新的明确 `MAINTENANCE_WINDOW_APPROVED=YES`，因此没有建立 SSH/Telnet/SNMP 连接。

```text
TARGET=DEVICE-NB10-C7-01
REAL_DEVICE_READONLY_AUTHORIZED=YES (历史授权，不作为本次维护窗口批准)
MAINTENANCE_WINDOW_APPROVED=NO (本次未重新明确批准)
REAL_DEVICE_CONNECTION_ATTEMPTED=NO
CYCLE1=NOT_EXECUTED
CYCLE2=NOT_EXECUTED
CYCLE3=NOT_EXECUTED
REAL_DEVICE_REVALIDATION=HOLD
DEVICE_CONFIG_CHANGED=NO
REPOSITORY_EFFECT=NOT_EXECUTED
UNEXPECTED_WRITES=0
```

因此旧 `220/220` 证据继续标记为历史 Shadow evidence，不提升为 `C7 RC Revalidation PASS`。

## Security and Production Boundary

- 原始真实设备 CLI、Production database、备份和凭据均未生成或提交；本阶段仅有脱敏摘要和 gitignored 本地 manifest。
- `D:\NetConsoleData` 与 `D:\NetConsoleData-dev` 未用于构建、测试或安装 smoke；local gate 使用 `D:\study\NetConsole-Workspace\test-data\NetConsole\` 隔离子目录。
- `HKLM\Software\NetConsole\DataRoot` 的临时测试指针已恢复为原正式值；没有应用进程或 Backend 进程残留。
- `SECRET_SCAN=PASS`，`CREDENTIALS_COMMITTED=NO`，`PRODUCTION_DATA_TOUCHED=NO`。
- 本阶段未执行 Production Backup、Restore Evidence、Production Activation、Wave 0、Wave 1、C9、AC、ZTE 或其他设备连接；默认生产路径继续为 Legacy。

## Final Decision

```text
PROVENANCE_RECONCILED=PASS
RC_BASELINE_READY=NO
PHASE2D_E2_STATUS=PASS_WITH_REAL_DEVICE_GATE
PHASE2D_E_READY=NO
PHASE2D_READY=NO
PRODUCTION_BACKUP_EXECUTED=NO
PRODUCTION_ACTIVATION_EXECUTED=NO
PRODUCTION_CUTOVER_EXECUTED=NO
WAVE0_EXECUTED=NO
WAVE1_EXECUTED=NO
DEFAULT_PRODUCTION_PATH=LEGACY
```

Remaining gates：

1. 在新的明确维护窗口和只读授权下，用 `RC_SOURCE_HEAD` 对 `DEVICE-NB10-C7-01` 完成 3 个真实 C7 cycle。
2. 在管理员权限的隔离 Windows 环境完成 Full/Customer fresh install、managed Backend、Renderer、版本、DataRoot 和 uninstall smoke。
3. 按正式 Wave 0 时间重新执行 Production Backup、Restore Evidence、Maintenance Window 和 Wave 0 Owner Approval。

本阶段不进入 Production Cutover，也不自动扩大到 Wave 1、Comware 9、AC、ZTE 或其他设备。
