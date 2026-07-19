# Electron Main

## 用途

本目录承载 Electron 窗口、受管 Python Backend 生命周期、下载、单实例和安全 IPC。

## 边界

Main 不执行设备命令、数据库查询、Parser、报告或业务状态机；Renderer 只能调用白名单 IPC，不能传任意路径、程序或窗口参数。

## 主要入口

- `index.ts`：应用与窗口生命周期。
- `backend-manager.ts`：受管 Backend 启停和健康检查。
- `ipc.ts`、`security.ts`：白名单 IPC 和发信方校验。
- `config.ts`：开发/生产配置与加载期背景色镜像。
- `bootstrap.ts`：在 Electron userData 中原子保存数据根和当前局点，不保存凭据。
- `renderer-theme-display-gate.ts`：持久化主题解析、超时和 Renderer 失败的有界显示门。

## 依赖关系

Main 依赖 `../shared/` 的强类型 DTO，与 Vue 仅通过 preload bridge 通信；Python Core 由受管进程提供 FastAPI，不导入 Node 业务实现。

## 数据与状态

临时会话令牌只存在于进程和受控临时通道，不写日志、URL、SQLite 或仓库。主题持久化属于 Python/FastAPI 系统设置。

局点/数据根 IPC 只允许原生目录、`.ncsite` 和导出路径选择，以及停稳后的 Backend 存储重配置；复制、SQLite、压缩、解压和校验仍由 Python Worker 执行。

## 测试

主题和安全边界由 `../../tests/config.test.ts`、`ipc.test.ts`、`preload.test.ts`、`renderer-theme-display-gate.test.ts` 覆盖；修改 Main 后还需运行 Electron typecheck、测试和 main/preload 构建。

## 修改规则

BrowserWindow 创建时保持隐藏，随后显示跟随 `nativeTheme` 的受控启动页，保证 Python Core 较慢或失败时仍可观察。业务 Renderer 导航受主题显示门约束：真实系统设置解析后只可报告 `light`/`dark`，Main 先更新发信窗口背景，再结束显示门；超时和失败先加载受控错误页。错误页重试不携带 Renderer URL，也不经过 preload/Renderer IPC；Main 只接受来自当前受管错误页的一次固定动作，再从按窗口保存的 Main-owned 目标中恢复主窗口或带筛选上下文的任务窗口，重新校验 loopback 地址、重置错误协调器并布防显示门。Main 拒绝 `auto`、强调色、任意颜色或附加窗口参数，不读取或持久化第二份主题。Web 颜色事实源始终位于 `apps/web/src/theme/`。

## 生成与清理

构建输出位于被忽略的 `dist/`；关闭应用必须清理受管 Backend、下载和子窗口，不在本目录生成运行数据。

## 相关文档

- [Electron Desktop](../../../../docs/ELECTRON_DESKTOP.md)
- [Native Bridge](../../../../docs/DESKTOP_NATIVE_BRIDGE.md)
