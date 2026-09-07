# Engineering Hardening：最新主线集成验证报告

## 1. 结论

本报告记录 `Phase 2D-E0 Latest Main Integration & Full Validation`。

结论：最新 `github/main` 已在独立基线 worktree 先行验证，并以普通 `--no-ff` 合并到独立集成分支；文本冲突为 0，关键迁移路径语义审查通过，集成回归没有新增失败，Full/Customer 正式安装器和 package smoke 均通过。

本阶段没有执行 Production Cutover，没有连接真实设备，没有读取或修改 `D:\NetConsoleData`，没有启用任何 Capability Primary。默认生产路径仍为 Legacy。

```text
PHASE2D_E0_STATUS=PASS
PHASE2D_E_READY=YES
PHASE2D_READY=NO
PRODUCTION_CUTOVER_EXECUTED=NO
REAL_DEVICE_CONNECTION_ATTEMPTED=NO
```

`PHASE2D_E_READY=YES` 仅表示集成候选具备进入下一次独立 Production Wave 0 Gate Review 的工程条件，不表示已通过 Production Backup、维护窗口或 Wave 0 Owner 批准，也不表示本报告执行了切换。

## 2. Git 基线与集成拓扑

| 项目 | 值 |
|---|---|
| Engineering branch | `codex-A/engineering-hardening` |
| Engineering HEAD | `65a6e2550e071075a3d40325799166197e9378b8` |
| Tracking remote | `github` |
| Latest main ref | `github/main` |
| Latest main HEAD | `6e6b4db062ed644250ebe4abdd1d0eac40d315a1` |
| Merge base | `1463647471d6d5836a6c0fc692062d35290aa0fd` |
| Integration branch | `codex-A/engineering-hardening-latest-integration` |
| Integration merge commit before this report | `9bba7b710ad80b044d7e4bdc0487ec2d4c3be687` |
| Fetch | PASS (`git fetch --all --prune`) |
| Latest-main baseline worktree | `D:\study\NetConsole-Workspace\worktrees\engineering-hardening-latest-main-baseline` |
| Integration worktree | `D:\study\NetConsole-Workspace\wi` |

开始检查时 Engineering worktree 与 main checkout 均 clean。集成使用普通历史合并，没有使用全局 `ours`/`theirs`，没有修改 main checkout、Engineering worktree 或其他 worktree。

## 3. Latest-main baseline

最新主线先于合并验证。主线自身保留以下已知 baseline debt；这些失败没有被计入集成新增失败：

| Gate | Latest-main baseline |
|---|---|
| Python full pytest | `4658 passed, 2 skipped, 4 failed, 33 warnings` |
| Python baseline failures | 4 个既有架构/版本策略失败 |
| Renderer tests | `180 files passed, 1290 tests passed` |
| Renderer typecheck/build | PASS |
| Electron tests | `37 files passed, 298 tests passed` |
| Electron typecheck/main build | PASS |
| Main contract smoke | `12 passed, 3 warnings` |
| Docs/path/layout | `27 passed` |
| Architecture audit | 4 个既有 findings，未产生新的迁移相关 finding |
| Ruff | 4 个既有 baseline findings |
| Compileall | PASS |
| `git diff --check` | PASS |

Latest-main 的 4 个 Python failure 与 4 个 Ruff findings 属于主线在合并前已存在的架构/版本策略债务；集成分支通过 baseline-aware pytest 和 baseline debt audit 重新确认其边界。

## 4. Overlap matrix

变更路径集合的直接交集为 0。另对 migration envelope、scoped router、rollout policy、Capability Primary、Legacy fallback、Single Writer、rollback、Repository consumer、Task/job routing 进行了语义审查，并以集成测试覆盖。

