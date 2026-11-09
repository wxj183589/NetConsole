# Phase 11.7 Electron UI 验收

结论：`ELECTRON_UI_STATUS=NOT_RUN`。

## 环境检查

- 指定真实数据根：`D:\NetConsoleData-dev`；宁波地铁12号线 Site 存在，列车01-MR-CW 解析库文件存在。
- 初始端口探测未发现 NetConsole Backend / Vite 监听端口；没有复用已运行的 Electron 窗口。
- 当前源码 `pnpm dev:codex` 是 persistent development runtime。启动 Backend 会执行数据库初始化；源码数据库 initialize 包含 WAL 初始化、schema scripts 与 additive updates。此次没有在真实库上证明启动绝不写 schema/数据库，因此未对真实库启动。
- 本轮没有可用的 Electron 原生窗口自动交互/截图通道；Chromium/静态组件测试不作为 Electron 截图证据。

## 验收结果

任务书要求的 17 项实际操作均为 `NOT_RUN`：四个业务入口、切换 AP/Radio/时间范围、双端趋势和 Tooltip、Shift固定、Ctrl浏览、AP历史详情、GARP/MulJoin、列设置批量应用、LinkCnt=0、RSSI跳转、Excel导出、加载状态。没有创建或冒充当前源码截图。

Phase 11.1/11.3 等历史报告中的 Electron 截图只列为历史参考，不满足 Phase 11.7 当前源码验收。

解除条件：先用 MESH 专用的、不会对真实 Authority 执行初始化写入的受控只读运行方案启动当前源码 Electron，并提供桌面窗口交互/截图能力；确认该方案不会应用数据库迁移后再执行。不得将 `RuntimeMode.TEST` 空库截图或 mock 数据说成宁波真实数据验收。
