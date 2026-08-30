# Electron Desktop 基础架构

## 全局任务中心

Electron 复用同一 Vue Renderer、FastAPI 会话和 `TaskApplicationService -> TaskRepository -> tasks.db`。全局任务入口、右侧任务列表抽屉、完整任务详情抽屉和合并进度浮层均位于 Vue 根布局，完整历史/筛选页面位于主工作区 `/tasks`；不再创建任务专用 `BrowserWindow`。严格的 `taskId/module/status` DTO 仅用于恢复主窗口：有 `taskId` 时直接在当前页面打开可复用详情抽屉，无 `taskId` 时打开任务列表抽屉，不创建工作区标签或切换路由；关闭抽屉或业务标签不取消后台任务。

任务动作以后端 owner capability 为准。当前统一停止入口只显式路由到设备管理、配置采集和文件管理既有 Application Service；其他 owner 保持禁用，不回退到通用 cancel 文件。设备 Export 只有在当前服务仍持有匹配的 Export spec、持久化 Job cancel 路径和活跃进程时才能确认 `STOPPING`。Artifact 使用强类型 DTO 携带不透明标识、正式显示名、大小、类型和受控 API 请求，经既有 Electron 流式下载、临时文件及原子替换保存；统一 DTO 和日志均不向 Renderer 返回服务端绝对路径。

主窗口和附加工作区窗口都安装同一 Renderer diagnostics，覆盖 preload、主 frame 加载失败、崩溃和无响应；`render-process-gone` 记录真实 reason、exitCode、webContents、窗口类型、安全路由和最新严格 workload 快照，GPU/Utility/Network Service 等 `child-process-gone` 使用独立事件。脱敏后的后端状态广播到所有受管窗口。任务抽屉和浮层随根布局存在，不建立第二套窗口生命周期。

文件管理桌面动作使用独立 `executeFileDesktopAction(fda1_*)` 白名单。Renderer 只能提交 60 秒一次性引用；Electron main 只访问当前受管 Python 的固定回环端点，Service 只允许打开受控根内目录或启动固定 WinSCP。路径、程序、参数和凭据不进入 Renderer，Electron WinSCP 启动参数不含密码。

## 工作区、多窗口与 Windows 通知区域

`WorkspaceWindowController` 统一管理一个主窗口和附加工作区窗口；所有窗口复用同一个 `PythonBackendManager`、动态回环 Origin 和内存桌面会话，不会为标签、窗口或 Vite 另建 Backend。Vue 工作区使用 Pinia 管理标签的路由、实例和缓存键，主进程只在当前进程内存中保存受限导航快照，不保存业务页面响应式状态、绝对路径、Token、密码、`confirm_token` 或设备凭据。

工作区路由默认 `cache=false`、`allowDuplicate=false`。标签仍可保留在工作区，但普通页面离开时会卸载；`AppRouteView` 的 KeepAlive include 只包含标签仍存在且显式声明 `workspace.cache=true` 的路由。MESH 使用单一 `singleton` 标签和稳定 cache key，禁止同窗口复制；设备详情与 Online MR 分析等确有资源实例语义的页面单独声明复制策略。关闭标签或局点切换从 include 移除 cache key 后会触发真实卸载，不通过提高 KeepAlive 上限掩盖资源增长。

工作区快照只存在于当前 Electron/Vue 进程内存。新进程首次读取工作区状态时固定返回主窗口空快照，不恢复主窗口或附加工作区窗口；旧 `userData/workspace-layout.json` 会被精准删除，且不影响同目录的主题、工具集或 UI preference 文件。Browser fallback 同样忽略并清理旧 `netconsole.workspace.v1` 与 `netconsole.web.open-page-tabs`，不再写标签持久化。Renderer 仍只能通过白名单 IPC 打开受控内部路由、保存当前所属窗口的进程内快照和更新已清理的窗口标题，不能提供 URL、`BrowserWindow` 参数或本机路径。

