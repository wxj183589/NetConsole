# NetConsole 本地 Electron 开发运行根隔离报告

状态：`PASS`（代码、隔离 smoke 和真实 `dev:codex` 启停）；真实业务数据与现场设备：未访问。

## 修改范围

- `apps/desktop_electron/scripts/dev.mjs`：`--codex` 纳入隔离判定，启动日志明确打印 Runtime、Storage、Site、Electron、Backend、Log、Temp 根。
- `apps/desktop_electron/scripts/dev-runtime.mjs`：默认 Codex 运行根、显式根、路径真实解析、前缀路径、符号链接/重解析点和正式数据根 fail-closed 校验。
- `apps/desktop_electron/src/main/development-data-root.ts`：Electron Main 与 launcher 使用同一真实路径边界检查。
- `apps/desktop_electron/scripts/dev-runtime.test.mjs`、`apps/desktop_electron/tests/development-data-root.test.ts`：默认、显式、重复启动、清理、兄弟前缀和重定向根回归。

## 实际运行证据

`pnpm exec node scripts/dev.mjs --codex --smoke`：`PASS`。

本次实际打印的隔离根均为：

```text
D:\study\NetConsole-Workspace\test-data\NetConsole\electron-<run-id>
```

五类子根均位于该目录：

```text
Site Data Root       = <run-root>
Electron UserData    = <run-root>\runtime\electron\user-data
Backend Database     = <run-root>\sites
Log Root             = <run-root>\runtime\logs
Temporary Root       = <run-root>\runtime\temp
```

`pnpm run dev:codex` 实际启动 Vite、Electron 和 Backend，打印 `Runtime mode: electron-development`。随后用 Ctrl+C 结束交互进程；PowerShell 返回码为 1，这是终止交互进程的退出码，不是启动失败。未发现本次 run-id 残留的 electron 临时根。

## 防护结论

- 无参数普通开发仍为 `persistent`；`--codex`、`--smoke`、Task Center smoke、Workspace Tray smoke 和显式隔离根均为 `isolated_test`。
- `D:\NetConsoleData`、`D:\NetConsoleData-dev`、`G:\NetConsoleData` 及其子路径不能作为隔离根。
- `test-data` 的兄弟前缀路径、符号链接/重解析点重定向路径均拒绝。
- Python、Backend、Electron UserData、日志和临时目录从同一个隔离根派生，不回退到生产或真实开发根。
- `PRODUCTION_DATA_MODIFIED=0`；`DATABASES_REMOVED=0/0`；未创建完整真实数据副本。

## 验证

```text
Electron Vitest targeted: 19 passed
Electron typecheck: PASS
dev:codex --smoke: PASS
dev:codex startup/shutdown: STARTED, GUI interaction not exercised
```
