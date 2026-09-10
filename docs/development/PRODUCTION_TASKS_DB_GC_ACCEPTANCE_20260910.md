# Production tasks.db 受控清理与 Compact 验收记录

日期：2026-09-10  
Agent：codex-A  
状态：`BLOCKED`（只读前置证据完成，Production GC / VACUUM / Replace 未执行）

## 结论

本轮没有修改 Production 数据，没有执行 `--apply`、`VACUUM INTO`、原子替换或回滚。阻断原因不是 Preview 集合不稳定，而是当前仓库正式 Production maintenance boundary 仍明确为：

- `PRODUCTION_STORAGE_CUTOVER_READY = FALSE`
- `PRODUCTION_MUTATION = NONE`
- `PRODUCTION_CUTOVER_AUTHORIZED = FALSE`
- `FAIL_CLOSED = TRUE`

当前 `config/storage_registry.yaml` 只有 `legacy-dfd356e96ea0`（宁波地铁12号线）的 `devices.db` / `tasks.db` 待建立 rollback owner，状态均为 `PENDING_PRODUCTION_BACKUP`，没有 VERIFIED backup SHA/size/quick check。该边界也不授权本轮全部 9 个局点。不能用一次性脚本绕过正式 owner、current-head gate 和 rollback contract。

## 只读前置证据

- Production DataRoot：`D:\NetConsoleData`
- 目标 `tasks.db`：9 个
- 代码：`main@d146890481b78d3cdbc866b34a279af3650513f1`，工作树 clean
- Writer：精确进程检查 `0`；NetConsole scheduled task `0`
- SQLite sidecars：9 个 `-wal` 均为 0 bytes；`-shm` 均为 32768 bytes；未手工删除任何 sidecar
- Fresh baseline：总文件大小 `402067456` bytes；freelist `655360` bytes；quick check/FK check 全部通过
- Fresh Preview：`candidate=7207`、`safe=6402`、`protected=805`、`unknown=0`
- Safe 集合 live recheck：`6402/6402` 通过
- Preview SHA-256：`d50e7a5b97a3b72d5d654268a57a49af8c27983d05ed5b5fc49dacd6a5224779`
- Safe set SHA-256：`bafe15f9ed6be5a4cb1afff15158b2c5bcea033bbdecec3bb926f4bde9d80bcd`
- 预估 safe logical payload：`141864358` bytes；仅为 Preview 估计，不是物理释放量

证据目录：

`D:\study\NetConsole-Workspace\diagnostic\production-task-gc-20260910-152240`

包含：`PRODUCTION_TASKS_DB_BASELINE.json`、`TASK_RETIREMENT_PREVIEW_BEFORE_APPLY.json`、`PROTECTED_TASK_REASON_PROFILE_BEFORE.json`、`TASK_RETIREMENT_APPLY_MANIFEST.json`、`LOG_AUTHORITY_AND_ARTIFACT_SAMPLE_BEFORE.json`、`PRODUCTION_MAINTENANCE_BLOCKER.json`。

## Apply Manifest 与保护分类

Apply Manifest 已锁定 Preview revision 和 safe set，但标记为 `NOT_EXECUTED`，并记录：`production-maintenance-boundary-not-authorized`、`verified-rollback-owner-missing`。没有因为 protected 数量而放宽保护；原因允许重叠，`UNKNOWN=0`。

5 个 safe task 样本均无 Artifact manifest 命中、无 runtime Log Authority 命中；长期日志 authority 仍记录为 `runtime/logs/app.log` 及轮转文件，由 AppLogger / Log Center 负责，`task_events` 不被当作长期日志 authority。protected 样本按可用保护原因保留。

## 状态矩阵

| Gate | 状态 | 说明 |
|---|---|---|
| `PRODUCTION_WRITERS_STOPPED` | PASS | 精确扫描无 writer，scheduled task=0 |
| `PRE_GC_DB_INTEGRITY` | PASS | 9/9 quick check、FK check 通过 |
| `PRE_GC_PREVIEW` | PASS | fresh preview 完成 |
| `UNKNOWN_CANDIDATES` | 0 | UNKNOWN 未纳入 safe |
| `RECOVERY_COPY` | NOT_RUN | Apply boundary 在 recovery copy 前已阻断 |
| `RECOVERY_COPY_VALID` | NOT_RUN | 同上 |
| `PRODUCTION_GC` | NOT_RUN | 未执行 Production `--apply` |
| `GC_ATOMICITY` | NOT_RUN | 未发生删除事务 |
| `POST_GC_DB_INTEGRITY` | NOT_RUN | 无 GC 后库 |
| `LOG_CENTER_AFTER_GC` | NOT_RUN | 未 GC |
| `ARTIFACT_AFTER_GC` | NOT_RUN | 未 GC |
| `ONLINE_MR_AFTER_GC` | NOT_RUN | 未 GC |
| `GROUND_AFTER_GC` | NOT_RUN | 未 GC |
| `BUSINESS_DATA_AFTER_GC` | NOT_RUN | 未 GC |
| `VACUUM_INTO` | NOT_RUN | 未生成 candidate |
| `CANDIDATE_INTEGRITY` | NOT_RUN | 未生成 candidate |
| `CANDIDATE_QUERY_PARITY` | NOT_RUN | 未生成 candidate |
| `PRODUCTION_REPLACE` | NOT_RUN | 未替换正式库 |
| `POST_REPLACE_DB_INTEGRITY` | NOT_RUN | 未替换正式库 |
| `PRODUCTION_GUI_SMOKE` | NOT_RUN | 不在未授权变更后启动真实 Production GUI |
| `PRODUCTION_RESTART_AFTER_GC` | NOT_RUN | 未发生 GC |
| `TOTAL_TASKS_DB_BYTES_BEFORE` | `402067456` | fresh baseline |
| `TOTAL_TASKS_DB_BYTES_AFTER` | NOT_RUN | 未发生 compact |
| `PHYSICAL_RECLAIMED_BYTES` | NOT RUN | 不能把 logical payload 当磁盘释放 |
| `PHYSICAL_RECLAIMED_MIB` | NOT RUN | 同上 |
| `PHYSICAL_RECLAIMED_PERCENT` | NOT RUN | 同上 |
| `ROLLBACK_EXECUTED` | NO | 未发生 replace，无需 rollback |
| `RECOVERY_COPY_RETENTION` | N/A | 未创建 recovery copy |
| `PRODUCTION_TASKS_DB_MAINTENANCE` | `BLOCKED` | 正式 Production boundary 缺 VERIFIED owner/授权 |

## 后续解除条件

需要由 Production owner 先建立本轮精确目标的 rollback authority（每个 target 的 backup、SHA、size、quick check、revision、owner 和保留策略），生成与当前 implementation HEAD 绑定的 production gate evidence，并使正式 maintenance manifest 进入 `EXECUTABLE`。解除后必须重新建立 baseline、Preview、保护样本和 safe-set digest；本记录中的只读数字不能直接复用。

本轮没有产品代码、schema、版本、安装包、tag、业务数据、日志、Artifact、MESH、Online MR、Ground 或设备数据变更。
