# FIT-AP Radio Retention Report

## 模型

最终 main commit：`afa35c06`

唯一键：`site_id + ap_identity + radio_id`。状态指纹包含 status/mode/band/channel/bandwidth/usage/tx_power/clients/bbssid；采集时间、collect run 和 raw path 仅为元数据。

## DEV 结果

- `fit_ap_radio_current`：6,729 行。
- `fit_ap_radio_history`：13,560 行。
- 每个资源 Recent 最大 10；hzl10 示例 Current 982、Recent 1,491；宁波12号线 Current 1,984、Recent 0。
- 单元 retention 测试：1000 次同状态不增长，100 次变化最终只留 10 条且无重复 fingerprint。
- 旧 `ac_fit_ap_radio_history`：0 行；HistoryStore Radio 事件：0。

结论：**PASS（DEV）**。旧 DB 未 cutover 时保留兼容读写；生产接管不在本轮范围。
