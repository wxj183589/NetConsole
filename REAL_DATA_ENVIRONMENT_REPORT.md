# Real Data Environment Report

日期：2026-08-26
代码基线：`538db1c3`（本轮工程态 Current/Recent10 变更在此基础上验收）
最终 main commit：`afa35c06`

## 环境

- `data_root`：`D:\NetConsoleData-dev`
- `D:\NetConsoleData`：未读取、未写入、未复制、未迁移；`PRODUCTION_DATA_TOUCHED=NO`
- DEV site directories：11；包含 `devices.db` 的迁移目标：9
- active site：宁波地铁12号线
- 所有验收数据库以只读方式打开；迁移只在 DEV 候选库完成后 cutover

## 数据库与规模

| 指标 | 结果 |
| --- | ---: |
| `devices.db` 总大小 | 722,067,456 bytes（约 688.6 MiB） |
| Legacy `db/history` | cutover 前 748,883,968 bytes；cutover 后 0 |
| Legacy HistoryStore 事件 | cutover 前 1,319,693 行；cutover 后 0 |
| `fit_ap_radio_current` | 6,729 |
| `fit_ap_radio_history` | 13,560 |
| `device_interfaces` / history | 13,381 / 37,355 |
| `device_lldp_neighbors` / history | 4,093 / 4,159 |
| `device_optical_modules` / history | 7,542 / 24,628 |
| `fit_ap_lldp_current` / history | 3,365 / 27,145 |
| `optical_current` / history | 6,638 / 50,863 |
| `ap_optical_treatment` | 322；重复 `(site_id, ap_identity)`：0 |

## 主要局点

| 局点 | devices.db | devices | FIT-AP resource |
| --- | ---: | ---: | ---: |
| 宁波地铁12号线 | 165,232,640 | 100 | 992 |
| 杭州地铁10号线 | 355,860,480 | 34 | 491 |

机器盘点证据：`D:\study\diagnostic\NetConsole\engineering_inventory.json`、`engineering_inventory_final.json`、`engineering_recent10_cutover.json`。
