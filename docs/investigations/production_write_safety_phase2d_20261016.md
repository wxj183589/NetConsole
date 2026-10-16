# NetConsole Phase 2-D：生产写入安全审计与最小修复

## 结论

审计基线为 `github/main` / `c22323d683f92873fa4e9ebb00854ee0f9a434fb`。PR #78 仍未合并，本次没有移植其 31 个文件，也没有修改正式数据根 `D:\NetConsoleData`。

本次确认并修复三项当前 main 缺口：

1. 基础资料直接编辑、清空与导入/回滚没有共用同一局点维护锁。
2. 历史 MESH 归档在解析根路径后才检查 symlink，根目录 symlink 可以把扫描范围带到允许根目录外。
3. 数据库升级、备份、恢复、删除和历史归档等生产写操作的 API/Worker 路径缺少统一的后端生产写 Gate 复核。

未确认当前 main 存在 PR #78 所描述的 deferred backup authority 缺陷：当前 main 没有该 deferred authority 入口；现有实际备份中心使用 SQLite Backup API、manifest SHA-256、size 和恢复前校验。相同 size/mtime 的内容替换在隔离测试中被内容哈希拒绝。

没有发现 P0/P1 级别问题。生产写 Gate 修复改变的是生产环境下的拒绝边界：未显式以 `--allow-production-write` 启动时，数据库维护任务不会入队或执行；测试/开发数据根行为保持兼容。

## 当前 main 与 PR #78 对照

| 保护能力 | 当前 main 基线 | PR #78 未合并设计 | 本分支判断 |
| --- | --- | --- | --- |
| 基础资料维护锁 | SQLite `BEGIN IMMEDIATE` 和 revision/hash；直接编辑/清空未复用数据库维护锁，导入/回滚也未复用 | 导入/回滚增加 `database_maintenance_lock`，直接编辑/清空仍不是完整覆盖 | 已在直接编辑、清空、导入、回滚公共入口补同一局点锁 |
| Backup Identity | `DatabaseBackupStore` manifest 保存 SHA-256、size、SQLite 校验；`validate()` 复核实际内容 | 新增 DatabaseUpgradeAuthority、deferred identity 和 worker 二次授权 | 当前实际路径已具备内容绑定；未移植 PR #78 的 deferred authority |
| 归档路径最终复核 | 根路径 `resolve()` 后检查 symlink；移动后复核 SHA/size | 增加候选 authority 快照和绑定校验 | 修复原始根 reparse 拒绝、候选/锁内 resolved containment；仍保留移动前后文件句柄级绑定的后续设计风险 |
| Capability Token / 生产写权限 | Feature Gate、Electron session、显式确认；数据库维护路径此前没有统一生产写 Gate | 操作 token、canonical site scope、worker 二次 authority | 复用现有后端生产写 Gate，在 API 入队和管理服务/Coordinator 执行时双重检查；literal token 仍不被当作认证凭据 |

PR #78 当前 head 为 `259d235b151d0c6d25a65bab13002fa84c235404`，状态为 OPEN、未合并；其 31 文件差异仅作为对照，没有 cherry-pick 或整体移植。

## P2-1：基础资料维护锁

### 原因和调用链

原调用链如下：

```text
BaseData API
  -> RailTransitBaseDataApplicationService.save_changes / clear_all
  -> RailTransitBaseDataRepository BEGIN IMMEDIATE
  -> AP Identity ensure_index（提交后）/ checkpoint

AC Web / Base Data Import API
  -> RailTransitBaseDataImportService.apply_merge_plan / rollback_import
  -> backup、audit、partial transaction、AP Identity rebuild
```

Repository 的 SQLite 事务和 revision/hash 冲突可以阻止一部分陈旧写入，但不能把备份、审计、提交后 AP Identity rebuild 和 checkpoint 组成同一局点维护临界区。此前直接编辑/清空也没有进入 `database_maintenance_lock`。

### 修复

复用现有 `database_maintenance_lock(paths, site_database_maintenance_key(site_id))`：

- `save_changes()` 和 `clear_all()` 在进入校验/写入/Identity refresh/checkpoint 前获取局点锁。
- `apply_merge_plan()` 和 `rollback_import()` 通过 locked helper 获取同一局点锁。
- 不同 `site_id` 使用不同锁键；锁仍有界等待，未新增全局锁框架。
- Repository 原有 `BEGIN IMMEDIATE`、revision/hash-after、失败回滚和 AP Identity 逻辑保持不变。

隔离回归 `test_base_data_save_and_clear_share_site_maintenance_lock`、`test_base_data_import_and_rollback_share_site_maintenance_lock` 验证持锁期间操作不会进入写路径；释放后正常完成。当前补丁没有执行正式基础资料写入、清空或回滚。

