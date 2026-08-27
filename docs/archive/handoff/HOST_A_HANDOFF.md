# Host A Handoff

日期：2026-08-26

## 当前基线

- main：`e8b826b9b6d3e799fc2bd71afe07ece07b4b2769`
- 分支：`main`
- 当前工作区：包含 LLDP/光衰 bounded current/history 实现、DEV migration tool、测试和验收报告；原有未跟踪性能审计文件未覆盖。
- 生产数据：`D:\NetConsoleData` 未访问、未修改。
- 验收数据：只使用 `D:\NetConsoleData-dev`。

## 已完成

- Phase1 性能静态审计与 profiling。
- Phase1 性能集成与 warm handoff；backend lifecycle 未重复实现。
- Trackside snapshot/export、FIT-AP、MESH 的服务端性能复核。
- LLDP `Current + 最近10条有效变化历史` 模型、迁移、DEV cutover 与回滚证据。
- Optical `Current + 最近10条有效变化历史 + 唯一 treatment ledger` 模型、AP/SWITCH 合并、空模块边界与 `-13.90 dBm` 阈值回归。
- Electron DEV 启动、Backend ready、Renderer interactive、认证 AC API 200。
- DEV 9 site schema/quick_check/authority/重复键/历史上限核验。

## 未合并内容 / 当前工作区

本轮代码尚未提交；不应把工作区变更误认为已经在远端 main。主要文件包括：

- `src/netconsole/core/database.py`
- `src/netconsole/repositories/ac_repository.py`
- `src/netconsole/services/lldp_retention.py`
- `src/netconsole/services/optical_retention.py`
- `src/netconsole/storage/lldp_optical_retention_migration.py`
- `src/netconsole/services/trackside_ap_export_service.py`
- 相关 AC/Trackside/兼容性测试与验收报告

## 当前性能热点（真实 DEV）

1. Site switch：历史基线 `8.5–14.4s`，根因是 backend restart；warm handoff metadata 历史实测 `362–453ms`。本轮最终代码启动 interactive `5.81s`，完整两局点 GUI 交替仍需补测。
2. MESH table：历史基线 `11.59s` / heap `3.22GB`；Nbo12 真实 99,299 link 数据，当前 1,000 行服务端分页 `633.13ms`。
3. Trackside snapshot/export：页面第一次快照 `936.59ms`、cache hit `3.53ms`；direct XLSX `28.14s`，其中 snapshot/enrichment `25.29s`；历史正式 Export Process 仍约 `74.8s`。
4. MESH chart：active path `1,056ms`、trackside chart `1,607.57ms`；GUI long-task/heap/滚动尚未重新采集。
5. 数据完整性：宁波12号线 unresolved 302、ambiguous 0；这是待业务数据补齐的问题，不在验收现场模糊修复。

## 推荐 Host A 下一步

1. 先检查本工作区 diff，只提交本轮 LLDP/optical/model/migration/test/report 文件；不要加入原有未跟踪审计文件。
2. 在提交前重跑 `git status`、`git diff --check`、400 项 Python 相关回归、Renderer/Electron 门禁；确认 DevStatus 三个文件追加内容未覆盖用户修改。
3. 若接受当前 PARTIAL 结果，再提交并推送；报告中明确“数据模型 PASS、Trackside export/GUI 全链路 PARTIAL”。
4. 下一任务单独处理 Trackside HistoryStore 历史分片/压缩解码；完成后再补最终 GUI Site Switch、MESH long-task/heap、设备/MESH 报告文件验收。
5. 不执行生产迁移、Update All 造数、AP Identity/LLDP 规则修改或大范围性能重构。
