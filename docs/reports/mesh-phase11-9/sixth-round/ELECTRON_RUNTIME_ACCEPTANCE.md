# NetConsole MESH Phase 11.9 第六轮：真实 Electron 全工作台验收

## 结论

`PHASE_11_9_SIXTH_ROUND=PARTIAL`。

实际启动了 Electron 主进程、Renderer、FastAPI backend 和真实 SQLite。目标会话、全工作台、13 个 ECharts 面板、14 个业务字段、AP 情况、页面重入和 30 分钟稳定性均有证据；但本轮不宣称整体 PASS，原因是运行时更新了隔离快照的 MESH catalog、采样器没有记录 `mtime_ns`，以及 gap-fill 的“只补 B 区间”未能从现有 trace 单独证明。

## 运行边界

- 目标会话：`80716c07-6bd9-47d8-b76d-ace1e55624d1:1`（宁波地铁12号线，列车01-MR-CW）。
- 运行快照：`D:\study\NetConsole-Workspace\test-data\NetConsole\mesh-phase11-8-run-001`。
- 真实开发数据：`D:\NetConsoleData-dev`；运行时未使用，仅读取做前后指纹对照。
- Electron 运行环境：`NETCONSOLE_STORAGE_MODE=isolated_test`、`NETCONSOLE_RUNTIME_MODE=test`。
- 主验收 Electron PID：`46580`，补充截图 Electron PID：`52192`。
- 采样时源码提交：`de7ca957d371cd8bc29b60d05f69f4c85d8b2190`，工作树带并行 dirty 修改。
- Native window：`1920x1080`，窗口坐标 `(24,24)`；Renderer viewport `1904x1041`，DPR `1`。

## 工作台结果

所有 14 个业务字段均出现于实际页面与详情内容：RSSI、CPU、Memory、TxBusy、RxBusy、Rate、Noise、TxDesFreeCnt、Tx、Rx、Retry、Err、GARP、MulJoin。实现以 13 个 ECharts 面板呈现，其中 `Tx / Rx` 是一个双序列面板，因此页面状态为 `13/13 图表完成`，不虚报为 14 个独立 chart。

主链路监控在真实滚动后达到 13/13 `COMPLETED`，Canvas 数量为 13；详情表同时显示 14 个字段。补充运行完成 gap-fill 后重新取得 13/13，并捕获 `08-gap-fill-completed.png`。AP 页面实际显示备用链路、Radio 1 和 853 条统计记录，捕获 `09-ap-radio-switch.png`。

## Gate 矩阵

| Gate | 结果 | 证据/边界 |
|---|---|---|
| Electron + Renderer + backend + SQLite 真运行 | PASS | PID、端口、隔离快照和请求 trace 在 `sixth-round-runtime-evidence.json` |
| 14 字段及 lazy chart | PASS（表示层） | 13 chart panels + Tx/Rx 双序列；页面显示 13/13，详情包含 14 字段 |
| 真实 HTTP/SQL trace | PARTIAL | 94 MESH HTTP、9 SQL，13 条 request record 为 FAILED/取消过渡 |
| 缓存区间交互 HTTP=0/SQL=0 | PASS（缓存动作） | 主运行 chart wheel、tooltip、Shift/Ctrl/Esc、详情动作均记录 0/0；区间扩大触发 gap miss，不属于缓存命中 gate |
| >=100 鼠标/键盘交互 | PASS | 30 分钟稳定性阶段 117 次真实交互，另有 35 项主动作 ledger |
| A+C→A+B+C 只补 B | PARTIAL | 真实 gap 缺口和合并结果可见；当前 trace 未对 B 的唯一补取作可审计归因 |
| Cold/Warm 性能 | MEASURED | warm-1 16.868s、warm-2 16.802s、cold reload 20.440s |
| 30 分钟 Heap 长稳 | PARTIAL | 30 samples、117 interactions、0 page/console error；ECharts 实例数和 listener 数无法直接观测 |
| 快照数据完整性 | PARTIAL | 目标 DB/raw/parsed 输入 SHA 与 size 未变；catalog SHA 发生变化，`mtime_ns` 未记录 |
| MESH 自动化回归与构建 | PASS | 491 Python、330 Renderer、Ruff、compileall、main build 全部通过 |
| Workspace 全量布局检查 | PARTIAL | 本轮临时 harness 已退役；检查仍被既有 `D:\study\NetConsole-Workspace\docs` 顶层目录阻断 |

详细证据见同目录的 HTTP/SQL、交互、gap、性能、Heap、数据完整性和回归报告。

