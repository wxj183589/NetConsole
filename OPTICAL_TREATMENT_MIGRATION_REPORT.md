# Optical Treatment Migration Report

日期：2026-08-26
数据根：`D:\NetConsoleData-dev`
生产保护：`PRODUCTION_DATA_TOUCHED=NO`

## 执行边界

- 采用 candidate-first、SQLite Backup API、候选门禁后 DEV-only cutover。
- 生产根 `D:\NetConsoleData` 未访问、未复制、未写入、未迁移。
- 回滚副本在 cutover 成功并完成校验后清理；没有删除生产文件。
- 迁移输出：`D:\study\diagnostic\NetConsole\engineering_recent10_cutover.json`。

## 结果摘要

| 类别 | Current | Recent | 最大深度 | 结果 |
| --- | ---: | ---: | ---: | --- |
| AP LLDP | 3,365 | 27,145 | 10 | PASS |
| AP Optical | 6,638 | 50,863 | 10 | PASS |
| Device LLDP | 4,093 | 4,159 | 10 | PASS |
| Device Optical | 7,542 | 24,628 | 10 | PASS |
| AP Optical Treatment | 322 | — | — | duplicate key 0 |

Treatment 唯一键为 `(site_id, ap_identity)`；AP/SW 两侧合并为一行。所有 9 个迁移目标 `quick_check=ok`，authority marker 为 `engineering_history_authority=retired`，旧 AP direct history 目标表为 0。

## 语义门禁

- 同状态写入只更新 Current 观测元数据，不新增 Recent。
- 状态真正变化才写 Recent，且每资源最多保留 10 条有效变化。
- Trackside 页面和导出读取 Current/Treatment，不使用 Recent 进行全量重建。
- 生产接管不属于本报告结论，必须另行审批、备份和演练。

结论：**DEV optical/AP treatment migration PASS；生产接管未执行。**