## P2-2：deferred backup 的同 size/mtime 替换

当前 main 的实际数据库备份路径为：

```text
DatabaseUpgradeManagementService
  -> DatabaseBackupStore.create
  -> SQLite Backup API
  -> validate_sqlite
  -> manifest database_sha256/source_revision/database_size
  -> restore/delete 前再次 validate
```

当前 main 没有 PR #78 的 `DatabaseUpgradeAuthority` deferred candidate/worker identity 机制，因此不能把 PR #78 的 deferred 假设误报成 main 的运行漏洞。

隔离测试先创建合法备份，再把备份数据库内容替换为相同大小并恢复原 mtime。`DatabaseBackupStore.validate()` 返回：`size_matches=True`、`sha256_matches=False`、`INVALID_DATABASE`。因此“只依赖 size/mtime”的现象未在当前实际 BackupStore 路径成立。

后续风险：若未来引入“提交时预览、Worker 延迟物化”的备份 authority，必须增加预提交 identity、Worker 执行前复核和最终 mutation 前复核；本次不引入该完整框架。

## P2-3：历史归档 reparse/TOCTOU

### 已确认缺陷

原代码先执行：

```python
root = self.paths.site_mesh_root(site_id).resolve()
```

再检查 `root.is_symlink()`。根路径如果本身是 symlink/reparse point，`resolve()` 后检查的是外部目标，无法拒绝越界根。隔离测试在临时目录创建指向外部目录的 symlink，原行为发现并移动外部归档，`found_count=1`，因此缺陷成立。

### 修复与边界

- 先检查未经解析的 `site_mesh_root`，拒绝 symlink、junction 和 Windows reparse attribute。
- 候选扫描后检查 resolved candidate 是否仍在 resolved root 内。
- 获取维护锁后重新读取根路径并再次检查 reparse、目录和 containment，再进入移动。
- 保留原有移动后 SQLite、size 和 SHA-256 复核；内容被替换时结果为 `INVALID_DATABASE`，不把新内容伪装为原候选。

隔离测试覆盖：根 symlink 越界、嵌套 symlink、移动前内容替换、正常有效/零字节归档及恢复已有回归。仍有一个设计边界：普通路径 API 在最终检查与 `shutil.move` 之间不能提供 Windows 文件句柄级 no-follow 原子绑定；若未来要抵御恶意同机进程在该极窄窗口反复替换父目录，应单独设计 handle-based move，不在本次扩大。

## P2-4：Capability Token 信任边界

### 现状

- Electron 到 Backend 的 WebHost session token 由 Middleware 使用 constant-time compare 校验。
- Feature Gate 负责功能暴露，不等于生产写认证。
- `SITE_*_AUTHORIZED`、MESH operation label 等 literal capability label 不是秘密，也不能抵御已取得本机回环访问能力的恶意进程。
- 当前 main 数据库升级路由此前仅由 Feature Gate、显式确认和任务入队控制，管理服务/Coordinator 没有统一复核生产写环境开关。

### 最小修复

复用既有 `require_data_root_write_allowed()` 和 `NETCONSOLE_ALLOW_PRODUCTION_WRITE`：

- API 入队前对 upgrade、batch backup、archive organize、backup validate/restore/delete 执行后端 Gate。
- `DatabaseUpgradeManagementService` 在对应 Worker/Service 入口再次复核。
- `DatabaseUpgradeCoordinator` 在实际升级 mutation 前再次复核。
- 测试/开发根保持可用；生产根必须由受控进程显式以 `--allow-production-write` 启动。

没有新增 Token Framework、OAuth、Electron IPC 大改或公共请求 DTO 字段。当前安全模型仍不承诺抵御已取得本机高权限或调试端口的恶意进程；如要覆盖该威胁，应后续设计短期、操作绑定、Backend 签发的凭据。

## 隔离复现和测试证据

新增 `tests/test_production_write_safety_phase2d.py`，共 7 项：

- 同一局点维护锁覆盖直接保存、清空、导入和回滚。
- 备份内容在 size/mtime 不变时仍被 SHA-256 拒绝。
- 归档内容替换在移动后被标记为无效。
- 嵌套 symlink 和 MESH 根 reparse point 不得越界。
- Production 根未开启进程写 Gate 时拒绝数据库维护。

正式数据根、正式备份、任务中心、计划文件和真实设备均未参与测试。

## 性能、兼容性和数据影响

