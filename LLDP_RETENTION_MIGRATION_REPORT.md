# LLDP Retention Migration Report

日期：2026-08-26

## 边界

- 仅处理 `D:\NetConsoleData-dev`；`D:\NetConsoleData` 未访问、未修改。
- 候选根：`D:\study\diagnostic\NetConsole\lldp-optical-migration-run-all`。
- DEV cutover 回滚根：`D:\study\backup\NetConsole\lldp-optical-20260826-130133`。

## 策略

- 旧 LLDP 事实与 HistoryStore 事件重放至 `fit_ap_lldp_current` / `fit_ap_lldp_history`。
- 首次观测只写 Current；相同状态只更新时间；真实关系变化才写 History。
- History 按 AP Identity 归属，单 AP 最多保留 10 条；旧目标 LLDP history 表不再作为主读路径。
- 候选库使用 Backup API、`VACUUM INTO` 和 manifest 校验；失败保留源文件和 rollback 证据。

## DEV 结果

| 局点 | current | retained history | 最大深度 | quick_check |
| --- | ---: | ---: | ---: | --- |
| 宁波12号线 | 992 | 8,377 | 10 | ok |
| 杭州10号线 | 492 | 3,806 | 10 | ok |
| 宁波10号线 | 592 | 5,912 | 10 | ok |
| 宁波1号线 | 685 | 6,038 | 10 | ok |
| 宁波6号线 | 602 | 3,008 | 5 | ok |
| demo | 2 | 4 | 2 | ok |

9 个 active site 均完成 post-cutover 校验，旧 `ac_fit_ap_lldp_history`/`ap_lldp_history` 目标表为 0，迁移 outbox/state 为 0，最大历史深度不超过 10。

结论：**DEV LLDP migration/cutover PASS；不等同于生产迁移完成。**
