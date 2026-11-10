# Gap Fill E2E

## 结果

真实 Electron 中观察到 raw cache 从已有窗口向前扩展：主运行先有 `18:37:06.381–18:42:06.381`，随后 wheel/拖动触发 `18:35:51.381–18:42:06.381` 的缺口判断。trace 明确记录 `raw_samples` 的 `gap`、`missing raw coverage`，并记录缺口区间请求的 operation id。

补充运行等待所有异步请求完成后取得稳定状态：

- window：`2026-10-20 18:35:51.381 – 18:42:06.381`。
- completed metrics：13/13。
- raw cache：1 scope、571 samples、1 covered interval。
- raw counters：HTTP=2、SQL=6、cache hits=17、gap queries=2。
- selected timestamp 和主链路详情仍然存在。
- 证据截图：`08-gap-fill-completed.png`。

## 连续性判断

已有区间、缺口检测、补取后的合并 cache 和 chart/detail 结果均可见，说明 A+C 到更宽窗口的连续性路径被真实执行。当前 trace 没有把每一个 raw row 以 A/B/C 分段及唯一补取集合导出，因此不能严格证明“只补 B、没有重查 A/C”。本项保持 `PARTIAL`，不伪造为 PASS。
