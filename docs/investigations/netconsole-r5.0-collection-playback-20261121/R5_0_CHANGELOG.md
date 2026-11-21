# R5.0 Changelog

- 增加实时采集/历史回放一级工作区。
- 增加历史 Site、线路、运行、列车/MR、时间范围选择和显式只读查询。
- 主地址、备用地址、Peer AP 使用唯一可视时间窗和底部 Navigator。
- 备用地址默认展开、可折叠，并保存用户折叠偏好。
- 修复 H3C MESH RSSI 正值被 `+100` 后截顶的问题，恢复真实负 dBm 语义。
- Peer 区间仅由相邻 `MESH_ACTIVELINK_SWITCH` 构造；增加窗口前序证据，不延长未证明末段。
- MESH 最近三条与丢包事件跟随当前可视窗口；丢包支持分页。
- 增加请求取消、generation 和 250 ms 事件查询防抖。
- 未改版本、Schema、采集调度、默认开关、包和 Release。
