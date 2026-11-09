# 缺口补齐验证

日期：2026-11-10
Branch：`codex-A/global-dataroot-disk-policy`

## 代码级规则

`MeshRawSampleCache.missing()` 将请求范围视为毫秒精度闭区间，并调用既有 `meshMissingIntervals()`。已覆盖区间合并时，相邻区间按 `previous.end + 1` 合并；因此一个窗口已经覆盖到 `10:10:00.000` 时，下一个查询从 `10:10:00.001` 开始，不会重复请求边界采样。

`loadRawSamples()` 的行为是：

1. 形成不含时间窗的 scope key。
2. 读取 coverage 并得到一个或多个 gap。
3. 每个 gap 通过 `loadRawInterval()` 发一个 raw HTTP 请求；相同 session/scope/起止毫秒的在途请求由 `rawPending` 去重。
4. 所有响应成功且完整后写入 raw cache。
5. 再次检查 remaining gap；仍有缺口则报错，不生成派生指标。

完整性规则是明确拒绝而非乐观覆盖：版本不是 `mesh-raw-v1`、`raw_sample_complete` 不为 true、或 `downsampled=true` 时不写 coverage。`is_boundary_context=true` 的 row 只保存为上下文，不能使目标区间变完整。

## 自动化 fixture 证据

`meshRawSampleCache.test.ts` 覆盖了以下可重复场景：

- 同一时间戳的不同 Peer/AP 身份独立保存；`10:00:00.000–10:00:05.000` 与 `10:00:10.000–10:00:15.000` 之间实际缺口被识别为 `10:00:05.001–10:00:09.999`。
- 不完整响应不推进 coverage；超出两个 scope 上限时最久未使用 scope 被淘汰。
- 第二段只携带第一段最后采样作为 predecessor context 时，合并后 counter previous/delta/per-second 与一次性完整 raw 集完全相同。
- reset、role change 和长间隔分别产生 `reset`、`link_changed`、`gap`，且原始 row 不被派生过程修改。

后端 `test_mesh_raw_sample_query.py` 另行验证：

- raw 目标范围只返回可见 row，context 为每个身份取一个 predecessor。
- `raw_max_rows=100` 对 101 条目标记录返回 `raw_sample_complete=false`、`downsampled=true`。
- context 查询不受可见 `link_role=ACTIVE` 过滤误伤，能够带回窗口起点前的 STANDBY predecessor。
- FastAPI route 暴露 `query_kind=raw_samples`、版本、完整性和 SQL 计数。

## 真实宁波数据分段证据

会话 `7c7b6df2-e67b-452a-ab1a-91760014501f:1`、`列车03-MR-CW`、Radio 1，窗口为 `2026-10-20 00:05:00.000–00:05:20.000`：

| 查询 | 目标记录 | 返回 items | context | complete | SQL |
|---|---:|---:|---:|---|---:|
| 第一段 `00:05:00.000–00:05:10.000` | 31 | 34 | 3 | true | 3 |
| 第二段 `00:05:10.001–00:05:20.000` | 30 | 33 | 3 | true | 3 |
| 一次性完整窗口 | 61 | 64 | 3 | true | 3 |

两段可见 record id 拼接后与完整窗口可见 record id 完全一致，连续为 `[806..866]`；第二段的 3 条 context 为 `[834, 835, 836]`，没有进入可见目标序列。该结果证明了真实后端的边界查询、上下文分离和目标记录补齐。

## 仍需补齐的验证

本轮未在真实 Electron 中抓取“已有前后两个区间、再补中间缺口”的浏览器网络日志，也未做逆序、三段、多段、重叠区间的真实 HTTP 对照。前端 gap planner 和后端分段 route 已通过自动化/真实数据验证，但完整工作台运行态请求统计仍是未完成项，不能把本报告解释为全部缓存验收通过。
