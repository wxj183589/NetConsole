# 本地 Electron GUI 证据

状态：`PARTIAL`；交互式人工 GUI 验收未完成，现场验证：`FIELD_VALIDATION_PENDING`。

## 实际尝试

1. 直接 `pnpm run dev:codex` 启动了 Electron，但该入口在当前配置下解析到 `D:\NetConsoleData\runtime\electron\user-data`，不满足本轮隔离数据要求；已立即停止，未继续点击或写入业务数据，不将其计为通过。
2. 使用 `pnpm exec node scripts/dev.mjs --codex --smoke` 重新执行隔离启动。日志确认 `Isolated temporary test runtime`，backend、Vite、Electron 均 ready，随后 smoke 正常输出 `SHUTDOWN_STARTED`、`BACKEND_STOPPED`、`EXIT_RETURNED`，临时根由编排器回收。

## 结论

隔离 Electron 启动/关闭链路通过，不能等同于 1920×1080/2560×1440 下的人工点击验收。未用 Vitest 冒充 GUI 页面通过；静态台账筛选、AC 离线显示、导入预览等仍需要真实桌面人工检查。