| 领域 | Latest main 直接变更 | Engineering hardening 直接变更 | 文本冲突 | 语义审查 | 结果 |
|---|---:|---:|---:|---:|---|
| Device Inventory / application service | NO | YES（集成到既有服务路径） | NO | PASS | PASS |
| H3C collector | NO | YES | NO | PASS | PASS |
| Parser / DTO contract | NO | NO（复用现有 contract） | NO | PASS | PASS |
| Repository / DeviceFactRepository consumer | NO | YES | NO | PASS | PASS |
| Task runtime / job routing | NO（主线只改非迁移 site handler） | NO（复用既有 runtime） | NO | PASS | PASS |
| Scoped migration router | NO | YES | NO | PASS | PASS |
| Electron backend | YES | NO | NO | PASS | PASS |
| Renderer / UI | YES | NO | NO | PASS | PASS |
| Command profile / guard | NO | NO | NO | PASS | PASS |
| Packaging / release identity | NO（本阶段未改 packaging code） | NO | NO | PASS | PASS |

```text
TEXTUAL_OVERLAP_CANDIDATE_COUNT=0
TEXTUAL_CONFLICT_COUNT=0
SEMANTIC_OVERLAP_COUNT=0
SEMANTIC_OVERLAP_REVIEW=PASS
DUPLICATE_CAPABILITY_RESOLVED=NOT_APPLICABLE
```

主线改动集中在 Electron tray、site storage、Renderer site/AC/Trackside AP presentation 与相关服务；没有改动 H3C collector、interface discovery router、command profile/guard、DeviceFactRepository 写入实现或 scoped rollout policy。因此按照本阶段规则不要求重新连接真实 C7 设备。

## 5. Migration safety review

已检查以下实际源码与测试，不引入现场临时修改：

- `interface_discovery_routing.py`：缺失/禁用/不可信版本/不匹配 envelope 时 fail closed 到 Legacy；只识别 `device inventory`、`interface.discovery`、H3C switch、Comware 7 scoped target。
- `device_operation_service.py`：规划阶段和 worker 阶段均复核 submitted platform facts；Capability 仅在 route decision 通过后作为 primary，失败仍沿既有 Legacy fallback。
- `h3c_collect_service.py`：复用现有安全 command profile、parser、collector 与 DeviceFactRepository 语义。
- `interface_discovery_shadow.py`：observe-only；不进入 current/recent/history/revision 写路径。
- Repository 写入、Task/job execution、production backup 的现有边界：本阶段只做离线/隔离验证，没有生产写入。

集成后确认：

```text
MIGRATION_ENVELOPE=PASS
DEFAULT_PRODUCTION_PATH=LEGACY
PRODUCTION_CAPABILITY_PRIMARY_ENABLED=NO
C7_SWITCH_ELIGIBLE=SCOPED_ONLY
C9_SWITCH_ELIGIBLE=NO
WIRELESS_CONTROLLER_ELIGIBLE=NO
ZTE_ELIGIBLE=NO
UNKNOWN_VERSION_BEHAVIOR=LEGACY
CAPABILITY_PRIMARY=PASS
LEGACY_FALLBACK=PASS
SINGLE_WRITER=PASS
DOUBLE_WRITE_OBSERVED=NO
SCOPED_ROLLBACK=PASS
POLICY_FAILURE_DEFAULT=LEGACY
```

## 6. Integrated validation

核心迁移、shadow、replay、Repository、inventory、database framework、docs/path/layout 定向集合：

```text
149 passed in 8.65s
```

全量 Python 使用 `scripts.quality.baseline_aware_pytest`，明确排除 4 个主线既有 baseline tests：

```text
4734 passed, 2 skipped, 4 deselected, 33 warnings
BASELINE_EXCLUSIONS=4
PYTHON_REGRESSION_NEW_FAILURES=0
NEW_FAILURES=0
```

集成 baseline debt audit：

