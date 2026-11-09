# Raw Sample Cache 设计

## 数据层次

1. 后端 `raw_samples=true` 只返回 `mesh_links` 中的事实采样；不在数据库中写入计数器派生结果。
2. `include_context=true` 时额外返回每个 raw lane 在窗口起点前的一个 predecessor，标记 `is_boundary_context=true`。
3. Renderer 收到完整 raw 响应后，以 `meshRawLaneKey()` 排序、计算 gap、role boundary、counter delta 和 rate，产出 `mesh-derived-v1`。

## 身份与覆盖

- scope key 只包含 session、radio、AP、精确 AP、role、LinkCnt=0 和站点范围；时间不是采样身份。
- sample key 使用 `source_file_id + record_id + local_radio + peer_mac + establish_time`，不会把同一毫秒的不同链路合并。
- lane key 还包含 peer radio MAC/label 和 peer AP MAC，role 变化保留在同一物理 lane 的连续序列中。
- 覆盖区间是闭区间毫秒 `[start, end]`；相邻区间自动合并，缺口由现有 `meshMissingIntervals()` 计算。
- 只有 `raw_sample_version=mesh-raw-v1`、`raw_sample_complete=true` 且 `downsampled=false` 的响应推进覆盖；context 不推进覆盖。

## 容量与生命周期

`MeshRawSampleCache` 默认最多 8 个 scope、100,000 个 raw sample，按 scope LRU 整体淘汰。刷新、session 切换和卸载清理对应 scope；in-flight 请求通过区间 key coalesce。

## 兼容边界

若服务端完全没有 raw 元数据，Workbench 仅 request-local 地回退到旧 `metric_group` / nearest 查询；该响应不写入 raw coverage，也不被报告为 raw cache 命中。带有 raw 元数据但不完整的响应直接失败并要求缩小窗口。
