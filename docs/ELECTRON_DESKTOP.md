# Electron Desktop 基础架构

## 统一任务窗口

Electron 复用同一 Vue Renderer、FastAPI 会话和 `TaskApplicationService -> TaskRepository -> tasks.db`，提供单实例任务窗口。主窗口只通过严格的 `taskId/module/status` DTO 打开或恢复该窗口；关闭窗口仅隐藏，不取消后台任务，应用退出时再与主窗口、受管后端一并有序关闭。

任务动作以后端 owner capability 为准。未授权动作保持禁用并说明原因；Artifact 只携带不透明标识和受控 API 请求，经既有 Electron 流式下载、临时文件及原子替换保存，不向 Renderer 暴露服务端绝对路径。

## 当前状态

Electron Desktop 安全基础已在 `apps/desktop_electron/` 建立，复用唯一 Vue Renderer `apps/web/` 和唯一 FastAPI 组合根 `src/netconsole/backend/api/main.py:create_app()`。当前正式处于 **Electron 与 Qt 并行迁移阶段**：Qt 仍是生产与回退入口，Electron 是可运行的新宿主基础；这不是安装包发布完成，也不表示任何 Qt 业务模块已经达到替换门槛。

当前并存关系：

```text
apps/desktop/              当前 Qt Web Shell，Legacy/生产回退
apps/desktop_electron/     Electron main/preload/shared，目标桌面外壳基础
apps/web/                  唯一 Vue Renderer；Electron 正式使用，浏览器仅开发联调
src/netconsole/            唯一 Python Core/FastAPI/Application Service
```

Qt 目录本阶段不移动、不改名、不删除。Electron 没有复制 Vue 页面、Python Service、Repository、Parser、Agent、Online MR 或报告逻辑。

## 运行架构

```mermaid
flowchart TD
    EM["Electron Main"] --> PM["PythonBackendManager"]
    PM -->|"参数数组；shell=false"| PY["Python Electron Runtime Adapter"]
    PY --> API["现有 FastAPI create_app"]
    API --> AS["Application Service / Repository / Infrastructure"]
    EM --> PRE["sandboxed preload + contextBridge"]
    PRE --> VUE["apps/web Vue Renderer"]
    VUE -->|"Runtime Adapter: REST / WebSocket"| API
    VUE -->|"安全下载 DTO"| PRE
    PRE -->|"固定 IPC"| EM
    EM -->|"动态 Origin + 内存令牌；流式响应"| API
    BROWSER["开发诊断浏览器"] -.-> VUE
```

职责固定为：

| 层 | 当前职责 | 禁止事项 |
| --- | --- | --- |
| Electron Main | 窗口、Python 子进程、动态端口、会话令牌、CSP、导航和白名单 IPC | 设备、采集、解析、数据库、报告或 Agent 业务 |
| preload | 将固定方法逐个映射到固定 IPC channel | 暴露 `ipcRenderer`、Node `process`、`fs` 或通用 invoke/send |
| Vue | 页面、状态、表单、REST/WebSocket；正式运行使用 Electron Adapter，Browser Adapter 仅作开发诊断兼容 | 直接访问 Node、持久化 Electron API Token、为浏览器另建业务页面或验收链 |
| FastAPI | 鉴权、DTO、Router、静态 Vue、Application Service 组合根 | 复制业务规则或建立 Electron 专属业务 Core |
| Application Service | 原有业务用例、Task/Session/Artifact、采集、报告和存储 | 依赖 Electron、Vue 或 Qt 控件 |

## 开发模式

先准备两个独立前端工作目录的依赖：

```powershell
cd apps/web
pnpm install --frozen-lockfile
cd ../desktop_electron
pnpm install --frozen-lockfile
```

项目根存在 `.venv` 时直接启动：

```powershell
cd apps/desktop_electron
pnpm dev
```

