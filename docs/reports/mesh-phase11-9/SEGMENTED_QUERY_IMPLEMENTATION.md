# 分段查询接入实现

日期：2026-11-10
Branch：`codex-A/global-dataroot-disk-policy`
变更级别：L3（共享 Renderer 原始缓存、公共 DTO/API、动态指标路径）

## 结论

本轮已把毫秒精度缺口规划器接入真实 raw 查询路径。Renderer 不再为每个指标分别请求完整窗口：同一会话、MR、Radio、Peer、角色和数据范围条件先形成 raw scope，再由 `meshMissingIntervals()` 计算真正缺失的闭区间；每个缺口才发出 `raw_samples=true` 的 HTTP 请求。

后端 raw 查询只读取目标区间及可选的边界 predecessor，不写数据库、不做全量重解析。完整性、截断和降采样状态在进入共享缓存前校验。由于真实 Electron/浏览器运行态本轮未启动，下面的“请求减少”是代码路径、单元测试和真实 HTTP 路由证据，不能替代完整工作台交互计数。

## 实际数据流

```text
Workbench 时间窗/筛选条件
  -> meshRawScopeKey（排除纯时间窗，保留实际筛选）
  -> MeshRawSampleCache.missing
  -> meshMissingIntervals（毫秒闭区间）
  -> listMeshLinks(raw_samples=true, include_context=true)
  -> 后端目标采样 + 批量 predecessor
  -> raw_sample_version / raw_sample_complete / downsampled 校验
  -> 按 sample key 合并、按时间排序
  -> deriveMeshRawSamples
  -> 指标图表、历史、时间定位和右侧详情
```

## 后端修改

- `MeshAnalysisQueryService.list_link_details()` 增加 `raw_samples`、`include_context`、`raw_max_rows` 参数。
- raw 模式要求显式 `time_from/time_to`，拒绝与 `metric_group`、`nearest_time`、`include_zero` 混用，避免把派生结果误当作 raw 事实。
- 目标 SQL 使用 `raw_max_rows + 1` 检测截断；返回超出上限时 `raw_sample_complete=false`、`downsampled=true`，不得写入共享 coverage。
- `_raw_context_rows()` 先按 source/radio 批量扫描窗口起点前记录，再按完整 lane identity 选择 predecessor。上下文标记为 `is_boundary_context=true`，不增加目标 `total`，不冒充目标覆盖。
- `MeshLinkPageDTO` 和 `MeshLinkDetailDTO` 暴露 raw/derived 版本、上下文、来源文件及 SQL 计数元数据；Router 透传真实查询参数。

## Renderer 修改

- `meshRawSampleCache.ts` 复用既有 `meshCompleteMetricCache.ts` 的 `Interval` 和缺口计算，不再创建第二套区间规划器。
- `MeshRawSampleCache` 以 session 加 scope key 隔离数据，最多 8 个 scope、最多 100000 个 sample，按最近使用时间淘汰；完整、非降采样且版本为 `mesh-raw-v1` 的响应才推进 coverage。
- raw sample key 包含 `source_file_id`、持久 `record_id`、local radio、PeerMac 和 establish time；同一时间戳的不同链路不会互相覆盖。
- `MeshPhase11Workbench.vue` 的指标、历史和时间定位共享 raw cache；已缓存范围直接本地派生，缺口通过 `Promise.all` 并发补齐并通过 `rawPending` 去重。
- 缓存原始事实的派生版本固定为 `mesh-derived-v1`。派生过程只复制 row，不反向修改缓存中的 raw row。
- 仍保留旧后端/测试 double 的 request-local compatibility fallback；没有 raw 版本元数据时只临时复用旧 metric/nearest 响应，绝不推进 raw coverage。

## 覆盖边界

已接入共享 raw 路径：主工作台全部非 `LinkCnt=0` 指标、历史列表、时间点最近定位、右侧选中详情的本地定位。

保留既有路径：显式 `include_zero` 视图仍使用原 metric endpoint（raw 合同故意不接受 zero-link 混合数据）；AP 统计、Active Build Order/建链分页、摘要和解析问题是独立业务查询，未强行拼接为 raw sample。

## 关键保证

1. 缩小已覆盖窗口不发 raw HTTP/SQL。
2. 扩大窗口只请求缺口，不重新请求已覆盖区间。
3. 中间缺口使用前后端点加一毫秒/减一毫秒的闭区间规划，不以固定秒数重叠掩盖边界问题。
4. context row 只参与派生前值和连续性，不显示、不计数、不推进 coverage。
5. 取消、失败、截断、版本不匹配均不污染共享缓存。

## 尚未完成

真实 Electron 中的完整窗口、双缺口、缩小窗口、右侧详情操作尚未逐操作记录 HTTP/SQL 数量；真实数据已完成后端 HTTP/SQL 路由验证和 raw 记录对照，但未在真实 Renderer 中运行完整派生流程。因此本轮总状态仍为 `PHASE_11_9_FOURTH_ROUND=PARTIAL`。
