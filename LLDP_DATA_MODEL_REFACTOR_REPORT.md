# LLDP Data Model Refactor Report

日期：2026-08-26

## Current/History 契约

- Current：`fit_ap_lldp_current`，每个 AP 保留当前有效 LLDP 关系。
- History：`fit_ap_lldp_history`，只记录真实关系变化，单 AP 上限 10 条。
- identity：优先 AP Identity/AP UUID，回退规范化 AP MAC；接口、邻居 MAC/接口等字段进入 canonical state fingerprint。
- 同值重复采集不新增历史；首次观测不伪造历史；多来源合并不重复实现 backend/warm handoff。

## 消费者

AC FIT-AP 列表、详情、历史页、Trackside snapshot/export 使用 bounded authority；旧表只做兼容读。非法关联维修只清 Current，保留 History 审计证据。

## 证据

- `LLDP_CANONICAL_STATE_SPEC.md`：canonical 字段与变化判定。
- `LLDP_RETENTION_MIGRATION_REPORT.json`：候选、cutover、回滚和 post-check 证据。
- DEV 9 site `quick_check=ok`；LLDP history 最大深度 `10`（demo 2、空局点 0）。
- `tests/test_lldp_retention.py`、AC/Trackside 相关回归包含首次、同值、变化、裁剪、兼容读场景。

结论：**Current/History 语义与消费边界 PASS；GUI 交替切换及生产接管不在本报告范围。**
