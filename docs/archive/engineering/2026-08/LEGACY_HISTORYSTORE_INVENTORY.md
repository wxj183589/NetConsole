# Legacy HistoryStore 盘点

日期：2026-08-26
范围：仅 `D:\NetConsoleData-dev`；`PRODUCTION_DATA_TOUCHED=NO`。

## Before

- DEV site directories：11；有 `devices.db` 的迁移目标：9。
- `db/history` 总字节数：`748,883,968`（约 748.9 MB）。
- HistoryStore 事件行：`1,319,693`。
- 分类：Interface `434,512`、Radio `332,580`、Optical `218,686`、LLDP `164,981`、Other `168,934`。
- Other 由 `device_fact`、`fit_ap_resource`、`fit_ap_unauthenticated`、`station_online_summary` 组成，不在本轮四类工程态收口范围。

## 四类来源

| 类别 | 旧来源行数 | 迁移后的 authority |
| --- | ---: | --- |
| FIT-AP Radio | 124,977 | `fit_ap_radio_current` + `fit_ap_radio_history` |
| Interface | 208,261 | `device_interfaces` + `device_interfaces_history` |
| Device LLDP | 46,568 | `device_lldp_neighbors` + `device_lldp_neighbors_history` |
| Device Optical | 156,845 | `device_optical_modules` + `device_optical_modules_history` |
| AP LLDP | 既有 bounded Current/History | `fit_ap_lldp_current` + `fit_ap_lldp_history` |
| AP Optical | 既有 bounded Current/History | `optical_current` + `optical_history` |

## After

- Legacy HistoryStore `db/history`：0 bytes，11 个 DEV site 目录均不存在 history 目录。
- HistoryStore 事件扫描结果：0 行。
- 旧 AP 直接历史表：`ac_fit_ap_radio_history=0`、`ac_fit_ap_lldp_history=0`、`ac_fit_ap_optical_history=0`、`ap_lldp_history=0`、`ap_optical_history=0`。
- 四类 bounded history 均以资源键分组，最大深度不超过 10；同状态写入不新增 Recent。
- `ap_optical_treatment`：322 行，`(site_id, ap_identity)` 重复分组 0。

机器证据：`D:\study\diagnostic\NetConsole\engineering_inventory.json`、`engineering_inventory_final.json`、`engineering_recent10_cutover.json`。