每次新进程创建主窗口时，`BrowserWindow` 仅接收 `1280x800` 安全默认尺寸和既有 `1024x680` 最小约束，不接收历史坐标。首次 `ready-to-show` 按当时 `screen.getPrimaryDisplay().workArea` 将窗口放入当前主显示器，再执行 `maximize -> show -> focus`；窗口保持 `frame=true`、`fullscreen=false`，最大化使用 Windows 工作区而不是无边框全屏。启动完成后用户可正常还原、移动、调整尺寸或最小化。托盘和第二实例恢复只对仍在运行的同一窗口执行 `restore/show/focus`，不会重新最大化；完整退出、异常退出、升级启动和 `app.relaunch()` 创建的新进程才重新应用启动默认值。

局点切换前，Renderer 先把当前进程快照收敛为仅保留 Dashboard 与系统设置，并立即显示目标局点 metadata 与“加载中”状态；`WorkspaceWindowController` 再对所有受管窗口执行同一局点边界清理并在内存中保留回滚副本。FastAPI `create_app()` 中存在绑定启动局点数据库和目录的 Service/Repository，因此 Main 不在原进程内强改 SiteContext，而是执行 warm handoff：旧 Backend 继续承载当前 Renderer，新 Backend 使用目标局点和独立动态回环端口后台启动；ready 后先核对目标局点，再原子切换 Runtime、内存令牌、Cookie、Bootstrap 和 Renderer，最后安全停止旧进程。同一数据根仅允许持有当前 owner `instance_id` 且目标局点不同的候选进程进入 transition lock，旧进程释放主锁后候选进程才提升为新 owner；第三个进程与伪造 owner 仍失败关闭。新 Backend 不一致或启动失败时保持旧 Backend 并恢复原局点与进程内窗口快照。成功时才清除旧 MESH Renderer recovery/workload 并重新加载所有窗口，避免旧 `session_id`、KeepAlive 实例或多窗口业务标签跨局点恢复。

Windows 下启动时会创建 `TrayController`，图标统一由 `resolveTrayIconPath()` 解析：源码态取仓库 `resources/branding/netconsole.ico`，安装包从 `extraResources/branding/netconsole.ico` 读取。菜单包含打开主窗口、新建工作区、打开任务中心、运行/失败任务数量、脱敏的 Backend/当前局点状态、关闭到通知区域开关和“退出 NetConsole”。Vue 只向 Main 推送聚合计数；Main 不查询任务数据库。前台终态使用显式加载样式、挂载到 `document.body` 的 Vue Notification，后台终态使用有界 Windows 原生通知；两类通知的详情入口都恢复/保留当前主页面并直接打开任务详情抽屉。图标不可用或创建失败时托盘设置运行时不可用，主窗口不会被隐藏，避免留下无法恢复的后台进程。

默认启用“关闭主窗口后驻留通知区域”。主窗口关闭会隐藏而不停止 Backend、Renderer 或后台任务；托盘和第二实例恢复只显示、还原最小化并聚焦该窗口，不调用 `loadURL/reload/maximize`，因此标签、顺序和活动页保持不变。附加工作区窗口正常销毁；所有普通窗口不可见时，托盘、Backend 和后台业务任务继续存在。只有托盘“退出 NetConsole”（以及显式系统关闭信号）进入单次受控退出：丢弃工作区会话、拒绝新窗口、关闭受管窗口和 Tray，再停止下载、Backend 与会话授权。关闭该设置后，最后一个可见普通业务窗口触发相同的受控退出。

## Windows Server 2012 兼容事实

Windows Server 2012 x64 的 NetConsole 主程序已有用户现场运行确认，证据等级为 `USER_FIELD_CONFIRMED`。仓库没有隔离 Server 2012 自动化 VM 的安装、启动、健康和退出记录，自动化证据记为 `AUTOMATION_NOT_RECORDED`；正式安装包 GUI 验收仍为 `PENDING`。该事实不增加 Electron 或 Backend 的 OS 启动阻断，Windows 11 x64 仍是默认构建与开发目标。