`pnpm dev` 先检查并打包 Electron main/preload，再确认固定回环端口 `5173` 未被占用、启动 Vite dev server，最后启动 Electron；端口冲突时直接失败，不能误连其他 worktree 的 Vite。Electron 自己选择 Python 动态端口，因此 Vite 的 `5173` 与 FastAPI 端口没有绑定关系。Vite 中固定的 `/api`、`/ws` 代理只服务普通 Browser 开发；Electron 的 REST、WebSocket 和下载全部从 Runtime Config 读取受管动态 Origin，不经过固定 `127.0.0.1:8000`。独立 Git worktree 可通过开发机环境变量 `NETCONSOLE_PYTHON` 指向同一项目虚拟环境；该路径不会进入 Renderer、日志或版本化配置。

Electron/Vue 的产品标题统一为 `NetConsole`，侧栏使用“本地网络运维控制台”；内部迁移阶段文案不进入正式界面。

自动开发冒烟：

```powershell
cd apps/desktop_electron
pnpm smoke:dev
```

冒烟只有在 Electron、Python、Vue runtime adapter 和真实 `/api/health` 全部成功后才以 0 退出，并检查退出链能够回收 Vite、Electron 和 Python。

## 生产资源模式

源码环境可验证生产资源加载逻辑：

```powershell
cd apps/desktop_electron
pnpm build
pnpm start
```

`pnpm build` 构建单文件 main/preload 和 `apps/web/dist`；`pnpm start` 启动 Electron 与本机 Python，由 FastAPI 在同一动态回环 Origin 提供已构建的 Vue 静态资源。Electron 不使用第二套 Renderer，也不把临时令牌放入页面 URL。

当前尚未建立 Electron 安装包、冻结 Python backend bundle、代码签名、自动升级或发布白名单；现有 PyInstaller/Nuitka Qt 发布链保持原样。正式 Electron 安装包必须另立发布任务，不得把源码 `.venv` 当作交付依赖。

## Python 后端生命周期

`PythonBackendManager` 的状态为 `starting -> ready -> stopped|failed`，并提供幂等 `start()`、`waitUntilReady()`、`getRuntimeInfo()`、`getStatus()` 和 `stop()`：

1. Electron 启动受管 Python，并要求后端直接绑定 `127.0.0.1:0`；Python 在持有监听 socket 后通过 stdout 结构化事件回报实际端口，避免“预选后释放”的抢占窗口。
2. 每次启动生成新的高熵、URL-safe 临时令牌。
3. 使用可执行文件和参数数组启动 `netconsole.backend.electron_runtime`，固定 `shell: false`、`windowsHide: true`、`127.0.0.1` 和端口 `0`。
4. 令牌只通过已持有子进程的 stdin 首行 JSON 传递；不进入参数、环境变量、URL 或配置。
5. Electron 先校验受管子进程管道返回的 `127.0.0.1:<port>`，再使用临时请求头轮询真实 `/api/health`，成功后才加载正式 Vue 页面。
6. stdout/stderr 按行写入 Electron 日志，先移除令牌和常见敏感字段。
7. 正常退出时 Main 通过同一 stdin 控制管道发送 `shutdown`，Python 控制线程据此请求 Uvicorn 优雅退出；父进程异常导致管道 EOF 时，Python 同样请求退出。
8. Python 只在 `uvicorn.Server.run()` 完全返回后发送 `netconsole.electron_backend.shutdown_ack`，随后等待 Main 的 `exit`；Main 收到该确认后才发送 `exit` 并关闭控制管道。
9. 只有优雅停止确认超时才对本管理器持有的子进程句柄发送终止信号；不按名称扫描或误杀其他 Python。
10. 后端意外退出或强制终止后仍未退出时状态变为 `failed`，只向当前受信 Renderer 发送脱敏状态事件，不谎报 `stopped`。

桌面总退出是单一受管屏障：先等待 Desktop IPC 的下载清理，再完成上述 Python `shutdown_ack -> exit` 握手，最后清空会话路径授权；这些步骤结束后才销毁窗口、释放单实例锁并退出 Electron。Windows 下不依赖可能缺失的 child `exit/close` 事件来判定 Uvicorn 是否已经停止。

## 本地 API 安全模型

