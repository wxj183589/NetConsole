# Architecture Exceptions Audit

基线：`config/architecture/exceptions.yaml` at `origin/main` `5d88bd40`。

## Counts and decisions

| rule | count | classification | decision |
| --- | ---: | --- | --- |
| `PY_LAYER_CORE_REVERSE` | 7 | D: 应迁移依赖方向 | 保留，均有实际跨层依赖和对应 architecture guard；不得在本轮顺手重构。 |
| `PY_LAYER_REPOSITORIES_REVERSE` | 5 | D: 应迁移依赖方向 | 保留，HistoryStore/AP Identity/领域模型依赖仍是共享契约热点。 |
| `PY_LAYER_SERVICES_REVERSE` | 4 | D: 应迁移依赖方向 | 保留，属于兼容 Service/Application adapter 方向问题。 |
| `ORPHAN_SERVICE_MODULE` | 22 | C/B：静态分析误判或维护/测试入口 | 20 个由测试、诊断、动态任务注册或兼容入口证明仍可执行；两个明确为 maintenance CLI-only。 |
| `WEB_STATUS_COLOR_TOKEN` | 1 | F: 过时风险已受局部 override 约束 | 保留到压缩样式清理完成；测试验证 `--nc-warning` 覆盖。 |

总数为 39；本轮没有删除源码或放宽 architecture guard。没有证据表明任一条目可以安全删除，
因此“清理”采用证据化分类和到期 owner，而不是把静态 finding 改成未检查。

## Maintenance CLI-only entries

以下两个条目必须保留，且不得接入 Backend startup、自动调度或默认路径：

- `src/netconsole/services/history_legacy_migration.py`：仅由
  `scripts/maintenance/migrate_device_history.py`、benchmark 和验证脚本显式调用，并要求受控
  `--apply`；生产 source delete/cutover 仍关闭。
- `src/netconsole/services/production_database_maintenance.py`：仅由
  `scripts/maintenance/production_database_maintenance.py`/人工维护流程调用；生产 mutation
  gates 仍 fail-closed。

## Evidence policy

每条 exception 的 `reason`、`owner`、`test` 和到期日仍由机器校验；静态 finding 之外的动态/CLI
入口证据必须写在本文件或对应领域文档中。任何到期条目应先补真实 importer/test，再决定删除、迁移
或建立正式 entrypoint。删除 exception 之前要证明 guard 不再产生该 finding；不得通过删除测试、扩大
排除规则或把 maintenance module 接入生产路径来“清零”。

## Guarded regression

`tests/architecture/test_architecture_guards.py::test_all_architecture_checks_have_no_unwaived_findings`
仍是唯一机器门。`tests/test_architecture_exceptions_audit.py` 校验条目计数、两个 maintenance
entry 和本文件的分类边界；`scripts/architecture/run_all.py` 必须在集成 commit 重跑。

