# Architecture Baseline Debt Governance — 2026-10-12

本清单对应 `github/main` `8b2a1fc9` 上 `config/architecture/exceptions.yaml` 的原 37 条过期例外。处理原则是：真实消除依赖或确认无生产调用者后删除例外；保留旧导入入口时必须保留行为；不添加虚假调用者、不扩大扫描排除、不延长过期时间。

## 逐条结果

| 原 rule/path | 结果 | 处理与证据 |
| --- | --- | --- |
| `PY_LAYER_CORE_REVERSE` `core/bootstrap.py` | `REQUIRES_OWNER_APPROVAL` | 组合根仍创建 Repository；需 core/data owner 独立注入切片，避免破坏 `create_demo_context`。 |
| `PY_LAYER_CORE_REVERSE` `core/mr_collect/parser/counter_parser.py` | `FIXED` | parser 实现归位 `core/mr_collect/parser/online_mr_parser.py`，原 Service 入口保留兼容导出。 |
| `PY_LAYER_CORE_REVERSE` `core/mr_collect/parser/fping_parser.py` | `FIXED` | legacy fping parser 归位 core，Service 入口保留兼容导出。 |
| `PY_LAYER_CORE_REVERSE` `core/mr_collect/parser/mesh_parser.py` | `FIXED` | Online MR parser 归位 core，保留既有公共 Service 导入路径。 |
| `PY_LAYER_CORE_REVERSE` `core/mr_collect/ssh_client.py` | `FIXED` | SSHClient 改为由 Service boundary 注入 connection factory，不再从 core 反向导入 collector。 |
| `PY_LAYER_CORE_REVERSE` `core/ping/fping_v5_runner.py` | `FIXED` | tool resolver 与 validator 归位 core，Service 入口保留兼容导出。 |
| `PY_LAYER_CORE_REVERSE` `core/sites.py` | `REQUIRES_OWNER_APPROVAL` | Site 初始化仍组合 Repository 与 demo data；迁移会触及 Site/Database 启动契约。 |
| `PY_LAYER_REPOSITORIES_REVERSE` `repositories/ac_repository.py` | `FIXED` | source helper、VLAN parser 与 bounded retention 归位 core。 |
| `PY_LAYER_REPOSITORIES_REVERSE` `repositories/mesh_mr_repository.py` | `FIXED` | MESH analyzer、RSSI stats、Identity normalizer 归位 core。 |
| `PY_LAYER_REPOSITORIES_REVERSE` `repositories/rail_transit_base_data_repository.py` | `FIXED` | rail source helper 归位 `core/sources`。 |
| `PY_LAYER_REPOSITORIES_REVERSE` `repositories/ap_identity_repository.py` | `FIXED` | normalizer 与 topology projection 归位 core。 |
| `PY_LAYER_REPOSITORIES_REVERSE` `repositories/device_fact_repository.py` | `FIXED` | Current/Recent10 retention helper 归位 `core/storage`。 |
| `PY_LAYER_SERVICES_REVERSE` `services/command_reference_application_service.py` | `FIXED` | Web artifact/process contract 归位 service，Application 保留兼容导出。 |
| `PY_LAYER_SERVICES_REVERSE` `services/device_management_web_service.py` | `FIXED` | Desktop/Web contract 归位 service，Application 保留兼容导出。 |
| `PY_LAYER_SERVICES_REVERSE` `services/file_management_service.py` | `FIXED` | Desktop action contract 改为 service-owned。 |
| `PY_LAYER_SERVICES_REVERSE` `services/job_center/query_service.py` | `FIXED` | maintenance task constants 提取为 Job Center contract。 |
| `ORPHAN_SERVICE_MODULE` `services/agent/local_self_check.py` | `FIXED` | 实际调用者是维护脚本，入口归位 `scripts/maintenance/agent`，测试同步。 |
| `ORPHAN_SERVICE_MODULE` `services/ap_mapping_service.py` | `FIXED` | 全仓库源码、测试、脚本、配置无调用者，安全删除旧模块。 |
| `ORPHAN_SERVICE_MODULE` `services/background_tasks.py` | `FIXED` | 仅测试兼容 helper，归位 `tests/support`，生产 Job Center 未被伪造引用。 |
| `ORPHAN_SERVICE_MODULE` `services/config_snapshot_task_helpers.py` | `FIXED` | 无调用者；现行 config job handler 已是正式入口，删除旧 helper。 |
| `ORPHAN_SERVICE_MODULE` `services/data_disk_manager.py` | `FIXED` | 仅测试使用，归位 `tests/support`，不改变真实数据清理边界。 |
| `ORPHAN_SERVICE_MODULE` `services/device_batch_operations.py` | `FIXED` | 仅测试使用，归位 `tests/support`。 |
| `ORPHAN_SERVICE_MODULE` `services/device_form_rules.py` | `FIXED` | 仅测试使用，归位 `tests/support`；UI 现行规则未改。 |
| `ORPHAN_SERVICE_MODULE` `services/export_task_models.py` | `FIXED` | 仅测试使用，归位 `tests/support`；正式 ExportJob 入口未改。 |
| `ORPHAN_SERVICE_MODULE` `services/external_tool_launcher.py` | `REQUIRES_OWNER_APPROVAL` | 无内部调用者但声明为旧导入兼容层，不能在没有外部 consumer 清单时删除。 |
| `ORPHAN_SERVICE_MODULE` `services/mr_service.py` | `REQUIRES_OWNER_APPROVAL` | 无内部调用者但属于旧 MR facade，需 online-mr owner 确认外部兼容范围。 |
| `ORPHAN_SERVICE_MODULE` `services/network_tools/toolbox/export.py` | `FIXED` | 无调用者，且当前 network export 由正式 job handler 提供，删除旧模块。 |
| `ORPHAN_SERVICE_MODULE` `services/network_tools/toolbox/route_tools.py` | `FIXED` | 仅测试使用，归位 `tests/support`。 |
| `ORPHAN_SERVICE_MODULE` `services/network_tools/wireless_mimo_parser.py` | `FIXED` | 仅测试使用，归位 `tests/support`；生产 Wireless IE parser 未变。 |
| `ORPHAN_SERVICE_MODULE` `services/online_mr/core/realtime_parser.py` | `FIXED` | 仅测试使用，归位 `tests/support`；现行 realtime parser engine 未改。 |
| `ORPHAN_SERVICE_MODULE` `services/online_mr/offline/replay_engine.py` | `REQUIRES_OWNER_APPROVAL` | storage registry 与历史 Online MR 语义仍引用该位置，需 owner 确认 replay authority 后再移除。 |
| `ORPHAN_SERVICE_MODULE` `services/online_mr_analysis_report_exporter.py` | `REQUIRES_OWNER_APPROVAL` | 测试与 storage registry 仍证明它是历史报告实现，不能无审批删除或伪接入生产。 |
| `ORPHAN_SERVICE_MODULE` `services/path_preference_service.py` | `FIXED` | 无调用者且现行路径契约由 PathResolver/领域服务承担，删除旧模块。 |
| `ORPHAN_SERVICE_MODULE` `services/rail_transit/trackside_optical_history.py` | `REQUIRES_OWNER_APPROVAL` | storage registry 仍记录历史光学语义，需 rail-transit/data owner 确认重建/退役边界。 |
| `ORPHAN_SERVICE_MODULE` `services/site_database_recovery.py` | `REQUIRES_OWNER_APPROVAL` | 仅测试/历史恢复入口，但含数据库备份与删除操作，必须由 data owner 明确 maintenance 入口后再迁移。 |
| `ORPHAN_SERVICE_MODULE` `services/vehicle_mr_offline_report.py` | `FIXED` | 无调用者，且现行 `vehicle_mr_offline_excel_report.py` 已承担报告输出，删除旧 façade。 |
| `WEB_STATUS_COLOR_TOKEN` `TracksideApWpsConfigDialog.vue` | `FIXED` | 原压缩样式直接使用 Element 状态 token 改为 `--nc-warning`，删除重复 scoped override 与例外。 |

## 当前门禁与决策

本分支将例外清单收敛为 8 条：2 条 `PY_LAYER_CORE_REVERSE`，6 条 `ORPHAN_SERVICE_MODULE`，全部按 fail-closed 处理并保持已过期。它们不是自动批准的债务，也不能通过改 `expires_at` 变绿。需要 owner 批准的 8 条应在独立架构 PR 中完成组合边界、外部兼容和历史维护入口的正式决策后，继续清空例外。

本次迁移未触碰 `D:\NetConsoleData`、`D:\NetConsoleData-dev`、`F:\ncdata`，未删除或重建任何真实数据库。