- FastAPI 只监听 `127.0.0.1`。
- Electron HTTP 请求携带 `X-NetConsole-Session`；原 Qt WebHost 的 `POST /__desktop_session` 和 HttpOnly Cookie 兼容链继续有效。
- Electron 主进程使用非持久化的内存 Session。开发态 Cookie 仅匹配后端 `/ws`，供 WebSocket 自动携带且不发送给普通 Vite/REST 请求；生产态 Vue 与 API 同源，Cookie 匹配 `/` 以便加载受保护的首页和静态资源。两种模式均为 HttpOnly、SameSite Strict，令牌不进入 WebSocket URL，进程退出后 Session 一并销毁。
- 开发态 CORS 只允许命令行校验后的精确 `http://127.0.0.1:<Vite 端口>`；生产态 Vue 与 API 同源。
- Vue 只在模块内存保存 `apiBaseUrl`、`apiToken` 和宿主类型；不写 `localStorage`、`sessionStorage`、URL 或 Pinia 持久化状态。
- 临时令牌用于本机桌面会话，不替代 Agent Token、用户登录、角色权限或业务写操作审计。
- Renderer 被完全攻陷时仍能使用其当前内存令牌，因此 CSP、导航限制、上下文隔离、preload 最小化和短生命周期必须共同成立。
- Electron Runtime Config 初始化未完成或失败时，Vue 拒绝把 REST/WebSocket/下载静默降级为相对 `/api`；普通 Browser 模式才允许相对路径和 Vite 代理。

## Electron 安全默认值

正式 BrowserWindow 固定：

```text
nodeIntegration: false
contextIsolation: true
sandbox: true
webSecurity: true
webviewTag: false
partition: non-persistent in-memory session
```

同时执行：

- preload 使用 esbuild 打成单文件，适配 sandboxed preload 的受限 `require` 环境；
- 阻止所有新窗口和 `<webview>`；
- 主窗口同时拦截普通导航和服务端重定向，只允许已登记的精确 Renderer 回环 Origin，且同源 `/api`、`/ws` 与桌面会话路径也不得替换 Vue 页面；
- 拒绝 Renderer 权限请求；
- 生产 CSP 不包含 `unsafe-eval`，开发 CSP 只为 Vite 开放该项；
- `object-src 'none'`、`frame-ancestors 'none'`，`connect-src` 只包含当前回环 Renderer/API/WebSocket Origin；
- IPC 在 main 再次校验参数，并核对发送者必须是当前主窗口的 main frame，且 frame URL 仍属于已登记回环 Origin。
- 所有新窗口继续拒绝；设备 Web 管理地址只能通过独立 `openExternalUrl` 白名单动作交给系统浏览器，拒绝 HTTP、凭据 URL 和 Renderer 任意导航。
- Electron 内存 Session 一律拦截 Chromium `will-download`；合法文件只能走 `downloadBackendResource` 的原生保存确认与 main 流式链，不能用 `<a download>`、Blob 或页面导航绕过。
- `did-start-loading`、`did-finish-load`、`did-fail-load`、`preload-error`、`render-process-gone`、`unresponsive/responsive`、`child-process-gone` 和后端状态变化均写入脱敏诊断；主框架失败显示可重试状态页，不保留永久黑屏。
- 默认移除 Electron 应用菜单；仅开发服务器存在且显式设置 `NETCONSOLE_ELECTRON_DEV_MENU=1` 时显示开发菜单。

## preload / IPC 白名单

Renderer 当前只能调用：

- `getAppInfo`
- `getBackendStatus`
- `getRuntimeConfig`
- `selectFile`
- `selectDirectory`
- `chooseSavePath`
- `downloadBackendResource`
- `openPath`
- `showItemInFolder`
- `openExternalUrl`
- `onBackendStatusChanged`
- 内部开发冒烟用 `reportRendererReady`

没有通用 `invoke(channel)`、`send(channel)`、文件读写、环境变量读取、Python 路径设置或命令执行接口。详细路径规则见 [Desktop Native Bridge 契约](DESKTOP_NATIVE_BRIDGE.md)。