```text
ARCHITECTURE_BASELINE_EXPECTED=7
ARCHITECTURE_BASELINE_ACTUAL=7
ARCHITECTURE_BASELINE_NEW=0
ARCHITECTURE_BASELINE_RESOLVED=0
RUFF_BASELINE_EXPECTED=4
RUFF_BASELINE_ACTUAL=0
RUFF_BASELINE_NEW=0
RUFF_BASELINE_RESOLVED=4
BASELINE_DEBT_COUNT=15
NEW_FAILURES=0
BASELINE_DEBT_MATCH=PASS
```

集成架构审计仍报告主线已有 4 个 finding；没有新增 finding。集成 Ruff 为 `All checks passed!`，与 baseline manifest 的既有 debt 账本一致。

| Gate | 集成结果 |
|---|---|
| Scoped routing / Capability Primary / fallback / Single Writer / rollback | PASS |
| Shadow / B1 rehearsal / replay | PASS |
| Repository / Device Inventory | PASS |
| Main contract smoke | `12 passed, 3 warnings` |
| Docs/path/layout | `27 passed`（包含在定向集合中） |
| Python full baseline-aware | PASS，无新增失败 |
| Renderer tests | `180 files, 1290 tests passed` |
| Renderer typecheck/build | PASS；仅有既有 chunk-size warning |
| Electron tests | `37 files, 298 tests passed`（serial isolated recheck） |
| Electron backend startup smoke | PASS（`real-backend.test.ts` recheck） |
| Electron typecheck/main build | PASS |
| Architecture | PASS with 4 known baseline findings; new findings 0 |
| Ruff | PASS；new findings 0 |
| Compileall | PASS |
| `git diff --check` | PASS |

Electron 初次并行全量运行曾因隔离测试目录锁竞争出现 EBUSY/timeout；未修改源码，随后使用单文件并行关闭、单 worker 和隔离 data root 重跑：`real-backend.test.ts` 通过，完整 Electron suite `37/298` 通过。该环境性波动没有留下集成失败。

## 7. Packaging gate

使用正式 `pnpm run package:all` 入口，先将同一集成提交推送到集成分支 upstream，再在短路径临时 worktree 执行，以满足仓库的 clean/synced git 与 Windows NSIS path 要求。没有执行 release、tag、发布或版本变更。

```text
PACKAGING=PASS
FULL_PACKAGE=PASS
CUSTOMER_PACKAGE=PASS
PACKAGE_SMOKE=PASS
PACKAGE_SOURCE_GIT_HEAD=9bba7b710ad80b044d7e4bdc0487ec2d4c3be687
PACKAGE_VERSION=1.5.5
PACKAGE_BUILD_NUMBER=0
PACKAGE_PUBLISHED=false
VERSION_BUMPED=NO
RELEASE_PUBLISHED=NO
```

Full 与 Customer 均通过：冻结 Backend/status、device database migration/list HTTP 200、feature policy、MESH import idempotency、duplicate-safe archive naming、Worker protocol、Qt residue、NOTICE/SBOM metadata 与 7-Zip 解包验证。安装包和 build output 均为隔离 worktree 下的 ignored 临时制品，不提交 Git。

## 8. Real-device gate

本阶段没有真实设备重验证：

```text
REAL_DEVICE_REVALIDATION_REQUIRED=NO
REAL_DEVICE_REVALIDATION_REASON=LATEST_MAIN_DID_NOT_CHANGE_CRITICAL_MIGRATION_PATHS
REAL_DEVICE_READONLY_AUTHORIZED=YES
MAINTENANCE_WINDOW_APPROVED=NO
REAL_DEVICE_CONNECTION_ATTEMPTED=NO
TARGET=NOT_EXECUTED
CYCLE1=NOT_EXECUTED
CYCLE2=NOT_EXECUTED
CYCLE3=NOT_EXECUTED
REPOSITORY_EFFECT=NOT_EXECUTED
STOP_RESUME=NOT_EXECUTED
```

