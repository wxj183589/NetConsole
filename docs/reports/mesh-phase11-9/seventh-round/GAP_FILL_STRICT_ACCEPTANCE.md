# A+C 仅补 B 严格验收

## 数据身份

- 隔离根：`D:\study\NetConsole-Workspace\test-data\NetConsole\mesh-phase11-8-run-001`。
- Site：宁波地铁12号线。
- Session：`80716c07-6bd9-47d8-b76d-ace1e55624d1:1`。
- 统一 query identity：radio=1、exact_ap=true、link_role=ACTIVE、include_zero=false、exclude_depot=true、exclude_parking=true、peer_ap_mac 为空。
- raw endpoint：`raw_samples=true&include_context=true&raw_max_rows=50000&page_size=1000`。

## 实际请求范围

| 步骤 | 目标窗口 | 实际 raw HTTP | SQL | 目标行 | boundary context | 结果 |
|---|---|---:|---:|---:|---:|---|
| A | `18:30:00.000–18:33:00.000` | 1 | 3 | 285 | 1 | A 完整覆盖 |
| C | `18:35:00.000–18:38:00.000` | 1 | 3 | 175（实际只请求 `18:35:00.000–18:37:06.380`，右侧已由初始窗口覆盖） | 1 | C 完整覆盖 |
| A+B+C | `18:30:00.000–18:38:00.000` | 1 | 3 | 181（实际只请求 B：`18:33:00.001–18:34:59.999`） | 1 | B 完整补齐 |
| A+B+C 重复 | 同上 | 0 | 0 | 0 | 0 | raw cache 完整命中 |

A/C/ABC 首次严格序列的 operation id 分别为：

- A：`mesh-op-mwa4bpt4-c`，HTTP 200，SQL=3。
- C：`mesh-op-mwa4btzd-m`，HTTP 200，SQL=3。
- ABC 的 raw gap：`mesh-op-mwa4bxzz-w`，HTTP 200，SQL=3。

ABC raw 请求的实际参数是：

```text
time_from=2026-10-20 18:33:00.001
time_to=2026-10-20 18:34:59.999
radio=1
exact_ap=true
link_role=ACTIVE
include_zero=false
exclude_depot=true
exclude_parking=true
raw_samples=true
include_context=true
raw_max_rows=50000
page_size=1000
mesh_trace=true
mesh_operation_id=mesh-op-mwa4bxzz-w
```

这不是完整 A+B+C 重查。第七轮增加的后端 `sql_query_ranges` 对该请求给出：

| purpose | time_from | time_to | visible | record_count |
|---|---|---|---|---:|
| target_count | 18:33:00.001 | 18:34:59.999 | false | 181 |
| target_rows | 18:33:00.001 | 18:34:59.999 | true | 181 |
| boundary_context | null | 18:33:00.001 | false | 1 |

`boundary_context` 是每个 raw 查询为跨区间 Counter/Link Continuity 提供的前置采样；它带有 `is_boundary_context=true`，不可见、不计入 `total`，没有扩大为 A 或 C。

## 一次性参考与逐字段比较

使用相同 identity 直接请求一次性窗口 `18:30:00.000–18:38:00.000`，operation id=`comparison-full`，HTTP=200、SQL=3、target rows=723、boundary context=1、items=724。renderer 内使用同一 `deriveMeshRawSamples` 对 segmented cache 和 full reference 比较：

```text
segmented raw rows       = 724
segmented visible/derived = 723
one-shot raw rows        = 724
one-shot visible/derived = 723
equal                   = true
firstMismatch           = null
```

比较的稳定原始字段：

`record_id,timestamp,source_file_id,local_radio,peer_mac,peer_ap_mac,link_role,link_count,local_tx,peer_tx,local_rx,peer_rx,local_retry,peer_retry,local_err,peer_err,monitor_gap_before`

比较的派生字段：

`current,previous,delta,interval_seconds,per_second,status`，覆盖 12 个 counter 字段 `local_tx,peer_tx,local_rx,peer_rx,local_retry,peer_retry,local_err,peer_err,local_tx_garp,peer_rx_garp,local_tx_mul_join,peer_rx_mul_join`。

第二次对完全相同 ABC 窗口的真实 Electron 调用在当前 trace 中没有新增事件；raw counters 从 HTTP=10/SQL=18 保持为 HTTP=10/SQL=18，增量为 0/0。

## 判定

`GAP_FILL_STRICT=PASS`：实际 raw 业务查询只覆盖 B，允许的 context 明确为不可见前置边界行；分段与一次性结果数量、稳定字段和派生字段一致；重复请求为 HTTP=0、SQL=0。

## 边界覆盖说明

毫秒边界、部分重叠、逆序/多段规划、Counter reset、链路切换和 LRU 行为由现有 raw cache/continuity/gap-fill 单元及 Python MESH 回归覆盖；本轮真实 Electron 主证据集中于 A/C/中间 B 和重复 ABC，不把单元测试伪装成额外真实 HTTP 证据。
