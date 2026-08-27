# Engineering State Storage Audit

## 结论

四类工程态已从无界历史重构为 Current + 最近 10 条“有效变化记录”。Current 是页面、快照和导出的事实源；Recent 只用于审计、变化回看和有限详情，不参与 Trackside 页面/导出的大范围重建。

## 资源键与语义

| 类别 | 唯一键 | Current | Recent 规则 |
| --- | --- | --- | --- |
| Radio | `site_id + ap_identity + radio_id` | 每个 AP/Radio 一行 | 状态指纹变化才写，最多 10 |
| Interface | `site_id + device_uuid + interface_name` | 每个接口一行 | PVID、链路、模式等状态变化才写，最多 10 |
| Device LLDP | `site_id + device_uuid + local_interface + chassis_id + neighbor_interface` | 当前邻居一行 | 邻居状态指纹变化才写，最多 10 |
| Device Optical | `site_id + device_uuid + interface_name` | 当前光模块一行 | Rx/Tx/告警/模块状态变化才写，最多 10 |
| AP LLDP | `resource_key` | 每个 AP 一行 | 指纹变化才写，最多 10 |
| AP Optical | `site_id + ap_identity + side` | AP/SW 当前两侧投影 | 指纹变化才写，最多 10 |
| Optical Treatment | `site_id + ap_identity` | 每个 AP 唯一台账 | AP/SW 两侧合并，不重复建行 |

时间戳、采集批次和 raw path 不属于状态指纹；重复采集只更新 Current 的观测时间与来源元数据。

## 兼容边界

旧 DB 未写入 `engineering_history_authority=retired` 时保留兼容读取；DEV cutover 后该 marker 禁止 Legacy HistoryStore writer，并将 Trackside 资源投影的独立未认证历史降为不参与 Current 读路径。MESH/MR raw、Syslog、PCAP、导入包和各自解析库保持原有事实源与生命周期，未被本轮删除或迁移。

## 同类但未纳入四类

| 表 | DEV 行数 | 分类 | 后续 |
| --- | ---: | --- | --- |
| `device_facts_history` | 1,444 | own history / NEEDS_PRODUCT_DECISION | 明确事实/摘要边界后单独任务 |
| `ac_fit_ap_resource_history` | 59,125 | FIT-AP 资源 own history / NEEDS_PRODUCT_DECISION | 评估 Current-only 与新上线语义 |
| `ac_fit_ap_unauthenticated_history` | 2,982 | unsupported independent history | 保留 producer/reader，禁止 Trackside Current 扫描 |
| `ac_station_online_summary_history` | 38 | unsupported independent history | 保留并单独定义统计事件契约 |