原因是 latest main 与工程加固分支没有直接或语义冲突，且 latest main 未修改本阶段定义的 H3C connection/collector、Device Inventory migration service、parser/DTO、scoped router、capability/fallback、Repository write path、command guard 或版本识别关键路径。已有 C7 真实 Shadow 证据仍由既有报告和 replay/shadow regression 覆盖。根据授权约束，本阶段没有因为集成成功而扫描或连接任何设备，也没有连接 Comware 9、AC、无线、ZTE 或其他 C7。

## 9. Production safety and data boundary

```text
PRODUCTION_CUTOVER_EXECUTED=NO
PRODUCTION_CAPABILITY_PRIMARY_ENABLED=NO
PRODUCTION_PATH=LEGACY
PRODUCTION_DATA_TOUCHED=NO
DEV_REAL_DATA_TOUCHED=NO
ISOLATED_DATA_ROOT_USED=YES
BACKUP_EXECUTED=NO
ACTIVATION_EXECUTED=NO
GLOBAL_ACTIVATION_EXECUTED=NO
DATABASE_REPAIR_REQUIRED=NO
PROCESS_RESTART_REQUIRED=NO
HISTORY_REBUILD_REQUIRED=NO
C9_SWITCH_ACTIVATED=NO
WIRELESS_CONTROLLER_ACTIVATED=NO
MOBILE_ROUTER_ACTIVATED=NO
ZTE_ACTIVATED=NO
OTHER_C7_SWITCH_ACTIVATED=NO
NEIGHBOR_DISCOVERY_ACTIVATED=NO
TRANSCEIVER_READ_ACTIVATED=NO
PROFILE_CHANGED=NO
PARSER_CHANGED=NO
DTO_CHANGED=NO
REPOSITORY_SCHEMA_CHANGED=NO
API_CHANGED=NO
UI_CHANGED=NO
TASK_STATE_MACHINE_CHANGED=NO
```

本阶段的 source 变更来自已完成的 engineering-hardening 分支与 latest-main 正常合并；E0 收口本身只新增本报告。Production activation state 没有写入 Git、数据库或 Production data root。

## 10. Evidence and secret boundary

```text
EVIDENCE_BUNDLE=PASS
RAW_EVIDENCE_LOCAL_ONLY=YES
REAL_CAPTURE_C7=EXISTING_PRIOR_LOCAL_ONLY
REAL_CAPTURE_DEIDENTIFIED=NO
SECRET_SCAN=PASS
```

本阶段未生成新的真实 CLI capture、REAL_CAPTURE fixture、生产数据库备份或原始生产日志。既有 shadow/rehearsal fixture secret scan、inventory fixture credential-token test、package smoke 资源/身份校验均通过；报告只使用 commit、别名、状态和计数，不包含密码、Token、SNMP community、真实地址、MAC、序列号或用户名。

## 11. Formal merge decision

```text
FORMAL_MAIN_MERGE_READY=YES
FORMAL_MAIN_MERGE_EXECUTED=NO
INTEGRATION_BRANCH_PUSHED=YES
MAIN_BRANCH_PUSHED=NO
ENGINEERING_BRANCH_MODIFIED=NO
```

本集成分支可以作为下一次正式审查候选，但本报告不执行 main merge，不执行 Production Cutover，也不自动进入 Wave 1。下一阶段仍需独立处理：

1. Production Backup、manifest/SHA-256 与隔离 Restore Evidence；
2. 当次维护窗口明确批准；
3. Wave 0 Owner 明确批准；
4. 仅针对 `DEVICE-NB10-C7-01` 的 Production Wave 0 activation 与有限观察；
5. C9、AC、无线、ZTE、其他站点/线路、neighbor.discovery、transceiver.read 继续 Legacy。

## 12. Final status

```text
PHASE2D_E0_STATUS=PASS
PHASE2D_E_READY=YES
PHASE2D_READY=NO
WAVE0_EXECUTED=NO
WAVE1_EXECUTED=NO
AUTOMATIC_SCOPE_EXPANSION=NO
```
