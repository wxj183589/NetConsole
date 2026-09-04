# Architecture Guard 基线债务复核

复核基线：Phase 1 记录的 7 条未豁免发现，复核日期 2026-09-04。本文只做事实分类和后续边界记录，不把分类结果直接写成大量 architecture exception，也不改变业务运行逻辑。

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

这 7 条是“原始 guard 发现”的分类，不等于已完成门禁清零。当前 Phase 1.5 不新增宽泛豁免；尤其 `UNREGISTERED_STORAGE` 仍应保留在债务列表中，后续由 storage owner 决定是否把局点导出 Job 作为 `site.devices.current` 的明确消费者登记，并补对应测试。

本次复核未确认独立业务功能错误，因此没有新增 `DISCOVERED_BUG`。真实设备、生产数据、数据库结构和 API/UI 行为均未触碰。