## 当前状态

Electron Desktop 安全基础已在 `apps/desktop_electron/` 建立，复用唯一 Vue Renderer `apps/desktop_renderer/` 和唯一 FastAPI 组合根 `src/netconsole/backend/api/main.py:create_app()`。Electron 是唯一正式桌面产品；Qt 源码、运行时与入口已经退出活动仓库。部分业务仍处于自动实现完成但真实设备待验收状态，不能把“零 Qt”误写成全部业务已经现场验收完成。

当前并存关系：

```text
apps/desktop_electron/     Electron main/preload/shared，目标桌面外壳基础
apps/desktop_renderer/                  唯一 Vue Renderer；Electron 正式使用，浏览器仅开发联调
src/netconsole/            唯一 Python Core/FastAPI/Application Service
```

已删除 Qt 文件的业务去向只由冻结迁移矩阵和 Git 历史追溯。Electron 没有复制 Vue 页面、Python Service、Repository、Parser、Agent、Online MR 或报告逻辑。

## 运行架构

```mermaid
flowchart TD
    EM["Electron Main"] --> PM["PythonBackendManager"]
    PM -->|"参数数组；shell=false"| PY["Python Electron Runtime Adapter"]
    PY --> API["现有 FastAPI create_app"]
    API --> AS["Application Service / Repository / Infrastructure"]
    EM --> PRE["sandboxed preload + contextBridge"]
    PRE --> VUE["apps/desktop_renderer Vue Renderer"]
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
cd apps/desktop_renderer
pnpm install --frozen-lockfile
cd ../desktop_electron
pnpm install --frozen-lockfile
```

项目根存在 `.venv` 时直接启动：

```powershell
cd <仓库根目录>
.\.venv\Scripts\python.exe main.py

# 或从 Electron 子项目启动同一开发链
cd apps/desktop_electron
pnpm dev
```

无参数 `main.py` 与 `pnpm dev` 最终进入同一 `scripts/dev.mjs`。Python 入口优先使用项目锁定的本地 Electron 作为 Node 运行时，因此 PyCharm 不依赖全局 `pnpm`；Electron Main 仍是受管 Python Backend 的唯一生命周期所有者。开发脚本先检查并打包 Electron main/preload，再确认固定回环端口 `5173` 未被占用、启动 Vite dev server，最后启动 Electron；端口冲突时直接失败，不能误连其他 worktree 的 Vite。Electron 自己选择 Python 动态端口，因此 Vite 的 `5173` 与 FastAPI 端口没有绑定关系。Vite 中固定的 `/api`、`/ws` 代理只服务普通 Browser 开发；Electron 的 REST、WebSocket 和下载全部从 Runtime Config 读取受管动态 Origin，不经过固定 `127.0.0.1:8000`。独立 Git worktree 可通过开发机环境变量 `NETCONSOLE_PYTHON` 指向同一项目虚拟环境；该路径不会进入 Renderer、日志或版本化配置。

需要让 Codex、浏览器自动化和 API 诊断访问同一受管运行时时，使用专用入口：

```powershell
cd apps/desktop_electron
pnpm dev:codex
```

该入口为本次进程生成随机开发 Session，在 `D:\study\NetConsole-Workspace\test-data\NetConsole\<run-id>` 创建隔离数据根，并固定使用 `127.0.0.1:5173` 与 `127.0.0.1:8000`。Vue 仅在 Vite 开发编译中取得内存令牌，先通过受保护的 `/api/dev/session` 建立 HttpOnly、SameSite Strict Cookie，再复用正式 REST、WebSocket 和下载契约；令牌不写仓库、URL、日志、SQLite 或持久浏览器存储。只读 `/api/dev/runtime-status` 仅在显式开发模式、回环请求和有效 Session 下注册，并对数据根脱敏。退出时编排器回收 Electron、Vite、Python、两个端口和严格校验过的本次测试目录。

