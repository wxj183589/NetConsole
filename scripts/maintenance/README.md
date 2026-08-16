# maintenance

## 用途

本目录保存可审计、可重复运行的本机维护脚本，包括历史运行数据迁移、测试垃圾清理、构建产物回收和专项诊断。

## 边界

- 清理、迁移和修复脚本默认只读或只生成计划，必须显式传入 `--apply`、`--repair` 等对应变更参数才能改动文件。
- 所有可删除路径必须使用固定白名单、解析绝对路径并拒绝链接越界。
- 不得在本目录实现设备业务、数据库 Repository 或发布入口。

## 主要入口

- `migrate_legacy_runtime_data.py`：无覆盖迁移仓库历史运行数据。
- `clean_test_artifacts.py`：清理明确白名单内的历史测试临时项。
- `clean_generated_artifacts.py`：回收明确白名单内、可重新生成的构建产物；`build-temporary` 只处理 `dist/_build`，默认 dry-run，发布目录和 Electron/Agent 输出不在该目标内。
- `check_desktop_bootstrap.py`：只读检查 Electron bootstrap；`--repair` 先备份并原子修复临时/失效的数据根和局点引用，不移动业务数据。
- `audit_sites.py`：只读扫描局点文件、SQLite 完整性、业务记录和 Registry/bootstrap 引用，并把审计 manifest 写入当前数据根；不移动或删除局点。
- `rebuild_mesh_parsed_data.py`：在 schema 变更后从受保护 raw 日志重建 MESH 派生 SQLite；默认仅输出计划，`--apply` 必须在 NetConsole 完全退出后执行。
- `remap_mesh_identity.py`：扫描健康的 MESH parsed 来源并规划/执行 identity-only remap；默认 dry-run，只有显式 `--apply` 才逐来源复用 `MeshSourceRebuildService` 写入，经数据库回读验证后才发布 ready。
- `migrate_device_history.py`：显式 inventory/start/pause/resume/status 的 legacy history COPY-only 迁移，以及逐表 cutover/rollback/observation eligibility/delete-plan preview；状态切换必须 `--apply`。精确源删除执行器还必须提供 plan/source/revision 摘要和 `--allow-development-root-only`，且只接受 `D:\study` 隔离副本；生产 `DELETE`、`DROP` 或 `VACUUM` 始终不可用。`--output` 可把单次结果保存为新的 JSON 证据且拒绝覆盖既有文件。
- `validate_history_provenance.py`：默认以 SQLite read-only 连接审计隔离 `devices.db`、History catalog 和全部登记 shard 的 quick/integrity/foreign-key、event/provenance 数量、missing/duplicate source identity、`WITHOUT ROWID` 与 provenance 索引布局；只有同时提供 `--apply-backfill --allow-development-root-only` 才调用幂等 provenance backfill。数据库、History 根和新建 JSON 证据必须解析在 `D:\study` 下，既有输出拒绝覆盖。
- `benchmark_device_history_legacy_migration.py`：只在 `D:\study` 隔离数据上测量迁移吞吐、chunk latency、commit/checkpoint 和 target growth。
- `profile_device_history_storage.py`：只读剖析隔离 legacy/V1 history 的表、payload、envelope、索引和 fragmentation；`--decompose` 的 VACUUM 只作用于 diagnostics scratch。
- `benchmark_device_history_storage_queries.py`：只读比较隔离 V1/V2 月分片的实体、时间范围、跨月和 offset 查询，输出延迟、EXPLAIN plan 与 event ID 一致性摘要。
- `validate_history_migration_server_hdd.py`：只评估已捕获的 migration/host/operational JSON 证据，不打开 source DB、不运行迁移；缺少真实 HDD 或运行态证据时保持 `PENDING`。
- `profile_tasks_db.py`：LIGHT 只读元数据、DEEP 只读隔离副本的 tasks.db 存储剖析。
- `manage_task_result_rollout.py`：读取单个 tasks.db 的安全 rollout 摘要；仅显式 `--apply`、revision CAS 和 reason 可启用或停止未来 dual-write，不提供 verified/ref-only apply。
- `benchmark_tasks_db_governance.py`：在 `D:\study` 隔离库对比 legacy baseline、guarded default、显式 dual-write、future ref-only、100/1,000/10,000 task scale、约 4.5 MB result 和 progress sampling；future 空间差异仅为 potential。
- `benchmark_database_functional_queries.py`：只以 `mode=ro&immutable=1` 比较真实隔离 Before/After 的 Device、FIT-AP、LLDP、History、Task 以及 Site Package 内 MESH/Ground 查询，输出绑定 Git HEAD 的 p50/p95/max、结果数量和语义 SHA-256。
- `collect_functional_consumer_observations.py`：从真实隔离 Site Package、性能和 No-Reinflation 证据生成完整 consumer Before/After manifest；只接受 registered store 与查询语义一致的 canonical digest。
- `build_site_storage_optimization_impact.py`：只读绑定递归 site/global inventory、隔离前后 devices/tasks、最终 History 根和 task result 去重报告，生成可复验的 `netconsole-site-storage-impact-v1`，拒绝手工猜测或不匹配的 baseline 字节。
- `finalize_functional_compatibility.py`：将数据库 Before/After、完整 Site Package、No-Reinflation、性能比较、最终 Storage footprint 以及 TARGETED/FAST/CONSUMER/FULL Gate 绑定到同一 Git HEAD，并强制每个 consumer 的 Before/After query digest 相同；任何缺项或 FAIL 都拒绝生成最终三份功能报告。
- `../quality/run_storage_targeted_gate.py`：在唯一 `D:\study\test-data\NetConsole\<run-id>` 中执行数据库治理定向套件，完成后删除自有测试根并保存绑定 HEAD 的 TARGETED 报告。

