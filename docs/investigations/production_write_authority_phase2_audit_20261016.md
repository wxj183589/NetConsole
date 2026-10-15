# PR #78 生产写入与回滚 Authority：Phase 2 只读安全审计

## 审计结论

| 项目 | 结果 |
| --- | --- |
| 审计日期 | 2026-10-16（Asia/Shanghai） |
| 审计分支 | `codex-A/phase2-production-write-authority-audit-20261016` |
| 审计基线 | `main` / `5b65713751324d3cfbf3adc7e5aa9a4ec48c1191` |
| 被审查 PR | [PR #78](https://github.com/wxj183589/NetConsole/pull/78) |
| PR #78 当前 head | `259d235b151d0c6d25a65bab13002fa84c235404` |
| PR #78 与当前 main 的共同基线 | `8b2a1fc933f44146eda847f7bf2114425e4ba59b` |
| Diff 规模 | 31 files changed，`+3485 / -127` |
| 审计类型 | 代码、Diff、测试和文档的只读审计 |
| 产品代码变更 | 无 |
| 审计结论 | 未确认 P0/P1；存在需要 Phase 2 单独验证和修复的 P2 风险；不建议直接合并 PR #78 |

本审计不批准生产切换，也不等同于数据库升级、回滚或基础资料回滚的执行授权。PR #84 已在当前 main 中以合并提交 `5b657137` 存在；本分支没有移植 PR #78 或 PR #83 的产品代码。

## 范围和历史审查状态

PR #78 的主题为数据库升级、备份验证、恢复/删除及 AC 扩展和基础资料回滚 Authority。审查覆盖：

- `src/netconsole/services/database_upgrade/authority.py`
- `src/netconsole/backend/api/database_upgrade_router.py`
- `src/netconsole/services/job_center/handlers/database_jobs.py`
- `src/netconsole/services/database_upgrade/management_service.py`
- `src/netconsole/services/database_upgrade/sqlite_consistency.py`
- `src/netconsole/services/database_upgrade/history.py`
- `src/netconsole/services/production_rollback_authority.py`
- `src/netconsole/services/rail_transit/base_data_import_service.py`
- `src/netconsole/application/rail_transit/base_data_application_service.py`
- `apps/desktop_renderer/src/api/databaseUpgrades.ts`
- `apps/desktop_renderer/src/api/acWebParity.ts`
- 相关测试、配置和生产写入口清单文档。

GitHub 上 PR #78 的历史 P1/P2 review threads 均已被关闭；其中一部分同时标记为 outdated。已关闭意见包括 WAL-aware identity、备份变化验证、目标陈旧性、旧归档 Authority、批量逐项陈旧处理、临时目录和 reparse/junction、并发锁、非生产目标校验、批量 catalog revision、HTTP 重型 identity scan、无效备份删除、生产写 Gate、路径穿越、按 profile 物化、归档候选冻结、target registry revision 以及取消传播等。

这些意见已经关闭不代表 PR #78 获得本阶段合并批准。本审计关注的是关闭意见之后仍需由独立测试或威胁模型确认的残余边界。

## 生产写入入口矩阵

| 能力 | 主要入口/实现 | 现有保护 | 本审计判断 |
| --- | --- | --- | --- |
| 数据库升级 | `database_upgrade_router.py`、`DatabaseUpgradeAuthority`、`management_service.py` | feature gate、操作级 capability token、生产写开关、站点绑定、worker 再授权 | 结构完整；需继续验证并发和陈旧输入边界 |
| 数据库备份 | `database_upgrade_router.py`、`management_service.py`、`sqlite_consistency.py` | SQLite Backup API、WAL 处理、manifest/identity、维护锁和资源锁 | 主要路径有保护；延迟物化的同 stat 替换风险仍需测试 |
| 备份验证 | `DatabaseBackupStore.validate()` | 生产写 Gate，验证结果和 manifest 持久化 | 已覆盖主要生产写边界；需保持验证文件写入与操作授权一致 |
| 恢复/删除备份 | `management_service.py`、backup authority | 显式确认、备份 identity、站点作用域、保护中的备份拒绝删除、批量逐项授权 | 未发现已确认的 P0/P1；建议补充最终 mutation 前复核测试 |
| 旧归档整理/恢复 | `history.py`、database upgrade authority | 延迟发现、路径包含校验、candidate freeze、SHA/size/mtime 复核 | 最终 organizer/recovery 操作的 reparse/TOCTOU 复核仍需加强 |
| AC 扩展回滚 | `production_rollback_authority.py`、AC Web parity 路径 | `AC_EXTENSION_ROLLBACK_AUTHORIZED`、生产写开关、站点 allowlist、显式确认 | Authority 边界存在；token 不是认证凭据，需明确本地威胁模型 |
| 基础资料回滚 | `base_data_import_service.py`、`ProductionRollbackAuthority` | `BASE_DATA_ROLLBACK_AUTHORIZED`、revision/hash-after 冲突校验、AP Identity rebuild、维护锁 | 回滚路径受保护；直接编辑/清空路径与回滚锁的并发关系需补测 |

WPS 云端同步、设备配置下发、MESH 重新导入和正式生产切换不属于本 PR 审计的执行范围。本次未执行这些操作。

## Authority 和 worker 执行链

### API 层

API 侧先检查 feature gate，再按操作类型检查 capability token、生产写开关和站点作用域；需要改变生产状态的操作还要求显式确认。批量升级、批量备份和批量删除均保留逐项处理语义，单个 profile 或 backup 变陈旧时不应把整批重新解释为当前授权。

Renderer 中的 `DATABASE_UPGRADE_AUTHORIZED`、`DATABASE_BACKUP_RESTORE_AUTHORIZED`、`AC_EXTENSION_ROLLBACK_AUTHORIZED` 等值是 capability label，不是秘密，也不应被当作用户认证。真正的生产保护仍依赖 Backend 进程的生产写开关、canonical scope、feature gate 和显式确认。

### Job Center worker

worker 不直接信任提交时的路径或 UI 状态，而是使用 Authority snapshot/resource key，在执行前重新物化和验证 deferred profile、backup 或 archive candidate。批量操作在每个 profile/item 的 mutation 前再次授权；数据库维护锁、站点资源锁和 MESH 相关锁用于串行化关键数据库操作。取消回调沿 worker 链传递，不应在取消后继续进入 mutation。

### 站点隔离

生产站点路径通过 canonical site registry/allowlist 和 `resolve_mesh_production_scope` 解析；PathResolver 对目标、backup、manifest 和临时目录执行包含关系检查。生产和非生产路径有不同的授权要求；reparse/symlink 检查用于阻止路径解析逃逸。

### 备份和恢复

SQLite 一致性路径包含 WAL 处理、SQLite Backup API、`query_only` 临时连接、隔离 temp root、逻辑 identity/hash、manifest 验证、shadow switch/rollback 和 safety backup。恢复和删除会检查 backup identity、保护状态、目标作用域及当前 revision，不能仅以文件名或 UI 选项决定目标。

## 仍需确认的残余风险

### P0：无已确认项

本次没有发现能够直接绕过生产写 Gate、任意站点 scope 或设备配置边界的已确认 P0。

### P1：无已确认项

PR #78 的历史 P1/P2 review threads 已关闭，当前代码审阅没有足够证据将下列残余边界升级为已确认 P1。若后续威胁模型证明本地不可信进程能够稳定取得 capability token，或 reparse/TOCTOU 路径可被稳定利用，应重新评估为 P1；在证据出现前不作阻断级结论。

### P2：需要 Phase 2 单独验证的项目

1. **直接基础资料写入没有明确复用回滚维护锁。**
   `base_data_application_service.py` 的 `clear_all()`、`save_changes()` 是正常编辑/清空写入口；PR #78 对 `base_data_import_service.py` 的 `apply_merge_plan()` 和 `rollback_import()` 增加了共享 `database_maintenance_lock`，但直接编辑/清空路径没有显示地进入同一跨进程锁。SQLite transaction 和 optimistic revision 提供部分保护，但缺少“直接写入与回滚并发”的证明测试。建议先补并发测试，再决定是否扩大共享锁范围。

2. **延迟备份 Authority 的同 size/mtime 替换窗口。**
   提交阶段记录 backup/manifest 的 size、mtime 和声明 identity，worker 阶段再物化并计算完整 identity。若攻击者能在窗口内替换内容，同时保持初始 stat 和声明字段不变，理论上仍存在绑定强度不足的可能。当前未证明可利用，建议在提交阶段绑定 manifest SHA，或在最终 mutation 前执行不可跳过的二次确认。

3. **旧归档 organizer/recovery 的最终 reparse/TOCTOU 复核。**
   `history.py` 对根路径有 symlink 检查，Authority 对候选路径做包含关系校验；但 organizer/recovery 的最终写入点仍建议再次执行 reparse-safe resolution 和 parent identity 校验。当前不是已确认路径穿越，但需要独立回归覆盖目录在检查后被替换的情况。

4. **客户端 capability label 的威胁模型边界。**
   Renderer 中的 literal token 不能作为认证或授权事实源。当前安全性依赖本机受管 Electron、回环 Backend、生产写环境开关和 Backend Authority。需要在安全设计中明确：本地恶意进程、调试端口暴露、Renderer 注入和同机 API 重放不属于哪些信任边界；如果需要抵御这些威胁，应改为由受管 Main/Backend 签发短期、操作绑定的凭据，而不是把字符串 token 误称为 secret。

5. **正式根的历史 AC Web 计划缓存存在陈旧 `EXECUTING` 状态。**
   本次只读检查发现 21 个历史 `ac-plan-*.json` 仍标记 `EXECUTING`，最新文件修改于 2026-10-15；没有发现相应的采集/设备 worker 进程。本次不清空任务中心、不修改缓存，需由人工在 GUI 任务中心确认这些记录是可恢复任务还是陈旧状态。该项是现场运行状态风险，不作为 PR #78 代码缺陷结论。

## 最小修复和验证顺序

1. 先新增并发测试：直接基础资料编辑/清空、导入回滚、AC 扩展回滚、数据库升级/备份同时发生时，验证维护锁、revision/hash-after 和失败后的可恢复状态。
2. 增加 deferred backup 的 adversarial fixture：保持 size/mtime 的替换、manifest 改写、WAL 变化和跨站点候选，要求最终 mutation 前全部拒绝或重新确认。
3. 为 archive organizer/recovery 增加 Windows reparse/junction 和检查后替换测试，最终写入前再次解析并确认 parent identity。
4. 在安全文档中把客户端 literal capability label 明确为非认证信息，补充本机攻击面和 loopback 端口暴露假设。
5. 以上测试和设计结论稳定后，再以独立 Phase 2 PR 评审最小代码修复；不要把完整 PR #78 直接移植到 main。

## 不在本阶段移植的内容

本阶段不移植以下代码或行为：

- 数据库 schema/data migration、生产数据库升级和 rollback 执行；
- AC 扩展回滚、基础资料回滚及其生产切换授权；
- 生产 tasks.db GC、DELETE、VACUUM、shadow replace 或 restore；
- WPS 云端同步、设备配置下发、MESH 重新导入；
- PR #83 的列车在线站点安全回退逻辑；
- 新的全局 Adapter/统一数据来源框架。

## 自动化和数据影响

当前 main 的合并后证据：

- GitHub `engineering-hardening` run `38762495684`：8/8 jobs SUCCESS。
- Python：5133 passed，2 skipped；baseline-aware 新失败数为 0，baseline debt 为 0。
- Renderer：1310 passed；Electron：303 passed。
- Storage targeted gate：239 passed，`production_data_root_used=false`。
- Architecture：12/12 guards passed；Main contract：12 passed、3 warnings；Docs/path：22 passed；Ruff 和 `git diff --check` 通过。
- 本地 full gate 唯一失败为仓库既有 `test-data` 顶层目录触发的 workspace-layout debt；没有删除该目录，也没有把它误报成产品回归。

本审计分支只增加本文件，不修改产品源码、公共 DTO、REST API、数据库 schema 或正式数据。审计期间没有执行生产数据库 UPDATE/DELETE/VACUUM/迁移/重建，没有执行设备配置，没有执行 WPS 远端写入。

```ini
AUDIT_ONLY=YES
PRODUCTION_DATA_MUTATION=NO
DEVICE_CONFIG_MUTATION=NO
WPS_REMOTE_WRITE=NO
MAIN_MERGE=NO
```

## 后续建议

PR #78 不建议在当前状态直接合并。建议先由 Phase 2 负责人确认上述 P2 是否属于本产品威胁模型，再以测试先行、最小修复、独立 PR 的方式处理。PR #84 已经合并并完成合并后自动回归；本审计不改变其状态，也不要求回滚。
