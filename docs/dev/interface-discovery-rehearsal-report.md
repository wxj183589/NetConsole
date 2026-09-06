# Interface Discovery Isolated Rehearsal Report

> Phase: `PHASE 2D-B1`
> Result: `PASS`
> Environment: isolated pytest `tmp_path` only
> Real device connection: `NO`
> Production Shadow enabled: `NO`

## 1. Rehearsal scope

本次 rehearsal 只验证 interface discovery Shadow 的安全行为，不验证真实设备 CLI 兼容性，也不执行生产切换。输入使用现有 H3C Comware 7 synthetic replay fixture；Legacy 结果通过现有 `DeviceFactRepository` 写入隔离 `devices.db`，Shadow 只接收 normalized result callback。

本轮没有修改 Legacy Collector、Parser semantics、DTO schema、Repository write path、Task state machine、API、UI、Profile JSON 或正式 Operation。没有新增 runtime Feature Flag，验证中的启停只存在于 test harness：

```text
NO_RUNTIME_FEATURE_FLAG_ADDED=YES
PRODUCTION_DATA_TOUCHED=NO
DEV_REAL_DATA_TOUCHED=NO
REAL_DEVICE_CONNECTED=NO
```

## 2. Environment isolation

测试使用仓库既有 pytest `tmp_path` 和 `NETCONSOLE_DATA_ROOT` 隔离约束。每次运行创建独立 test root，数据库为该 root 下的 `sites/<site>/db/devices.db`；临时 evidence/backup 也只位于该 root，测试退出后由既有 pytest 清理逻辑处理。

没有访问或修改 `D:\NetConsoleData`、`D:\NetConsoleData-dev`，没有复制完整 Production Site/数据库，也没有执行真实 SSH/Telnet/SNMP/SFTP。`artifacts/engineering-hardening/interface-discovery-rehearsal/` 只是建议的临时输出布局，本次 JSON evidence 不作为仓库 runtime artifact 提交。

## 3. Repository fingerprint method

`tests/support/interface_discovery_rehearsal.py` 提供 test-only `repository_fingerprint()`，通过现有 `Database.connect_readonly()` 查询，使用稳定排序、canonical JSON 和 SHA-256。实际 Repository 映射如下：

| 逻辑层 | 实际表 |
| --- | --- |
| Current | `device_facts`、`device_interfaces`、`device_optical_modules`、`device_lldp_neighbors` |
| Recent | `device_fact_recent`（Device Fact 的 bounded Recent10） |
| History | 四类 `device_*_history` 表；接口、光模块和 LLDP 的历史由现有 bounded retention 实现约束 |

每张表记录 `total_count`、目标设备 `device_record_count`、全表/目标设备 semantic hash；History 额外记录按现有插入顺序生成的 semantic row hash sequence。`schema_metadata` 的 key/value 和行内 `source_revision` 纳入指纹，用于发现 revision/generation 变化。

以下 runtime metadata 不参与 semantic hash：`id`、`created_at`、`updated_at`、`collected_at`、`collect_run_uuid`、`raw_log_path`、`changed_at`、`first_seen_at`、`last_seen_at`、`vlan_config_collected_at`。这样不会把合法采集时间/运行 ID 变化误报为 Shadow 业务写入，同时仍能在 Shadow 前后发现 Current/Recent/History、revision 或数量变化。

Repository Effect 使用两层证据：

1. F1 Legacy-only 完成后分别与 F2-F6 Shadow 场景完成后比较 Current/Recent/History/revision fingerprint，要求全部 `NONE`。
2. `WritePathCounter` 对现有 `upsert_device_fact`、`replace_device_interfaces`、`replace_optical_modules`、`replace_lldp_neighbors` 做 call-level spy；Shadow callback 前后 writer call count 必须完全不变。

F7 是停止 Shadow 后再次执行 Legacy 的恢复点。F7 允许且应归因于 Legacy 自身的 expected delta；它不被错误当成 Shadow effect。

## 4. Scenario results

| Scenario | Legacy | Shadow | Compare | 结果 |
| --- | --- | --- | --- | --- |
| MATCH | `SUCCESS` | `SUCCESS` | `MATCH` | Legacy 结果/Task 保持成功，Repository effect `NONE` |
| DIFFERENT | `SUCCESS` | `SUCCESS` | `DIFFERENT` | 受控制造 speed 差异，并同时验证 `added`/`removed`/`changed`；不 autofix、不写库 |
| ERROR | `SUCCESS` | `FAILED` | `SHADOW_FAILED` | 受控异常被隔离，Legacy 不变为 FAILED |
| TIMEOUT | `SUCCESS` | `TIMEOUT` | `SHADOW_FAILED` | 通过短路径 `TimeoutError` 演练，不使用长时间 sleep，Legacy 不等待不合理时间 |
| EMPTY | `SUCCESS` | `EMPTY` | `DIFFERENT` | 空接口结果按既有契约分类，不覆盖 Legacy、不写库 |
| INVALID | `SUCCESS` | `FAILED` | `SHADOW_FAILED` | 缺少 `interfaces` 的无效结果被隔离，Task 仍为成功 |

指纹采集点完整覆盖：

```text
F0 initialization complete
F1 Legacy-only normal run
F2 MATCH
F3 DIFFERENT
F4 ERROR
F5 TIMEOUT
F6 EMPTY
F7 Shadow disabled / Legacy-only resumed
```

