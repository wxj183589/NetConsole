# 真实 Electron 定向验收

## 可重复入口

从 Electron package 目录运行，不使用固定 PID：

```powershell
cd D:\study\NetConsole-Workspace\NetConsole\apps\desktop_electron
$env:NETCONSOLE_DEV_PORT='5192'
$env:NETCONSOLE_DEV_BACKEND_PORT='8132'
$env:NETCONSOLE_DEVTOOLS_PORT='9223'
pnpm run dev:codex -- --isolated-test-data D:\study\NetConsole-Workspace\test-data\NetConsole\mesh-phase11-8-run-001
```

第七轮为 `dev.mjs` 增加了可选 `NETCONSOLE_DEVTOOLS_PORT`；默认不启用，开发/验收时才打开 CDP。入口支持独立数据根、指定 MESH session、真实鼠标/键盘、HTTP trace、raw coverage 和生命周期快照。两次实际运行均由本轮启动并通过已知父进程树安全停止，未关闭其他任务进程。

## 真实运行结果

- Electron/Vite/backend/SQLite 全部来自当前源码；运行根为 `mesh-phase11-8-run-001`，没有使用 `D:\NetConsoleData-dev` 作为 runtime root。
- 首次主链路加载后滚动到 13 个图表，14 个业务字段可见；raw 目标 465 条、boundary context 1 条，页面错误和 console error 为 0。
- 第六轮已有的 30 分钟/117 次操作证据继续作为长稳基线；第七轮补做低层真实 fetch trace、缓存差值、A/C/ABC 范围、重复 ABC 和生命周期计数，没有把短测冒充新的 30 分钟长稳。
- 真实操作覆盖：普通滚轮放大/缩小、不同图表滚轮、页面外滚动、tooltip/counter tooltip、Shift 固定、Ctrl 浏览、Esc、右侧详情、AP/Radio、历史/建链页面复用和离开返回；已完整缓存的操作没有新的 raw/data HTTP 或 SQL。

## 热缓存与 gap

5 次页面工作台循环的热缓存数据增量为 HTTP=0、SQL=0；唯一额外 trace 是未预加载的 links page 请求，单独归为分页 miss。

A/C/ABC 的 raw 请求实际只补 B，SQL ranges、context 和 full-vs-segmented 对照见 `GAP_FILL_STRICT_ACCEPTANCE.md` 与 `GAP_FILL_EVIDENCE.json`。同一 ABC 窗口第二次真实调用的 raw counters 从 HTTP=10/SQL=18 保持为 HTTP=10/SQL=18，新的 trace event=0。

## 运行时边界

- 页面退出后 `active_count=0`，无遗留 MESH 请求。
- 生命周期完整计数见 `ECHARTS_LIFECYCLE_EVIDENCE.json`；离开工作台后 active ECharts、Canvas、listener、ResizeObserver 全部为 0。
- 第七轮不新增现场设备、Excel/WPS GUI 或 125% DPI 验收；这些不影响本轮已完成的 MESH 缓存专项证据，但仍不是最终产品发布许可。
