# Architecture Exceptions Audit

基线：`github/main` `8b2a1fc9`；本次治理分支为 `codex/architecture-baseline-remediation-20261012`。

## Counts and decisions

37 条过期例外已逐条复核：29 条已通过真实依赖归位、测试/维护入口归位、兼容导出收口、纯 helper 下沉或删除无调用者旧模块消除；当前只保留 8 条需要负责人确认的真实边界，不续期旧例外。

| rule | count | classification | decision |
| --- | ---: | --- | --- |
| `PY_LAYER_CORE_REVERSE` | 2 | `REQUIRES_OWNER_APPROVAL` | `core/bootstrap.py` 与 `core/sites.py` 仍承担组合根/局点初始化；继续拆分会改变 Site/Database 初始化入口和兼容 API，需 data/core owner 的独立切片。 |
| `ORPHAN_SERVICE_MODULE` | 6 | `REQUIRES_OWNER_APPROVAL` | `external_tool_launcher.py`、`mr_service.py` 是潜在外部兼容入口；Online MR replay/export、轨旁光学历史、站点数据库恢复具有历史/维护/存储语义，不能凭静态扫描删除或添加虚假生产调用者。 |

总数为 8；`PY_LAYER_REPOSITORIES_REVERSE`、`PY_LAYER_SERVICES_REVERSE`、`WEB_STATUS_COLOR_TOKEN` 已清零。
当前例外只作为阻断证据，均已过期，不能直接合并或通过延长日期绕过门禁。

## Production maintenance boundary

Production maintenance capability 仍保持显式 CLI/人工维护边界；Backend startup 只读取同一模块的 canonical site/database scope helper，
不调用 rollback owner、manifest、replacement 或 Production mutation capability：

- `src/netconsole/services/production_database_maintenance.py`：scope resolution 可被启动只读复用；生产 mutation gates 仍 fail-closed。

## Evidence policy

每条 exception 的 `reason`、`owner`、`test` 和到期日仍由机器校验；静态 finding 之外的动态/CLI
入口证据必须写在本文件或对应领域文档中。任何到期条目应先补真实 importer/test，再决定删除、迁移
或建立正式 entrypoint。删除 exception 之前要证明 guard 不再产生该 finding；不得通过删除测试、扩大
排除规则或把 maintenance module 接入生产路径来“清零”。完整 37 条处理清单见
`docs/architecture/ARCHITECTURE_DEBT_GOVERNANCE_20261012.md`。

## Guarded regression

`tests/architecture/test_architecture_guards.py::test_all_architecture_checks_have_no_unwaived_findings`
仍是唯一机器门。`tests/test_architecture_exceptions_audit.py` 校验条目计数、maintenance entry 和本文件的分类边界；
`scripts/architecture/run_all.py` 必须在集成 commit 重跑。