普通 `pnpm dev` 继续使用动态 Backend 端口并只服务 Electron；`dev:codex` 的固定端口只用于本机自动化。两者都拒绝 `0.0.0.0` 和非回环 Origin。生产打包不接受 `--dev-mode`，不注册开发状态接口和 OpenAPI，也不读取开发固定端口或开发 Session 环境变量。

`pnpm dev` 是持久开发模式：它先读取显式 `NETCONSOLE_DATA_ROOT`，否则读取安装器写入的 `HKLM\Software\NetConsole\DataRoot`（当前机器为 `D:\NetConsoleData`），然后在该根下保存正式 `userData` 与 bootstrap。没有这两种配置时 Electron 在创建业务数据前停止启动，不会猜测 AppData。`dev:codex`、`smoke:dev`、`smoke:task-center` 与 package smoke 是隔离测试模式：每次只在 `D:\study\NetConsole-Workspace\test-data\NetConsole\<run-id>` 创建统一根布局，Electron 在申请单实例锁和 `app.whenReady()` 前切换 `userData`，退出时仅删除经过边界校验的本次 run-id。`smoke:task-window` 仅作为旧命令别名保留，也执行主窗口任务中心 smoke。隔离模式不读取机器级指针或正式 bootstrap，局点/数据根写 API 返回 403，设置页只显示脱敏的临时数据根和只读提示。

正常启动会拒绝 bootstrap 中位于 Temp、测试根、不存在或缺少 `sites/` 的数据根，先保存 `bootstrap.json.invalid-<timestamp>`，再回退到正常持久化根。Python 缺失或不可执行只会让启动明确失败，不创建 demo、不改数据根和 bootstrap。可用以下命令只读诊断；只有显式 `--repair` 才会备份并原子修复配置引用，不移动或删除任何局点数据：

```powershell
.\.venv\Scripts\python.exe -m scripts.maintenance.check_desktop_bootstrap
.\.venv\Scripts\python.exe -m scripts.maintenance.check_desktop_bootstrap --repair
```

Electron/Vue 的产品标题统一为 `NetConsole v1.5.1 by wxj`，侧栏使用品牌图片与“本地网络运维控制台”；源码开发态顶栏额外显示 Git 短提交号，正式产品标题不附加开发标识，内部迁移阶段文案不进入正式界面。

自动开发冒烟：

```powershell
cd apps/desktop_electron
pnpm smoke:dev
pnpm smoke:workspace-tray
```

冒烟只有在 Electron、Python、Vue runtime adapter 和真实 `/api/health` 全部成功后才以 0 退出，并检查退出链能够回收 Vite、Electron 和 Python。

普通与打包 smoke 会验证主窗口位于当前主显示器、处于最大化且非全屏状态。`smoke:workspace-tray` 使用隔离临时数据根，额外验证受管附加窗口创建/关闭、主窗口还原并调整尺寸、隐藏到托盘后 Backend 仍为 ready、恢复时不重新最大化或改写尺寸，以及明确退出后的回收。它不替代 Windows 通知区域右键菜单、真实缩放图标、主显示器切换、任务栏/标题栏控件和安装包的人工点击验收。

Codex 开发链可用 `pnpm exec node scripts/dev.mjs --codex --smoke` 做同口径冒烟；它还验证受保护的 `/api/dev/runtime-status` 已就绪，并检查固定端口退出后可重新绑定。浏览器与 Electron 专项 E2E 将在独立 Playwright 阶段接入；在脚本真实存在前，不把 Vitest 或 smoke 冒充 E2E。

