# Optical Treatment Migration Report

日期：2026-08-26

## 执行边界

- 输入数据根：`D:\NetConsoleData-dev`。
- `D:\NetConsoleData`：未访问、未修改。
- 模式：先 dry-run/candidate，随后 DEV-only cutover；没有直接在生产目录执行迁移。
- 候选根：`D:\study\diagnostic\NetConsole\lldp-optical-migration-run-all`。
- 回滚根：`D:\study\backup\NetConsole\lldp-optical-20260826-130133`。
- 详细机器报告：`LLDP_RETENTION_MIGRATION_REPORT.json`。

## 迁移策略

1. 以 SQLite Backup API 创建候选库。
2. 从旧 optical current/history 与 HistoryStore 事件重放到 `optical_current`、`optical_history`、`ap_optical_treatment`。
3. 对每个 `site_id + ap_identity + side` 保留最后 10 个真实变化事件；对每个 `site_id + ap_identity` 合并 AP/SWITCH 台账。
4. 清理候选库中的旧目标 history、迁移 outbox/state；保留业务资源表和当前 FIT-AP 资源。
5. 对候选主库与历史 shard 执行 `VACUUM INTO`，关闭连接后再替换候选文件；DEV cutover 失败时恢复源文件。
6. cutover 前后执行 manifest/quick_check/schema/authority/重复键/深度校验。

## 结果摘要

| 局点 | optical current | optical history | 最大历史深度 | treatment | quick_check |
| --- | ---: | ---: | ---: | ---: | --- |
| 宁波12号线 | 1,892 | 18,907 | 10 | 101 | ok |
| 杭州10号线 | 984 | 8,646 | 10 | 85 | ok |
| 宁波10号线 | 1,184 | 11,508 | 10 | 49 | ok |
| 宁波1号线 | 1,370 | 8,488 | 10 | 74 | ok |
| 宁波6号线 | 1,204 | 3,314 | 5 | 13 | ok |
| demo | 4 | 0 | 0 | 0 | ok |

其余 3 个空数据局点的 current/history/treatment 均为 0，`quick_check=ok`。全部候选/切换后库的 treatment duplicate groups 为 0；旧 `ac_fit_ap_optical_history`/`ap_optical_history` 等目标表计数为 0。

## 失败恢复证据

第一次 cutover 在 demo 候选句柄关闭前失败，迁移工具恢复源文件；修正候选连接生命周期后，`--cutover-only` 成功。源文件未删除，而是移动到上述 rollback 根，便于人工恢复。

结论：**DEV optical migration/cutover PASS；生产迁移未执行。** 后续若需要生产接管，必须单独审批、备份和演练，不能复用本次 DEV 结果直接宣称生产完成。