所有 Shadow 场景均满足 `repository_effect=NONE`、`unexpected_writes=0`、`task_status_before=SUCCESS`、`task_status_after=SUCCESS`。

## 5. Controlled stop/resume and rollback

测试 harness 按以下流程演练：

```text
Legacy-only
  -> enable test-only Shadow invocation
  -> MATCH or ERROR/TIMEOUT
  -> disable Shadow
  -> Legacy-only continues
  -> Legacy runs again
  -> Task/Repository safety checks
```

已覆盖一次 MATCH 后停止，以及 ERROR/TIMEOUT 后停止。停止 Shadow 不需要数据库修复、进程重启、应用重装、数据回滚或 history rebuild；Shadow callback 不持有 Repository，Legacy 继续通过既有 writer path 运行。

```text
ROLLBACK_REHEARSAL=PASS
CONTROLLED_STOP_RESUME_REHEARSAL=PASS
SHADOW_STOP=PASS
LEGACY_RESUME=PASS
DATABASE_REPAIR_REQUIRED=NO
PROCESS_RESTART_REQUIRED=NO
HISTORY_REBUILD_REQUIRED=NO
```

## 6. Pre-switch backup manifest rehearsal

备份演练复用现有 `DatabaseBackupStore`，只对隔离 `devices.db` 执行。manifest 已验证包含：

- isolated data-root identity、database/file list、source size、mtime 和 source SHA-256；
- SQLite schema/version metadata、application version、source git SHA、branch、timestamp；
- backup target、database backup size/SHA-256、quick check/integrity check 和 restore notes。

验证结果：

```text
PRE_SWITCH_BACKUP_REHEARSAL=PASS
MANIFEST_FORMAT=existing DatabaseBackupStore manifest.json
SHA256_VERIFIED=YES
SOURCE_MUTATED=NO
PRODUCTION_BACKUP_EXECUTED=NO
```

这不等价于 Production backup PASS；本轮没有访问 Production，也没有执行真实切换前备份或恢复。

## 7. Evidence bundle schema and secret handling

test-only evidence bundle 由 `write_evidence_bundle()` 生成 `summary.json` 和按场景 JSON。schema 至少包含：

```text
phase
status
run_id
git_sha
branch
test_root
scenario
scenarios
repository_fingerprint_before
repository_fingerprint_after
repository_effect
task_status_before
task_status_after
rollback_status
backup_manifest_status
errors
production_touched
real_device_connected
```

写入前执行 `secret_scan()`，拒绝典型敏感 key/value：`password`、`secret`、`token`、`community`、`private_key`、`credential`。受控异常使用现有 Shadow Runner 的 redaction；证据中不保存密码、Token、SNMP community、私钥、完整敏感配置或现场 IP。

## 8. Gate result and remaining blockers

```text
MATCH_REHEARSAL=PASS
DIFFERENT_REHEARSAL=PASS
ERROR_REHEARSAL=PASS
TIMEOUT_REHEARSAL=PASS
EMPTY_REHEARSAL=PASS
REPOSITORY_EFFECT_REHEARSAL=PASS
ROLLBACK_REHEARSAL=PASS
CONTROLLED_STOP_RESUME_REHEARSAL=PASS
PRE_SWITCH_BACKUP_REHEARSAL=PASS
REPLAY=PASS
SHADOW_REGRESSION=PASS
NEW_FAILURES=0
BASELINE_DEBT_MATCH=PASS
```

因此工程侧可以标记：

```text
PHASE2D_B1_STATUS=PASS
PHASE2D_B_REAL_DEVICE_READY=YES
ENGINEERING_GATES_READY=YES
REAL_DEVICE_VALIDATION_EXECUTED=NO
REAL_DEVICE_AUTHORIZATION_REQUIRED=YES
PHASE2D_READY=NO
```

`PHASE2D_B_REAL_DEVICE_READY=YES` 只表示不依赖真实设备的工程 Gate、隔离回滚/Repository/备份/Evidence rehearsal 已具备执行条件；它不表示真实设备验证已经执行，也不授予生产 Shadow 启用权限。

## 9. Automated test record

- Rehearsal、Shadow、Replay、DeviceFactRepository、Device Detail task seam：`93 passed`。
- Docs/path：`22 passed`；CI selection：`1 passed`；Architecture green gates：`8/8 PASS`；Ruff、compile 和 `git diff --check`：`PASS`。
- Main Contract Smoke：`12 passed, 3 warnings`；warnings 为现有 Starlette deprecation warnings。
- `baseline_debt_audit --checks all`：`NEW_FAILURES=0`、`BASELINE_DEBT_MATCH=PASS`；架构新增债务为 0、Ruff 新增债务为 0。
- 一次完整 baseline-aware pytest 记录为 `4695 passed, 2 skipped, 4 deselected, 1 failed`，失败为现有 `tests/test_release_system.py::test_clean_build_runtime_subset_copies_only_imported_modules_and_assets`；随后独立复跑该 node 为 `1 passed`。该环境/顺序敏感观察未修改、未归因于本轮 rehearsal 文件，后续仍应保留在回归关注项中。

剩余阻塞：

1. 取得批准的 H3C Comware 7/9 低风险设备、owner 和维护窗口。
2. 在真实环境执行 Limited Validation，收集真实 device/version/CLI/parse/report/effect evidence。
3. 取得真实环境 controlled stop/resume 和后续切换授权；在此之前保持 Legacy-only。
