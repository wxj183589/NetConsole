# E3 Codex 本机开发运行时归档

日期：2026-07-18
状态：自动验证通过；Playwright E2E 待独立阶段

## 目标

在不增加浏览器产品、不关闭鉴权、不开放局域网的前提下，让 Codex 和本机浏览器自动化能够观察同一套 Vue、FastAPI 与 Electron 运行时。

## 已实现

- `pnpm dev:codex` 统一启动 Vite、Electron 和受管 Python Backend。
- Vite 固定绑定 `127.0.0.1:5173`，开发 Backend 固定绑定 `127.0.0.1:8000`；端口占用时失败关闭。
- 每次启动生成随机 Session Token，通过 Electron Main 的 stdin 握手交给 Python；Backend 子进程环境和日志不含 Token。
- 开发数据使用系统临时目录 `NetConsole-Codex-*`，退出时只对严格校验的临时路径递归回收。
- Browser Adapter 只在 Vite 开发编译中接收 Token，并通过 `/api/dev/session` 建立 HttpOnly、SameSite Strict Cookie。
- `/api/dev/runtime-status` 只在受保护 Desktop 开发运行时注册，要求有效 Session 与回环来源，数据根固定返回 `<redacted>`。
- 生产运行时继续使用动态回环端口，不注册开发 API/OpenAPI，不读取开发 Session 或固定端口。

## 自动验证

- Python Electron Runtime 定向测试：22 项通过。
- Python 改动范围 Ruff：通过。
- Vue Vitest：58 个文件、180 项通过。
- Electron Vitest：13 个文件、85 项通过。
- Electron TypeScript typecheck、main/preload build：通过。
- `scripts/dev.mjs --codex --smoke` 连续两次通过；第二次无 Vite 首次依赖优化告警。
- 固定端口不一致、非回环 Token Origin、冻结 Runtime `--dev-mode` 和临时目录越界均有失败关闭测试。
- 注入生产构建 Token 哨兵后重建 Vue，`dist` 不含该哨兵。
- 正常退出、Backend 启动失败和 Windows `pnpm dev:codex` Ctrl+C 均验证新临时目录不残留；Electron Main 与编排脚本共同承担严格前缀的数据根回收。
- 退出后 `127.0.0.1:5173`、`127.0.0.1:8000` 无监听，未发现受管 Electron/Vite/Python 残留。

## 未完成边界

- 尚未增加 Playwright 浏览器 E2E 与 Electron E2E 脚本，因此本阶段不声称 E2E 通过。
- 本接口仅用于本机开发诊断，不是公开 API、远程管理入口或客户 Browser 产品。
- 不提供任意 Shell、SQL、文件路径、环境变量、凭据或鉴权绕过接口。
