# AP 位置分类

位置快照从轨交基础资料站点的正式 `node_type` 建立类型映射，并通过 `station_id` 关联 AP；正式类型优先于名称。历史缺少类型时才对规范化站点名称使用受控后缀回退：车辆段/车辆基地/段场为 `DEPOT`，停车场/停车库/停车基地为 `PARKING`，车站/正线为 `STATION`，其余为 `UNKNOWN`。AP 名称不参与分类。

快照序列化保留 `station_type`，旧 Query double 在没有站点列表 API 时回退 `UNKNOWN`，不破坏旧数据读取。正式类型为 station 时，即使名称包含特殊词也仍归 `STATION`。

状态：`AP_LOCATION_STATUS=PASS`（合成分类和兼容性回归）；真实基础资料未验收。
