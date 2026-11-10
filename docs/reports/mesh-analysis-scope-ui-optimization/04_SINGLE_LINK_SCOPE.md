# 单链路范围

单链路资格仍为唯一 ACTIVE 且 `available_backup_count=0`，没有改成 `LinkCnt=1`。范围过滤在备链判定前执行，车辆段/停车场 AP 不产生风险，也不能为正线 AP 提供有效备链。过滤后结束的风险段不会跨越被排除时间点错误合并。

风险排序为持续时间降序，其次无备链、备链信号不达标、备链 RSSI 缺失，再按时间和 Radio 稳定排序。输出保留开始/结束时间、持续时长、备链证据、来源文件/行号和 ACTIVE Peer 证据；内部 `station_type/station_scope` 不泄露到 DTO。

状态：`SINGLE_LINK_STATUS=PASS`（合成站点、双 Radio、连续区段和排除备链回归）。
