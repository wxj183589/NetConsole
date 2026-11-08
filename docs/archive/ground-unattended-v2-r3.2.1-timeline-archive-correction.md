# Ground Unattended V2 R3.2.1 时间轴与历史归档验收

日期：2026-11-08
Branch：`codex-A/ground-unattended-v2-20261107`

## 结论

本轮自动化验收结论：**PASS_WITH_LIMITATIONS**。时间轴已恢复为独立事件查询，历史归档已收敛为按运行日期的一日一个压缩包，并支持同日多会话合并、幂等更新和选择后批量删除。Python 与 Renderer 定向回归通过；未连接真实设备、未读取或修改 `D:\NetConsoleData` / `D:\NetConsoleData-dev`。真实 Windows 安装、跨机器升级卸载、长时间现场运行和设备链路仍需独立验收。

## 原有问题

- 历史归档页把大量时间轴事件当作归档记录，真正的每日压缩包列表不可用。
- 启动、停止、运行日期、设备时间和接收时间的展示语义混用。
- 同日再次启动会覆盖首个启动时间，无法保留独立运行会话。
- 归档页没有每条记录的选择框，批量删除按钮无法完成正常选择流程。

## 职责划分

时间轴只查询实际发生的事件，主排序字段为 `event_at`，并独立展示 `device_time`、`received_at`、`run_date` 和 `source`。启动与停止是两个独立事件，归档生成不会改写事件时间。

历史归档只展示每日归档包，负责内容查看、完整性校验、下载、删除和保留状态。它不再承担时间轴事件列表查询。

## 数据模型与归档规则

- 新增 `ground_unattended_run_sessions`，每次启动/停止保存独立 session；daily run 仍作为按运行日期聚合的主键。
- 每个运行日期只复用一个归档 ID/ZIP；同日新 session 或新 raw 数据出现时更新该归档。
- 首次启动和最后停止分别由会话事实计算，不把多次运行压成连续会话。
- 归档摘要仅使用现有事实，包含 session 数、Syslog 记录数和 raw 文件数，不制造统计数据。
- 归档失败保留原始数据和失败状态，重试使用同一日期归档边界，不生成重复包。

## 页面与操作

ArchivePage 已删除历史索引/时间轴工作台，仅保留每日归档列表、详情、下载、校验和删除。每行使用归档唯一 ID 选择；表头支持本页全选/取消选择，显示选择数量，未选择时禁用批量删除。单条和批量删除均确认后执行，完成后刷新列表和统计，并保持时间轴原始事件、设备库存和当前运行不受影响。

## 测试结果

- Python 归档/历史/API 定向：**98 passed, 1 warning**。
- Ground 全模块：**396 passed, 1 skipped, 1 warning**。
- Renderer ArchivePage、Ground 行为、Heartbeat 定向：**55 passed**。
- Renderer 全量：**198 files / 1397 passed**。
- Electron 全量：**38 files / 306 passed**。
- `vue-tsc -b`：**PASS**。
- `local_gate --mode auto`：**PASS**（Python 5526 passed、2 skipped；架构、主契约、Ruff、文档门禁通过）。
- `python -m py_compile`：**PASS**。
- Workspace layout check：**PASS**。
- 真实设备、真实数据根和现场安装：**未执行**。

覆盖重点包括每日归档唯一性、同日多会话、启停独立事件、时间字段传递、归档恢复、空列表、单条/批量删除、全选和删除确认。

## 修改文件

主要修改位于：

- `src/netconsole/repositories/ground_unattended_repository.py`
- `src/netconsole/services/ground_unattended/supervisor.py`
- `src/netconsole/services/ground_unattended/archive_service.py`
- `src/netconsole/services/ground_unattended/application_service.py`
- `src/netconsole/backend/api/ground_unattended_router.py`
- `src/netconsole/models/api/ground_unattended.py`
- `apps/desktop_renderer/src/views/rail-transit/TimelinePage.vue`
- `apps/desktop_renderer/src/views/rail-transit/ArchivePage.vue`
- 对应 Ground Python/Renderer 测试与版本/发布文档。

## Git、数据与剩余问题

功能、版本和评审修复已提交到发布 PR #105。后续完整门禁发现新增 AC 目标富化测试意外启动 fping 工作线程，已将该测试的网络线程启动隔离，保留原业务断言和全局停止检查；原失败日志与按顺序复验证据保存在 Workspace reports。数据影响限于隔离 fixture 和 Workspace 测试证据，测试目标为文档地址 192.0.2.10；没有删除原始历史数据。最终 main 回归、Full/Customer 制品身份与 SHA256、安装验证和分支回收的当前事实以 [v1.5.12 发布报告](NETCONSOLE_V1.5.12_RELEASE_REPORT.md) 为准。本轮不创建 GitHub Release 或上传制品。