启动日志使用单调时钟记录 `electron.app_ready -> window_created -> loading_view_shown -> backend.spawn_started -> handshake_received -> health_ready -> renderer.navigation_started -> dom_ready -> mounted -> desktop.interactive`。受管 Backend 另以结构化 INFO 记录 `spawn -> first stdout` 及 `paths_resolved / instance_lock_acquired / storage_manifest_ready / listener_bound / active_site_database_ready / ap_identity_index_ready / routers_registered / application_built / listener_ready`，用于区分冻结 EXE/DLL 加载、数据根、数据库与应用组合耗时；不记录令牌或凭据。启动页单次加载后按这些真实阶段更新中文状态，并持续显示无虚假百分比的动画、已用时间和慢启动提示。Vue `mounted` 与可交互状态严格分开：页面先挂载基础壳，加载设置并通过真实 health 后才上报 `interactive`。Desktop 下历史 Task/Agent/Traffic/File 恢复延后到首屏之后执行；普通 Server 模式仍保持同步启动和失败回滚。当前 schema 且无需迁移/修复的 `devices.db` 启动使用只读 fast path，不执行 schema 脚本、`BEGIN IMMEDIATE`、schema version 写入或 `wal_checkpoint(TRUNCATE)`；只有新库、schema upgrade 或明确兼容/数据修复才进入 maintenance 并 checkpoint。运行服务的 `runtime_services_ready` 与 Backend core health 分层；degraded 状态会在 health 暴露并拒绝 Agent/Traffic/File 等写操作。当前 active site 必须通过 SiteRegistry 与 `PathResolver.site_db_path()` 解析，禁止硬编码显示名、legacy 目录或现场 hostname。当前实测基线与优化证据见 [E5 启动性能归档](../archive/migrations/electron-only/E5-2026-07-18.md)。

## 生产资源模式

源码环境可验证生产资源加载逻辑：

```powershell
cd apps/desktop_electron
pnpm build
pnpm start
```

`pnpm build` 构建单文件 main/preload、Windows x64 管理员启动 helper 和 `apps/desktop_renderer/dist`；构建机必须提供 Go，helper 使用 `CGO_ENABLED=0` 和 Windows GUI 子系统生成。`pnpm start` 启动 Electron 与本机 Python，由 FastAPI 在同一动态回环 Origin 提供已构建的 Vue 静态资源。正式运行只使用已打包的 `resources/native/netconsole-elevated-launcher.exe`，客户机不需要 Go。Electron 不使用第二套 Renderer，也不把临时令牌放入页面 URL。

Electron Builder 目录包/NSIS 与 PyInstaller 受管 Backend 的构建链已经建立。NSIS 保持现有安装器，只新增程序目录之后的数据根选择页；它以管理员权限写入 HKLM 指针，普通卸载不会删除业务根。升级时保持原根；选择新根时由受管 Backend 迁移成功后才更新指针。依赖批准清单、NOTICE、SBOM 和 package smoke 仍是构建门，完整 Windows 安装/升级/卸载人工验收仍待最终组合执行。代码签名和自动升级尚未建立，不得把源码 `.venv` 当作交付依赖。

## Python 后端生命周期

`PythonBackendManager` 的状态为 `starting -> ready -> stopped|failed`，并提供幂等 `start()`、`waitUntilReady()`、`getRuntimeInfo()`、`getStatus()` 和 `stop()`：

1. Electron 启动受管 Python，并要求后端直接绑定 `127.0.0.1:0`；Python 在持有监听 socket 后通过 stdout 结构化事件回报实际端口，避免“预选后释放”的抢占窗口。
2. 每次启动生成新的高熵、URL-safe 临时令牌。
3. 使用可执行文件和参数数组启动 `netconsole.backend.electron_runtime`，固定 `shell: false`、`windowsHide: true`、`127.0.0.1` 和端口 `0`。
4. 令牌只通过已持有子进程的 stdin 首行 JSON 传递；不进入参数、环境变量、URL 或配置。
5. Electron 先校验受管子进程管道返回的 `127.0.0.1:<port>`，再使用临时请求头轮询真实 `/api/health`，成功后才加载正式 Vue 页面。
6. stdout 只消费受管启动/退出协议；生产仅将结构化 lifecycle 事件提升为 INFO，其余 stdout 保持 DEBUG。stderr 先移除令牌和常见敏感字段，再按受控警告/错误事件写入 Electron 日志。
7. 正常退出时 Main 通过同一 stdin 控制管道发送 `shutdown`，Python 控制线程据此请求 Uvicorn 优雅退出；父进程异常导致管道 EOF 时，Python 同样请求退出。
8. Python 收到命令后立即发送 `netconsole.electron_backend.shutdown_received`；只在 Uvicorn 与 FastAPI lifespan 完全退出后发送 `shutdown_complete`，随后等待 Main 的 `exit`。协议事件不能替代 OS 进程退出。
9. Main 始终等待 child `exit/close`，超时后按 `SIGTERM -> SIGKILL -> Windows 当前 owned PID 的 taskkill /T /F` 有界升级；不按进程名扫描或误杀其他 Python/外部工具。
10. 只有 child 实际退出才能转为 `stopped`。后端意外退出或最终升级仍未退出时状态变为 `failed`，只向当前受信 Renderer 发送脱敏状态事件，不谎报 `stopped`。
11. 正式默认阶段 watchdog 为 30 秒，整体启动 hard deadline 为 60 秒；监听握手与 health ready 分开计时，合法阶段进展可刷新 watchdog，但不能无限等待。

