# Production Database Maintenance

NetConsole 的生产数据库维护能力是独立安全边界，不复用或放宽
`DevelopmentDatabaseCompactService` 的 `D:\study` 限制。实现位于
`src/netconsole/services/production_database_maintenance.py`，命令入口位于
`scripts/maintenance/production_database_maintenance.py`。

## 当前授权状态

- `PRODUCTION_STORAGE_CUTOVER_READY = FALSE`
- `PRODUCTION_MUTATION = NONE`
- `FAIL_CLOSED = TRUE`

代码能力已实现，但当前 production rollback owner 仍为
`PENDING_PRODUCTION_BACKUP`，没有 VERIFIED production rollback set，也没有生产
cutover 授权。不得把 capability 存在、隔离 rehearsal 通过或 manifest 生成解释为
已执行生产迁移。

## 固定作用域

第一阶段只允许：

- Site ID：`legacy-dfd356e96ea0`
- SiteRegistry display name：`宁波地铁12号线`
- 数据库：`devices.db`、`tasks.db`

路径必须由当前 DataRoot 的 SiteRegistry 精确解析；不能传任意局点路径、目录或
SQLite 文件。符号链接、越界路径、未登记 Site、显示名不一致和额外数据库一律
失败关闭。

## Manifest 契约

destructive manifest 必须由当前隔离 snapshot 生成并标记 immutable，至少绑定：

- `site_id`
- `database_identity`
- `source_size`
- `source_sha256`
- `schema_fingerprint`
- `source_revision`
- `row_identity`
- `expected_count`
- `candidate_identity`（candidate 的 size、SHA-256、schema fingerprint 与逐表行数）
- `plan_digest`
- `generated_git_head`
- `manifest_digest`
- `execution_status` 与 `blocking_prerequisites`

preflight 与进入维护锁后的第二次 source identity 校验都必须完全匹配。旧 source、
SHA、revision、row identity、plan digest 或 Git HEAD 任一不同均为
`STALE_SOURCE` / `STALE_PLAN`，不可执行。

maintenance CLI 当前只生成 `execution_status = NOT_EXECUTABLE` 的 preparation
manifest，并默认登记 rollback owner、production backup、writer quiescence 和 cutover
authorization 阻塞项。即使 source/candidate identity 与全部自动化测试一致，preflight
也会拒绝该 manifest；只有在真实生产前置条件均已建立后，由受控授权流程生成无阻塞项
的 `EXECUTABLE` manifest，才可能进入后续 gate。

manifest 和命令输出文件均为 create-only；既有路径或 `--output` 与 `--manifest`
相同一律在任何操作前拒绝。production preflight 在确认不存在非空 WAL 后使用
`mode=ro&immutable=1`，不得因读取 source、candidate 或 rollback backup 创建或更新
WAL/SHM sidecar。

## Rollback owner

`config/storage_registry.yaml` 的 `production_rollback_owners` 是正式 owner 注册表。
owner 必须包含 backup set、Site、operation、database、source identity/SHA/revision、
创建与验证时间、quick check、schema fingerprint、backup SHA/size/canonical relative
path、observation 和 retire state。

只有同时满足以下状态才是可用 rollback authority：

- `quick_check = ok`
- `observation_state = VERIFIED`
- `rollback_required = true`
- `retire_state = PROTECT`
- backup/source/revision/verified time 均非空且格式有效
- backup 必须已存在于
  `files/backups/production-maintenance/<backup_set_id>/database.sqlite`，并匹配登记的
  SHA-256、size 与 schema fingerprint

当前登记项是具体 Site/数据库的待建立槽位，不是 VERIFIED backup。生产切换前必须
用 SQLite Online Backup API 创建并验证 exact backup set，再更新 owner；不能把
历史 `files/backups/**` 文件名推断成 rollback authority。

## 执行门

mutation 入口必须同时具备：

1. 显式 `mode=production`。
2. 精确授权令牌。
3. Site 与 database allowlist 通过。
4. SiteRegistry identity 通过。
5. maintenance lock 已获取。
6. runtime/writer quiescence 已确认。
7. VERIFIED rollback owner 已登记。
8. immutable manifest 与当前 Git HEAD 匹配。
9. source identity 二次校验通过。
10. operation journal 可持久化。
11. 所有 production gate 为 PASS。
12. replacement 后 restart 与 functional gate 为 PASS。

restart 或 functional gate 失败时必须使用已验证 rollback authority 恢复，并保留
失败数据库和 journal；不得以清理失败现场代替恢复。

## Backup 生命周期

生产 cutover 前不得退役 `files/backups/**`。顺序固定为：cutover、restart、功能验证、
observation、分类、精确退役。分类仅允许
`ACTIVE_ROLLBACK_REQUIRED`、`OBSERVATION_REQUIRED`、`SUPERSEDED`、
`EXACT_DUPLICATE`、`EXPIRED_ROLLBACK`、`UNKNOWN`；`UNKNOWN = PROTECT`。

开发/测试使用唯一 `D:\study\test-data\NetConsole\<run-id>`，不得用真实生产根验证
DELETE、DROP、VACUUM、source retirement、database replacement 或 backup retirement。
