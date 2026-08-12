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
- `main-window-startup.ts`：新进程主窗口的当前主显示器定位、最大化、显示和聚焦。
- `workspace-layout-store.ts`：当前进程内的导航快照与窗口记录；启动时精准清理旧 `workspace-layout.json`，不跨进程恢复标签或窗口。

## 依赖关系

Main 依赖 `../shared/` 的强类型 DTO，与 Vue 仅通过 preload bridge 通信；Python Core 由受管进程提供 FastAPI，不导入 Node 业务实现。

## 数据与状态

临时会话令牌只存在于进程和受控临时通道，不写日志、URL、SQLite 或仓库。主题持久化属于 Python/FastAPI 系统设置。

系统设置工具选择器只接收共享契约中的语义 `toolId`，过滤器和 basename 白名单由 Main 派生，Renderer 不能提供扩展名或 allowlist。PuTTY 允许大小写不敏感的 `putty.exe`、`putty64.exe`；选择后 Main 先复验绝对路径和文件名，Python 保存及实际启动前再验证存在性、普通文件、非符号链接和终端类型匹配。

局点/数据根 IPC 只允许原生目录、`.ncsite` 和导出路径选择，以及停稳后的 Backend 存储重配置；复制、SQLite、压缩、解压和校验仍由 Python Worker 执行。

## 测试

主题和安全边界由 `../../tests/config.test.ts`、`ipc.test.ts`、`preload.test.ts`、`renderer-theme-display-gate.test.ts` 覆盖；修改 Main 后还需运行 Electron typecheck、测试和 main/preload 构建。

## 修改规则

BrowserWindow 创建时保持隐藏。新进程的主窗口不接收历史坐标或尺寸，首次 `ready-to-show` 按当前 Windows 主显示器工作区定位并以保留系统边框的最大化窗口显示和聚焦；托盘恢复同一窗口时不重复该初始化。随后显示跟随 `nativeTheme` 的受控启动页，保证 Python Core 较慢或失败时仍可观察。业务 Renderer 导航受主题显示门约束：真实系统设置解析后只可报告 `light`/`dark`，Main 先更新发信窗口背景，再结束显示门；超时和失败先加载受控错误页。错误页重试不携带 Renderer URL，也不经过 preload/Renderer IPC；Main 只接受来自当前受管错误页的一次固定动作，再从按窗口保存的 Main-owned 目标中恢复主窗口或附加工作区窗口，重新校验 loopback 地址、重置错误协调器并布防显示门。任务中心只存在于 Vue 根布局和主工作区，不创建专用 BrowserWindow。Main 拒绝 `auto`、强调色、任意颜色或附加窗口参数，不读取或持久化第二份主题。Renderer 颜色事实源始终位于 `apps/desktop_renderer/src/theme/`。

## 生成与清理

构建输出位于被忽略的 `dist/`；关闭应用必须清理受管 Backend、下载和子窗口，不在本目录生成运行数据。

## 相关文档

- [Electron Desktop](../../../../docs/architecture/DESKTOP.md)
- [Native Bridge](../../../../docs/architecture/NATIVE_BRIDGE.md)
- [外部终端白名单](../../../../docs/external-terminal/README.md)