### 运行日志生命周期

Electron Main 的应用日志由异步队列写入 `<data_root>/runtime/logs/electron.log`，达到 20 MB 或跨本地日期时滚动为 `electron-YYYYMMDD-HHmmss-NNNN.log`，旧文件保留 7 天。生产默认只落盘 `INFO` 及以上；Backend stdout 仅用于协议控制，stderr 作为受控错误/警告事件记录，重复 fingerprint 在 10 秒窗口内抑制并每 60 秒输出摘要。大对象只写有限摘要，不改变局点 raw/artifact 的完整内容。

Backend health ready 后，Electron 写入 `ELECTRON_BUILD_IDENTITY`，包含完整 `build_id`、Backend/Frontend
commit、edition、dirty 与 build timestamp；Python 启动日志写入同口径 `BUILD_IDENTITY`。Renderer 在
所有模式把合法 build identity 显示为 `v<version>+<8位短SHA>`。这些字段用于区分“现场旧安装包”与
“当前修复包”，不得用运行目录名或文件修改时间代替 provenance。

Python `app.log` 使用相同的 20 MB + 日期滚动与 7 天保留。启动后异步执行一次轻量 Housekeeper，运行期间每小时 best-effort 检查日志目录；总量上限 300 MB，清理目标 250 MB，活动日志和数据库升级审计始终保护。WPS writer 不属于 Electron 仓库，本边界只治理其外部 stdout/stderr 文件的识别、保留和总容量清理。

Backend 重启或恢复后，Main 的 `ready` 只表示新进程已通过 supervisor 健康检查。Vue Runtime 收到该事件后必须重新通过受信 preload bridge 读取并校验 Runtime Config，把动态 Origin 和 `X-NetConsole-Session` 令牌作为同一 generation 原子替换；完成前统一显示为重新连接中。根布局随后使用新绑定再次请求 `/api/health`，只有成功后才显示 `Backend Online`。重绑定失败保留上一份受信 Electron 绑定用于诊断，但状态保持失败，绝不回退 Browser 相对 `/api`。

通用 API client 只允许 `GET/HEAD` 对明确的连接中断、Backend 重启和 `502/503/504` 做一次受控恢复：Electron 先重绑定，再从当前 generation 重新构造 URL 与 Header 后重试。`POST/PUT/PATCH/DELETE` 不自动重放，避免响应丢失时重复创建任务或执行写操作。Runtime 重绑定诊断只记录 host、reason、generation、耗时和端口是否变化，不记录 Origin、令牌或请求头。

