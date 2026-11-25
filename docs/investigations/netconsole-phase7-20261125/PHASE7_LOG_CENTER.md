# Phase 7 日志中心接入

2026-11-25，本分工交付状态为 PARTIAL。服务日志查询、筛选与实时查看已经实现，正式安装态与真实 Electron 验收待集成阶段执行。

## 实现范围

- 复用 `/logs` 的 `SystemMaintenanceView`，增加网络服务日志 Tab，受既有 `capability.network_tools.local_services` 能力控制。
- `ServiceLogsPanel` 复用已有服务列表和日志 API，提供服务选择、关键字、级别、时间段、轮转历史与实时开关。刷新间隔为前一次请求完成后两秒，页面停用或卸载后结束轮询，generation 防止迟到响应覆盖新服务或新筛选。
- `GET /api/local-network-services/{kind}/logs` 增加 `keyword`、`level`、`since`、`until` 和 `history`。保留原 `lines`，增加结构化 `entries` 与 `bounded_tail/scanned_lines/history/line_limit`。非法时间、级别与过长关键字返回 422，响应设置 `Cache-Control: no-store`。
- 选择时间范围时自动读取受限轮转历史。当前日志最多 150 行，历史最多 1500 行，当前和两份轮转文件每份至多读取 250 KiB。UI Tooltip 明示查询范围。
- 未识别的 provider 输出保留原文。缺失或非法时间不参与时间段匹配，缺失级别不参与级别匹配。按时间过滤时使用带时区时间，既有无时区 logger 时间按主机本地时区解释。

本次扩展使用现有服务日志文件，服务历史读取由 Supervisor 提供。日志清理和应用运行日志导出沿用现有维护能力。

## 事实来源与入口

| 内容 | 既有来源 | 当前统一入口 / 缺口 |
| --- | --- | --- |
| 应用运行日志 | System Maintenance Service | 现有运行日志 Tab，保留搜索、级别、分页、导出及白名单清理 |
| 网络服务运行与访问日志 | Supervisor 各服务 `service.log` 与有限轮转文件 | 新服务日志 Tab，查询和实时查看 PASS |
| 服务安全审计 | Supervisor 现有 `AUDIT` 事件 | 现有日志原文可搜索，独立审计类别聚合 PARTIAL |
| 设备任务日志 | Task Repository / Task API | 既有任务日志 Tab，按 task ID 查询并跳转任务 |
| 设备连接与采集原始记录 | 连接、采集和 Job 各自来源 | 全来源时间线、设备深链和实时聚合 PARTIAL |
| 文件传输历史 | 既有文件传输任务及结果 | 服务访问事件可搜索，结构化 task/device 关联由文件与任务分工集成，PARTIAL |
| 变更、许可证、关于 | 既有维护 API | 原 Tab 保留 |

## Change Impact 与消费者

本分工为领域查询与页面扩展。原网络服务页面继续读取 `lines`，新 Tab 读取 `entries`，Router 参数均为可选。公共 API client、任务生命周期、数据库 schema 和实时来源写入者沿用现有实现。消费者包含 `LocalNetworkServicesView`、`SystemMaintenanceView`、新日志面板、服务 Router 和 Supervisor 的日志读取接口。Manager / Protocol / TLS 与文件管理由其他分工并行实现，最终集成需要复跑现有服务生命周期测试。

后续完整日志中心验收还需覆盖所有来源的统一 task/device 关联、服务日志 Export Process 导出、历史归档检索与保留期限策略。当前受限轮转查询只覆盖 Supervisor 已保留的日志文件。

## 验证

| 检查 | 结果 |
| --- | --- |
| `pytest tests/test_service_log_query.py -q` | PASS，2 tests，涵盖原文字段兼容、筛选、非法时间、历史参数、范围错误和 no-store |
| `pytest tests/test_service_log_query.py tests/test_local_network_services.py::test_http_api_lifecycle_file_boundary_and_port_conflict -q` | PASS，3 tests，包含现有 HTTP 生命周期及日志读取兼容回归 |
| `vitest run src/views/system/ServiceLogsPanel.test.ts src/views/system/SystemMaintenanceView.test.ts` | PASS，13 tests，包含轮询结束、KeepAlive 停用/恢复、陈旧响应与历史请求 |
| `vue-tsc --noEmit` | PASS |
| Ruff 对本分工 Python 文件 | PASS |
| 四尺寸真实 Electron 与正式安装包 | NOT VERIFIED，由集成任务执行 |
| 真实设备 / 真实长期运行 | NOT VERIFIED |

Python 测试出现现有 Starlette/httpx 弃用提示。测试使用主仓库 `.venv` 和项目隔离 fixture，未读取 Production 或 Dev 真实数据。

```text
MAINTENANCE_AUTHORIZED=NO
PRODUCTION_DATA_MODIFIED=0
DATABASES_REMOVED=0
DEVICE_CONFIGURATION_WRITES=0
```
