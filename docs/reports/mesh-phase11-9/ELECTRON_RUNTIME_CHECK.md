# Electron Runtime Check

日期：2026-11-10

## 运行证据

### 隔离 smoke

命令：`pnpm run smoke:dev`（`apps/desktop_electron`）。

- Electron 主进程/Preload 构建完成；
- Vite HTTP ready、warmup ready；
- smoke 输出 `SHUTDOWN_STARTED`、`BACKEND_STOPPED`、`EXIT_REQUESTED`、`EXIT_RETURNED`；
- 使用自动清理的临时隔离 runtime，未访问真实数据根。

### Codex development runtime

命令：`pnpm run dev:codex -- --isolated-test-data <Workspace test-data root>`。

- 输出 `NetConsole Codex development runtime ready`；
- `Runtime mode: electron-development`；
- 主窗口 PID `54916`，读取到窗口矩形 `left=20, top=20, width=1920, height=1080`；
- 启动时主显示器工作区为 `2560×1600`，随后把该隔离 Electron 窗口调整为验收目标 `1920×1080` 并复读矩形；
- 进程由验收脚本手动终止，显式隔离根已确认无 Electron 进程后删除。

## 结论

`ELECTRON_RUNTIME_STARTUP=PASS`，`ELECTRON_WINDOW_1920x1080=PASS`。由于隔离根为空，本次没有加载宁波12号线真实 MESH 工作台、没有截图或 GUI 业务点击，因此 `REAL_MESH_ELECTRON_WORKBENCH=PENDING`，不能把 runtime startup 写成完整 GUI 验收。