桌面总退出是单一受管屏障：进入 shutdown 后立即显示复用主窗口的“正在安全退出”进度页，拒绝第二实例恢复、任务中心、工作区窗口和局点切换；先等待 Desktop IPC 的下载取消与原子文件清理，再完成 Python `shutdown_received -> shutdown_complete -> child exit`，最后关闭窗口、Tray 和会话路径授权。完成事件只在 Backend 停止、窗口/Tray 收口并完成日志 flush 后记录。单实例锁保持到 Electron 进程真正结束，不在 `app.exit()` 前提前释放。Windows 注销/关机监听 `query-session-end`/`session-end`，采用 preventDefault 后的尽力收尾，不能保证操作系统提供完整主动退出预算；自动测试不能替代 Windows Server 2012、机械硬盘、RDP 多会话及正式安装包人工验收。

## 本地 API 安全模型

- FastAPI 只监听 `127.0.0.1`。
- Electron HTTP 请求携带 `X-NetConsole-Session`；桌面会话引导端点和 HttpOnly Cookie 只服务当前 Electron/Vite 受控链，不代表 Qt WebHost 运行时仍存在。
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
devTools: false（生产；Vite 开发态为 true）
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
- `did-start-loading`、`did-finish-load`、`did-fail-load`、`preload-error`、`render-process-gone`、`unresponsive/responsive`、`child-process-gone` 和后端状态变化均写入脱敏诊断；日志不得包含 Token、Cookie、完整路径、请求头或原始日志。轨旁图阶段的 Renderer 退出显示纯静态安全页，可安全恢复同一会话但不自动请求轨旁图，也可直接重试或打开日志目录；成功稳定交互三秒后清除本次进程内恢复标记。
- 默认移除 Electron 应用菜单；仅开发服务器存在且显式设置 `NETCONSOLE_ELECTRON_DEV_MENU=1` 时显示开发菜单。
- 生产 BrowserWindow 显式设置 `devTools: false`；只有已校验的本机 Vite 开发模式允许 DevTools。

## preload / IPC 白名单

Renderer 当前只能调用：

- `getAppInfo`
- `getBackendStatus`
- `getRuntimeConfig`
- `selectFile`
- `selectDirectory`
- `listExternalTools`、三个工具集专用选择器、系统终端引用和受控增删改/分类/排序方法
- `launchExternalTool({toolId, launchMode})`、`revealExternalTool(toolId)` 与 `refreshExternalToolStatuses`
- `chooseSavePath`
- `downloadBackendResource`
- `openPath`
- `showItemInFolder`
- `openExternalUrl`
- `onBackendStatusChanged`
- 内部开发冒烟用 `reportRendererReady`
- MESH 轨旁图诊断用单向 `reportRendererWorkload`，只接受固定模块、路由、阶段和有界标量
- `getRendererRecoveryState`，只返回当前受管窗口在本次应用运行期内的固定恢复 DTO

没有通用 `invoke(channel)`、`send(channel)`、文件读写、环境变量读取、Python 路径设置或命令执行接口。详细路径规则见 [Desktop Native Bridge 契约](./NATIVE_BRIDGE.md)。

工具集使用独立 `userData/external-tools.json` schema v2 Store，不进入 UI Preference 或局点数据。iperf3/fping 留在系统设置；SecureCRT/Xshell/PuTTY 的用户可见配置入口位于工具集，卡片只保存系统终端引用；旧 IPOP 路径幂等迁移为独立工具。Renderer 启动只传工具 UUID 与普通/管理员模式，Main 重新取已登记记录并复验。普通启动固定 `shell:false / detached:true / stdio:"ignore"`；管理员启动通过打包的最小 Go helper 调用 `ShellExecuteExW(runas)`，禁止提升 NetConsole 自身，UAC 取消不增加统计。自定义图标源路径留在 Main 的短期选择表，Renderer 只收到 `selectionId` 和 data URL。真实 UAC 和正式包 helper 状态为 `IMPLEMENTED_UNVERIFIED`，完整契约见[工具集](EXTERNAL_TOOL_COLLECTION.md)。

## 文件选择与导出边界

