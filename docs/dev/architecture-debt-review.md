# Architecture Guard 基线债务复核

复核基线：Phase 1 记录的 7 条未豁免发现，初次复核日期 2026-09-04。下表保留当时的事实分类；2026-09-09 主线收口已按精确登记或最小删除完成清零。

## 分类结果

| Rule | 文件与行 | 证据摘要 | 分类 | Phase 1.5 决定 |
| --- | --- | --- | --- | --- |
| `DIRECT_SQL_UNCLASSIFIED` | `tests/test_database_backup_batch_delete.py:23` | `_create_database()` 只接收 pytest `tmp_path` 下的 fixture 路径，用于构造批量备份测试数据库；不是生产连接 | `TEST_ONLY` | 不修改生产代码；后续若 guard 需要精确分类，可补充最小测试来源登记 |
| `UI_BUSINESS_LOGIC_UNCLASSIFIED` | `apps/desktop_renderer/src/components/mesh-analysis/meshRssiContext.ts:177` | `resolveMeshRssiPoint` 将折线采样值与已加载图表上下文合并，服务悬停/展示；未执行业务写入、设备决策或策略判断 | `FALSE_POSITIVE` | 保留现有组件边界，不迁移到 Service |
| `RUNTIME_PATH_CWD` | `src/netconsole/services/job_center/handlers/site_jobs.py:162` | `worker_cwd` 作为 `SOURCE_DB_OPEN` 进度诊断字段输出；源库来自 Registry 记录的 `record.root_path` | `FALSE_POSITIVE` | 不把诊断字段误判为生产路径解析；不改任务行为 |
| `RUNTIME_PATH_CWD` | `src/netconsole/services/job_center/handlers/site_jobs.py:190` | `worker_cwd` 作为 `EXPORT_FAILED` 错误诊断字段输出；异常路径和源库路径均已由业务对象/参数解析 | `FALSE_POSITIVE` | 保留可观测性；不删除诊断信息 |
| `RUNTIME_PATH_CWD` | `src/netconsole/services/site_storage.py:1572` | 导出目标目录创建失败时把当前工作目录写入错误详情，目标仍来自调用方的已解析 `destination` | `FALSE_POSITIVE` | 不把错误诊断上下文当作存储根；不修改导出流程 |
| `RUNTIME_PATH_CWD` | `src/netconsole/services/site_storage.py:3100` | `_export_source_details()` 返回 `worker_cwd` 供失败/诊断报告使用，实际 source 已由传入路径解析 | `FALSE_POSITIVE` | 保留诊断字段；后续可让 guard 区分 telemetry 与路径构造 |
| `UNREGISTERED_STORAGE` | `src/netconsole/services/job_center/handlers/site_jobs.py:145` | `site_export` 从 Registry 的局点根派生 `db/devices.db`，但 `site_jobs.py` 不在当前 `config/storage_registry.yaml` 的已登记 source location 中 | `TRUE_VIOLATION` | 记录为存储来源登记债务；不在本阶段修改 Registry、Job Handler 或导出逻辑 |

## 汇总

```text
TRUE_VIOLATION=1
FALSE_POSITIVE=5
LEGACY_EXCEPTION=0
TEST_ONLY=1
```

这 7 条是“原始 guard 发现”的历史分类，不代表当前仍存在债务。

## 2026-09-09 收口结果

- `tests/test_database_backup_batch_delete.py` 已按精确文件登记为 `TEST_ONLY`，仅允许 pytest 隔离 SQLite fixture。
- `resolveMeshRssiPoint` 已按精确 symbol 和现有单测登记为 `DISPLAY_ONLY`，没有迁移业务事实或扩大 Renderer 权限。
- 4 个只用于诊断的 `worker_cwd` 字段没有下游消费者，已删除，避免物理路径泄漏；真实 source/destination 仍来自受控解析路径。
- `site_export` 已作为 `site.devices.current` 的 Site Package 消费者登记到 Storage Registry。
- 更新策略断言已固定为：只有 `published=true` 且 ProductVersion 更高才提示升级；同版本 build/hash 变化不提示。

验证结果：`scripts/architecture/run_all.py` 为 12/12 PASS，Ruff 全仓 PASS；`config/ci/baseline_failures.yaml` 的 Python、Architecture、Ruff 精确债务均为 0。没有新增宽泛 exception，也未访问或修改 Production 数据。