## 文件选择与导出边界

- `selectFile`、`selectDirectory` 和 `chooseSavePath` 只调用 Electron 原生对话框。
- main 仅接受白名单 DTO；过滤器数量、名称、扩展名、保存文件名和未知字段均有运行时限制。
- 对话框返回的绝对路径只在当前 Electron 进程内登记为临时授权；`openPath`/`showItemInFolder` 只能回传并使用这些已授权路径。
- `openPath` 只允许原生对话框授予的目录或明确的数据/报告扩展名；程序、脚本、系统控制文件和未知扩展名默认拒绝，不能成为通用程序启动器。
- `chooseSavePath` 只选择目标；Excel、ZIP、PDF、报告和 Artifact 内容继续由 Python Application Service/Export Process 生成。
- `downloadBackendResource` 在 Browser 中使用普通下载，在 Electron 中只把安全相对 API 描述交给 main；main 使用当前动态后端和请求头令牌流式写同目录临时文件，成功后原子替换。Renderer 不接收完整文件、任意 URL、Header 或目标路径，令牌不进入 URL、Storage 或日志。
- Browser Adapter 启动原生下载后返回 `started`；Electron 只有保存完成才返回 `saved`，原生保存对话框取消返回 `cancelled`，HTTP、网络、文件或退出中止返回 `failed` 并清理 `.part`。
- Electron 退出先关闭下载入口、取消并等待在途流完成清理；保存对话框仍打开时也不会在退出开始后创建新下载。随后 Main 请求 Python 停止，等待 Uvicorn 退出后的 `shutdown_ack`，再发送 `exit`；全部受管清理结束后才退出 Electron。
- 后续 `openArtifact` 必须使用受控 `artifact_id` 解析，不得把当前临时路径授权扩大为任意业务路径接口。

## Qt Legacy 策略

当前 Qt 主程序仍是稳定生产与回退入口。允许：

- P1/P2 缺陷修复；
- 数据安全与必要兼容修复；
- 尚未完成 Web 纵向闭环的业务回退。

禁止：

- 新增大型 Qt 页面；
- 新增 Qt 专属业务规则；
- 新增只能由 Qt 调用的 Application Service；
- 在 Qt 页面内新增采集、解析、数据库或导出逻辑。

## 固定后续迁移顺序

1. Online MR 完整操作闭环
2. 任务中心
3. Agent 管理
4. fping / iPerf 网络工具
5. 离线 MR/MESH 分析
6. 报告和 Artifact 管理
7. AC 管理
8. 配置采集与文件管理
9. SNMP 等剩余模块
10. 删除 Qt Desktop

现有 SNMP Center 与无线勘测在 Feature Registry 中继续保持 `DISABLED`，迁移状态为 `BLOCKED`；第 9 项只能在独立重建设计批准后开始。

本轮只加固 Electron 宿主、下载和退出链，没有启动上述第 1 项 Online MR 完整操作闭环迁移，也没有改变 Qt 的生产与回退入口地位。

后续不能只迁移只读列表和详情页。每个模块必须按完整纵向业务闭环迁移，包括创建、启动、实时状态、停止、异常、恢复、Artifact 和导出；在达到 `COMPLETE` 前不能隐藏 Qt 回退入口。浏览器开发联调通过不构成正式产品验收证据。

## 定向验证

```powershell
# Python 启动适配器与既有 Desktop 会话
.\.venv\Scripts\python.exe -m pytest tests\test_electron_runtime.py tests\test_web_host.py

# Electron main/preload/IPC/生命周期与真实 Python 集成
cd apps/desktop_electron
pnpm test
pnpm run typecheck
pnpm run build:main
pnpm smoke:dev

# Vue Browser/Electron Adapter、统一 API/WebSocket 与浏览器回退
cd ../web
pnpm test
pnpm build
```

完整 Windows 安装包、代码签名、升级、托盘和真实发布目录尚未验收；原生保存对话框与关闭后进程残留也仍需在本地主工作区人工点击核对，不能从上述源码冒烟推断为通过。