- `selectFile`、`selectDirectory` 和 `chooseSavePath` 只调用 Electron 原生对话框。
- main 仅接受白名单 DTO；过滤器数量、名称、扩展名、保存文件名和未知字段均有运行时限制。
- 下载保存后的绝对路径只进入 Electron Main 的有界临时授权表；只有具备原生 open/reveal 权限的数据或报告文件才向 Renderer 返回 capability ID，`.bin/.conf/.exe` 等仅保存类型返回 `saved` 但不返回 capability。
- `openPath`/`showItemInFolder` 分别校验 capability 的 purpose、action、规范化实际扩展、默认 15 分钟 TTL 和 FIFO 有界状态；程序、脚本和系统控制文件不能通过 reveal 绕过。
- `chooseSavePath` 只选择目标；可选默认目录必须来自本会话 `selectDirectory` 授权。Excel、ZIP、PDF、NAM、报告和 Artifact 内容继续由 Python Application Service/Export Process 生成。
- `downloadBackendResource` 在 Browser 中使用普通下载，在 Electron 中只把匹配设备、配置、文件、AC、MESH、Online MR 和网络工具既有 Artifact 路由的安全相对 API 描述交给 main；普通 `/api` 路由不在白名单。Renderer 可回传本会话 `chooseSavePath` 产生的目标路径以避免重复弹窗，main 必须重新验证内存授权，任意路径仍被拒绝。Main 会保存选择时的目标快照，并在下载开始和提交最终文件前复验；目标被其他进程创建、替换、改成目录或改变时拒绝覆盖并要求重新选择位置。main 使用当前动态后端和请求头令牌流式写同目录临时文件，成功后安全替换，并拒绝用户把最终文件改成不同实际扩展。Renderer 不接收完整文件、任意 URL 或 Header，令牌不进入 URL、Storage 或日志。
- Browser Adapter 启动原生下载后返回 `started`；Electron 只有保存完成才返回 `saved`，原生保存对话框取消返回 `cancelled`，HTTP、网络、文件或退出中止返回 `failed` 并清理 `.part`。
- Electron 退出先关闭下载入口、取消并等待在途流完成清理；保存对话框仍打开时也不会在退出开始后创建新下载。随后 Main 请求 Python 停止，等待 `shutdown_received`、Uvicorn/lifespan 完成后的 `shutdown_complete` 和 child OS exit；全部受管清理结束后才退出 Electron。
- 后续 `openArtifact` 必须使用受控 `artifact_id` 解析，不得把当前临时路径授权扩大为任意业务路径接口。

## Qt 历史回收策略

Qt/PySide6/QFluentWidgets 源码、运行时和桌面入口已经删除，不再允许通过兼容导入、回退壳或开发依赖重新进入活动架构。旧页面和删除分类只保留在冻结迁移矩阵与 Git 历史中，不再驱动当前开发。

Electron 后续业务实现以当前 Feature Registry、生产代码和真实业务契约为准；缺失能力必须在 Electron 中明确隐藏或标记待验收，不能恢复 Qt 入口。

SNMP Center、通用 MIB/OID 平台与无线勘测已经正式删除，不进入 Electron 迁移、发布或未来重建清单。设备管理只保留 SNMP v1/v2c 只读基础识别，网络工具无线扫描保持独立能力。

Electron 宿主、下载和退出链已完成自动冒烟；Online MR 等业务闭环按最终迁移矩阵继续验收，Qt 历史只通过 Git 追溯。

后续不能只保留只读列表和详情页。每个模块必须按完整纵向业务闭环补齐创建、启动、实时状态、停止、异常、恢复、Artifact 和导出；未达到可用门槛的 Electron 入口保持隐藏或明确标记待验收，不能恢复 Qt 回退入口。浏览器开发联调通过不构成正式产品验收证据。

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
cd ../desktop_renderer
pnpm test
pnpm build
```

完整 Windows 安装包、代码签名、升级和真实发布目录尚未验收；工作区与托盘已有单元测试及源码 smoke，但原生托盘菜单、通知区域图标缩放、运行中切换主显示器后的下次启动、任务栏与标题栏控件、原生保存对话框及关闭后进程残留仍需在本地主工作区人工点击核对，不能从上述源码冒烟推断为通过。
