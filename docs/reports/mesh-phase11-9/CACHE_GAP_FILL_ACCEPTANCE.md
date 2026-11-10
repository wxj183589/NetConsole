# Raw cache gap fill 验收

日期：2026-11-10
测试：`apps/desktop_renderer/src/components/mesh-analysis/meshRawSampleCache.test.ts`

构造同一 scope 的两个完整区间：

- A：`[BASE, BASE+1000]`
- C：`[BASE+2000, BASE+3000]`
- 请求 A+B+C：`[BASE, BASE+3000]`

`missing()` 精确返回 B：`[BASE+1001, BASE+1999]`。测试只向该区间写入一次响应；写入后再次请求 A+B+C，missing 为空，visible rows 为 5 条，未重复请求 A 或 C。

raw cache 只接受 `raw_sample_complete=true` 且 `downsampled=false` 的 response 推进 coverage；context 不推进 coverage，visible row 在同 key 冲突时覆盖先前 context。缓存 scope 同时受 AP/Radio/role/zero 等 query 条件隔离。

结论：`PASS（最小确定性 fixture）`；真实多段/逆序/重叠 GUI 交互仍未完成。
