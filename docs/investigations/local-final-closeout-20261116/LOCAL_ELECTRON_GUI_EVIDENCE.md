# Electron 本地启动与 GUI 证据

状态：GUI_BLOCKED；启动链路 PASS

已执行 `pnpm exec node scripts/dev.mjs --codex --smoke`，并使用独立临时根启动 Vite、Backend 和 Electron；输出确认 Runtime Mode 为 `isolated_test`，站点数据、Electron userData、Backend database、日志和临时目录均位于任务隔离根。Smoke shutdown completed。

另执行一次不带 `--smoke` 的 `pnpm run dev:codex`，Vite、Backend、Electron 均完成启动并打印隔离路径，随后按用户取消全量验证的范围停止。停止产生的交互式退出码不作为启动失败。

当前环境没有可用的 Windows 原生窗口/屏幕采集工具，因此无法提供页面点击、窗口布局、Hover、滚动、Resize 或真实 Electron GUI 截图证据。Smoke 启动不等同于 GUI 验收；GUI 现场检查保留为 BLOCKED/PENDING。

已验证：Electron runtime 定向测试 19 passed，Electron typecheck PASS，Renderer vue-tsc PASS，Vite build PASS（仅有大 chunk 警告）。本轮不执行安装包构建。
