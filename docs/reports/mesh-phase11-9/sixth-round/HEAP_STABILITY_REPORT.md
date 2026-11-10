# Heap Stability Report

## 30 分钟结果

- 运行时长：1803 秒，30 个 minute samples。
- 稳定性阶段真实交互：117 次。
- JS heap used：min `227,101,990` bytes，P50 `516,101,716` bytes，P95 `557,456,233` bytes，max `558,780,314` bytes。
- Canvas 数量：所有 minute sample 均为 13。
- 每分钟 `inflight_mesh_requests=0`、`cancelled_trace_events=0`。
- 每分钟 uncaught page errors=0、console errors=0。
- ECharts instance 数：当前 harness 不可直接观测。
- event listener 数：当前 harness 不可直接观测。

## 进程峰值

按稳定性采样进程树的最大值：

- Electron child processes：private `959.94 MB`，working set `1031.06 MB`。
- Python backend processes：private `1243.28 MB`，working set `523.48 MB`。
- backend 子进程中观察到随运行启动的 `fping.exe`，最大 private `6.77 MB`；未修改独立 `D:\study\fping` 项目。

## 结论

在可观测指标范围内，30 分钟没有错误、inflight 泄漏或 Canvas 数量增长；由于 ECharts instance 和 listener 数不能从当前 Electron probe 直接读取，Heap gate 为 `PARTIAL` 而非 PASS。