局点审计从仓库根运行，默认使用源码开发数据根；`--site-id` 可限制为一个稳定 ID 或目录名，`--output` 可指定 manifest 文件：

```powershell
.\.venv\Scripts\python.exe -m scripts.maintenance.audit_sites
.\.venv\Scripts\python.exe -m scripts.maintenance.audit_sites --site-id demo
.\.venv\Scripts\python.exe -m scripts.maintenance.audit_sites --data-root "D:\NetConsoleData" --output "D:\NetConsoleData\migrations\site-audit.json"
```

历史 MESH 身份恢复默认只读扫描；`--profile` 可限制 Profile，`--source` 必须同时指定 Profile：

```powershell
.\.venv\Scripts\python.exe -m scripts.maintenance.remap_mesh_identity --site <局点> --dry-run
.\.venv\Scripts\python.exe -m scripts.maintenance.remap_mesh_identity --site <局点> --profile <MR Profile> --apply
```

dry-run 不写 parsed DB、raw 或 catalog，并兼容缺少后续可选身份投影列的历史 parsed DB；apply 逐来源执行，现有 Repository 会幂等补齐这些列，单来源失败会记录并继续其他来源。

该命令对局点业务数据只读，但会写审计报告。报告中的 `can_delete` 仍不是单阶段删除授权；正式回收必须经过 Application Service 的 prepare/apply、文件哈希复核和受控回收区。

## 数据与状态

脚本不得把业务数据写回仓库。迁移或清理清单应写入用户指定路径或系统应用数据目录，正式数据必须先校验再回收源文件。

## 测试

- `diagnose_server_hdd.py`：只读采集 Windows Server/HDD 主机、卷容量、Backend PID、devices.db/WAL/SHM、History health 和启动阶段；旧系统性能计数器不可用时返回 `unknown`。
- `validate_phase21_snapshot.py`：仅对用户提供的离线 `devices.db` 副本执行 SQLite Backup API 隔离验证，确认 current-schema fast path 和新 History shard 写入；未提供副本时明确 `NOT_EXECUTED`。

History HDD 证据校验与 Task 结果布局 benchmark 均只向 `D:\study` 写报告：

```powershell
$env:PYTHONPATH = "$PWD\src;$PWD"
.\.venv\Scripts\python.exe -m scripts.maintenance.validate_history_migration_server_hdd `
  --migration-benchmark "<migration-report.json>" `
  --host-diagnostic "<host-diagnostic.json>" `
  --operational-observation "<observation.json>" `
  --output-dir "D:\study\diagnostic\NetConsole\device-history-cutover\<run-id>"

.\.venv\Scripts\python.exe -m scripts.maintenance.benchmark_tasks_db_governance `
  --output-dir "D:\study\diagnostic\NetConsole\tasks-db-governance\<run-id>"
```

清理测试只在 `D:\study\test-data\NetConsole\<run-id>` 构造目标，禁止对真实 `D:\NetConsoleData`、历史 `data/`、`.local/` 或 LocalAppData 目录做破坏性测试。

## 修改规则

新增可写动作时必须补充白名单、路径逃逸/链接拒绝、dry-run 与 apply 测试，并同步数据布局或构建发布文档。

## 生成与清理

本目录源码需要长期保留；`__pycache__` 等运行缓存可安全回收且不得提交。

## 相关文档

- `docs/storage/DATA_LAYOUT.md`
- `docs/storage/HISTORY_STORAGE_V2.md`
- `docs/storage/SITE_MANAGEMENT.md`
- `docs/release/BUILD_AND_RELEASE.md`
- `docs/development/repository-layout.md`