- 局点维护锁只包住已有的业务校验、事务、Identity refresh 和 checkpoint，不新增数据库扫描或 N+1 查询；不同局点不共享业务锁键。
- 备份哈希行为沿用现有 BackupStore；本次没有在普通 GET 中增加全量 Hash。
- 未修改公共 DTO、REST 字段、数据库 Schema、Renderer、Electron Main/Preload 或 Excel 列。
- 归档检查增加少量路径解析与 reparse 检查，仅作用于归档 Worker。
- 正式数据没有 UPDATE、DELETE、VACUUM、迁移、恢复、回滚、任务清理或 WPS/设备写入。

## 当前验收字段

```text
PHASE2D_BASELINE=github/main@c22323d683f92873fa4e9ebb00854ee0f9a434fb
MAIN_HEAD=c22323d683f92873fa4e9ebb00854ee0f9a434fb
PR78_MERGED=NO

BASE_DATA_LOCK_RESULT=CONFIRMED_DEFECT_FIXED
BACKUP_IDENTITY_RESULT=NOT_APPLICABLE_FOR_DEFERRED_AUTHORITY; CURRENT_BACKUP_HASH_PASS
ARCHIVE_TOCTOU_RESULT=ROOT_REPARSE_CONFIRMED_AND_FIXED; CONTENT_RACE_REJECTED
CAPABILITY_TOKEN_RESULT=PRODUCTION_GATE_DEFENSE_GAP_FIXED; LITERAL_LABEL_NOT_AUTH

CONFIRMED_DEFECTS=P2-1 direct base-data paths lacked shared site lock; P2-3 resolved MESH root symlink escaped boundary; P2-4 database maintenance lacked unified backend production write gate
DEFENSE_GAPS=literal capability labels are not authentication; final archive move has no handle-bound no-follow atomic primitive
DESIGN_RISKS=future deferred backup needs pre-submit and worker identity binding; stronger same-host threat model needs short-lived backend-signed operation credentials
NOT_REPRODUCED=multi-process adversarial parent replacement and Windows junction replacement were not claimed as reproduced; no P0/P1 evidence
NOT_APPLICABLE=PR78 DatabaseUpgradeAuthority/deferred candidate flow is not in current main; Renderer/Electron UI did not change

PYTHON_TESTS=Phase2D 7 passed; affected regression 105 passed, 2 warnings; full clean-venv run 5172 passed, 2 skipped, 33 warnings, 1 unrelated release-system failure; release-system file isolated rerun 68 passed
RENDERER_TESTS=NOT_RUN; no Renderer files changed
ELECTRON_TESTS=NOT_RUN; no Electron files changed
ARCHITECTURE_GATE=PASS; Architecture Green Gates 8/8; storage targeted 239 passed; architecture baseline new failures 0; Ruff baseline new failures 0; diff check PASS
MAIN_CONTRACT=PASS; 12 passed, 3 warnings
BASELINE_NEW_FAILURES=1 unrelated tests/test_release_system.py::test_clean_build_runtime_subset_copies_only_imported_modules_and_assets in full run; isolated tests/test_release_system.py 68 passed; no Phase2-D changed-path failure

PRODUCT_CODE_CHANGED=YES
PR_CREATED=YES; PR #89 https://github.com/wxj183589/NetConsole/pull/89; head=8080ebae
MAIN_MERGE=NO
```

## 安全边界与最终状态

```text
PUBLISH=NO
TAG_CREATED=NO
RELEASE_CREATED=NO
INSTALLER_BUILD=NO
MAIN_MERGE=NO
PR78_MERGE=NO
PR83_MERGE=NO
PRODUCTION_DATA_MUTATION=NO
PRODUCTION_DATABASE_UPGRADE=NO
PRODUCTION_DATABASE_RESTORE=NO
PRODUCTION_BACKUP_DELETE=NO
PRODUCTION_BASE_DATA_ROLLBACK=NO
PRODUCTION_AC_EXTENSION_ROLLBACK=NO
PRODUCTION_TASK_CLEANUP=NO
PRODUCTION_RECONCILIATION=NO
AC_PLAN_FILE_MUTATION=NO
DEVICE_CONFIG_MUTATION=NO
WPS_REMOTE_WRITE=NO
```

Renderer/Electron 未改动，因此未重复运行前端测试、类型检查或构建；本次产品变更全部位于 Backend/Service/History 和架构登记。全量 Python 的唯一失败不涉及变更文件，单文件复跑通过，需在后续完整 Gate/CI 环境中继续观察其顺序相关性。

## 后续审查建议

建议审查 PR #89 的 P2-1/P2-3/P2-4 最小修复和隔离测试。PR #78、PR #83 不属于本次移植范围；本分支不自动合并 main、不发布、不打 Tag、不构建安装包。
