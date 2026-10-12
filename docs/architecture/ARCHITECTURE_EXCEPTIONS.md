# Architecture Exceptions Audit

基线：`github/main` `8b2a1fc9`；本次治理分支为 `codex/architecture-baseline-remediation-20261012`。

## Counts and decisions

37 条过期例外已逐条复核并通过真实代码处理：组合根归入 Service、纯身份 helper 下沉、旧 facade 退役或收口到正式兼容入口，维护和导出能力保留原安全边界。当前无活动例外，不续期旧例外。

| rule | count | classification | decision |
| --- | ---: | --- | --- |
| `PY_LAYER_CORE_REVERSE` | 0 | `FIXED` | `SiteManager` 与 `create_demo_context` 的组合逻辑归入 Service；core 仅保留纯站点身份 helper，Repository 不再反向依赖 Service。 |
| `ORPHAN_SERVICE_MODULE` | 0 | `FIXED` | 旧 external/MR facade 已按消费者证据退役；离线 replay、兼容报告、轨旁光学历史和数据库恢复均有正式包入口、ExportJob/查询入口或显式维护入口。 |

总数为 0；`PY_LAYER_REPOSITORIES_REVERSE`、`PY_LAYER_SERVICES_REVERSE`、`WEB_STATUS_COLOR_TOKEN` 继续清零。
所有架构例外均已删除；门禁必须以当前静态扫描结果为准，不得通过新增例外或延长日期绕过门禁。

## Production maintenance boundary

Production maintenance capability 仍保持显式 CLI/人工维护边界；Backend startup 只读取同一模块的 canonical site/database scope helper，
不调用 rollback owner、manifest、replacement 或 Production mutation capability：

- `src/netconsole/services/production_database_maintenance.py`：scope resolution 可被启动只读复用；生产 mutation gates 仍 fail-closed。

## Evidence policy

每条 exception 的 `reason`、`owner`、`test` 和到期日仍由机器校验；静态 finding 之外的动态/CLI
入口证据必须写在本文件或对应领域文档中。任何到期条目应先补真实 importer/test，再决定删除、迁移
或建立正式 entrypoint。删除 exception 之前已证明 guard 不再产生该 finding；不得通过删除测试、扩大
排除规则或把 maintenance module 接入普通启动路径来“清零”。完整 37 条处理清单见
`docs/architecture/ARCHITECTURE_DEBT_GOVERNANCE_20261012.md`。

## Guarded regression

`tests/architecture/test_architecture_guards.py::test_all_architecture_checks_have_no_unwaived_findings`
仍是唯一机器门。`tests/test_architecture_exceptions_audit.py` 校验条目计数、maintenance entry 和本文件的分类边界；
`scripts/architecture/run_all.py` 必须在集成 commit 重跑。
