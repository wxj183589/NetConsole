# Engineering History Audit

## PASS

- Current/Recent10 写入 helper：Radio、Interface、Device LLDP、Device Optical。
- AP LLDP/AP Optical bounded authority 与 AP Optical Treatment 唯一台账。
- 同状态 suppression、真实变化记录、每资源 Recent <=10。
- candidate-first、parity、idempotence、quick_check、authority marker。
- Trackside page/export Current-only，无 Legacy HistoryStore 回退。

## PARTIAL / NEEDS_PRODUCT_DECISION

- `device_facts_history`、`ac_fit_ap_resource_history`、`ac_fit_ap_unauthenticated_history`、`ac_station_online_summary_history` 仍是独立 owner history；本轮只禁止它们污染 Trackside Current，不擅自删除或改变其业务语义。
- Electron GUI、MESH GUI heap/long-task、Task Center 全操作矩阵未在本轮重新完成。
