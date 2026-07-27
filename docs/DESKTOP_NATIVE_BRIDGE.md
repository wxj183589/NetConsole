# Desktop Native Bridge 契约

## 任务与工作区窗口 DTO

`openTaskWindow` 只接受可选的 `taskId`、`module`、`status`。`taskId` 仅允许受控 ID 字符，`module` 固定为 `devices/config/files`，`status` 固定为任务状态枚举；未知字段和任意 URL、路径、程序或 argv 均拒绝。主窗口和任务窗口可作为 IPC sender，文件对话框以实际调用窗口为父窗口。

受控 Artifact 保存对话框同样以 IPC 调用窗口为父窗口。任务 DTO 只返回 owner 授权的下载 endpoint、opaque Artifact ID、显示名、大小和类型；保存完成后 Renderer 不接收本机路径，只有安全可打开/定位的文件才得到临时 capability ID，仅保存类型返回 `saved` 但不返回 capability。本机路径只存在于 Electron Main 的有界内存授权表。

`openWorkspaceWindow` 只接受长度受限的内部路由和清理后的标题；preload 与 main 双重拒绝外部 URL、`file:`、反斜杠、路径遍历、专用任务/API/WebSocket 路由、敏感 query、绝对路径和未知字段。读取/保存工作区快照仅作用于 sender 所属的受管窗口，并校验 schema、窗口 ID、标签数量和每个标签的受控字段；Renderer 不能创建任意 `BrowserWindow`，也不能传入位置、尺寸或加载地址。

## 当前状态

Electron Desktop Native Bridge 已实现基础白名单，代码位于 `apps/desktop_electron/src/{main,preload,shared}`。除桌面选择器和受控后端文件下载外，设备详情可通过独立 `openExternalUrl` 动作把无凭据 HTTPS 地址交给系统浏览器。普通 Browser/Server Mode 仅作开发诊断，没有正式本机动作能力。

Electron-only E1 已删除无生产调用者的 `QtDesktopAdapter`。Python `DesktopActionService`、`LocalDesktopAdapter` 与拒绝 Adapter 继续承载后端语义动作和安全校验；原生选择器、路径 capability、下载和 IPC 只以 Electron Main/Preload 实现为事实源，不保留第二套 Qt 桌面桥接。

总体运行方式和启动命令见 [Electron Desktop 基础架构](ELECTRON_DESKTOP.md)。

## 信任边界

调用必须同时满足：

- Electron BrowserWindow 使用 `nodeIntegration: false`、`contextIsolation: true`、`sandbox: true`；
- 方法由 contextBridge 逐项暴露，Renderer 不能取得完整 `ipcRenderer`；
- main 检查 IPC sender 必须是当前主窗口 `webContents`；
- preload 与 main 对 DTO 分别做运行时校验；
- `desktop.native_bridge` 在 Feature Registry 登记，Vue 状态区按 Feature 状态展示/禁用；Feature 只控制产品可见性，不替代 main 的安全校验；
- 任何本机业务对象仍须经过 FastAPI/Application Service 权限和审计。

## 当前白名单

| 能力 | 输入 | main 约束 | 当前用途 |
| --- | --- | --- | --- |
| `getAppInfo` | 无 | 只返回版本、平台、是否打包 | 状态展示 |
| `getBackendStatus` | 无 | 不返回令牌 | 生命周期展示 |
| `getRuntimeConfig` | 无 | 仅后端 `ready` 且受信 sender 可取 | Vue 内存 API 配置 |
| `openWorkspaceWindow` | 受控内部路由、已清理标题 | preload/main 校验路由和标题；Main 创建受管窗口，复用唯一 Backend | 当前标签或 Dashboard 在独立工作区打开 |
| `getWorkspaceWindowState` / `saveWorkspaceWindowState` | 无 / 当前窗口的强类型快照 | sender 必须属于 `WorkspaceWindowController`；严禁跨窗口写入、绝对路径和敏感字段 | 恢复标签与窗口布局 |
| `setWorkspaceWindowTitle` | 已清理标题 | 仅更新 sender 所属受管窗口标题，不接受路径、控制字符或敏感字段 | 动态标签标题 |
| `getCloseToTrayState` / `setCloseToTrayEnabled` / `onCloseToTrayChanged` | 无 / 布尔值 / 固定回调 | 只读写 Electron `UiPreferenceStore` 的桌面偏好并广播脱敏状态；不访问局点数据库或 Backend API | 系统设置与托盘开关同步 |
| `selectFile` | 过滤器、是否多选 | 数量、名称、扩展名、未知字段白名单 | 原生选择器 |
| `selectDirectory` | 无 | 原生目录选择器 | 原生选择器 |
| `chooseSavePath` | 安全文件名、过滤器、可选的本会话已授权目录 | 目录必须来自 `selectDirectory`，不接受未授权路径或把路径/命令伪装为文件名 | 只选择目标位置 |
| `downloadBackendResource` | 正式 Artifact endpoint 白名单、安全 Query、建议文件名、过滤器、可选的本会话已授权另存为路径，以及成对出现的期望大小/SHA-256 | main 重新校验路径确由 `chooseSavePath` 授权，只访问当前受管动态回环后端，自行注入内存令牌并流式保存；有完整性元数据时同时核对 Content-Length、实际字节数和 SHA-256；普通 `/api/health` 等路由拒绝 | 文件、配置快照与既有业务 Artifact 下载 |
| `openPath` | 下载完成返回的 capability ID | Main 按 purpose/action/type/TTL 解析当前进程临时授权；仅数据/报告扩展名白名单 | 打开已保存 Artifact |
| `showItemInFolder` | 下载完成返回的 capability ID | 与 `openPath` 独立校验 reveal action；危险或仅保存类型不签发该能力 | 在资源管理器定位 |
| `openOnlineMrSessionLocation` | 稳定 Online MR `session_id` | preload/main 双重字符白名单；main 只调用当前受管回环后端的固定 `desktop-location` 端点并注入内存令牌；后端只返回 `PathResolver` 管理根内的文件/目录，路径不返回 Renderer | 打开车载 MR 会话包、raw 或受管会话目录 |
| `openExternalUrl` | 后端设备详情 DTO 返回的 Web 管理地址 | 仅无用户名/密码的绝对 HTTPS URL；拒绝 HTTP、文件协议和畸形 URL | 交给系统默认浏览器打开设备管理页 |
| `selectSettingsTool` | `iperf3/fping/ipop/securecrt/xshell/putty` 之一 | main 按 tool ID 固定文件名集合，复验绝对路径与 basename；FastAPI 保存与真实执行点再次校验存在性、普通文件和非符号链接 | 系统设置原生 EXE 选择 |
| `selectSettingsDirectory` | `securecrt_sessions_root` | main 只接受语义 ID，返回值必须为绝对路径；FastAPI 保存时复验已存在目录和非符号链接 | SecureCRT 会话根目录选择 |
| `selectSettingsColor` | 无 | 只返回系统设置契约允许的受控主题色之一 | 原生主题色选择 |
| `executeSettingsAction` | `open_settings_config/open_current_site/launch_ipop` 之一 | main 调固定动态回环端点并注入短期会话；Renderer 不提供路径、程序或 argv；后端只打开受控目录或启动经复验的 IPOP | 系统设置本机动作 |
| `onBackendStatusChanged` | 固定回调 | 只接收脱敏状态 | 意外退出通知 |

`reportRendererReady` 仅用于自动开发冒烟的 health 结果回报，不接受 URL、路径、命令或令牌。

## 路径授权模型

Renderer 不能把绝对路径提交给打开动作。`downloadBackendResource` 仅在流式下载和原子替换成功后，针对至少具备 `open/reveal` 一项的文件把最终路径登记到最多 256 项、默认 15 分钟有效的 Main 内存授权表，并返回随机 capability ID。每条记录包含 purpose、独立 action、规范化实际扩展名和过期时间；未知、伪造、过期、FIFO 淘汰或跨用途复用均失败。`openPath`/`showItemInFolder` 只接受该 ID，由 Main 分别校验动作并解析路径；退出时授权表清空，不持久化。

原生打开/定位对文件使用允许列表，当前只接受常见文本、JSON/CSV、Markdown、PDF、Excel、抓包和 ZIP 等数据/报告类型。FileManagement 既有 `.bin/.conf` 及其他合法远端文件仍可安全保存，但不返回 capability；`.exe`、脚本、系统控制文件、快捷方式和安装包同样不能借 reveal 绕过。保存时建议名与最终名按规范化的真实末级扩展精确比较，`.tar.gz/.zip.gz` 等已知复合扩展整体保留，无扩展单独表示；未知或含连字符的合法扩展不会折叠为“无扩展”，改扩展名会在发起 HTTP 前拒绝。

`openExternalUrl` 不复用窗口导航，也不允许 Renderer 自己创建新窗口。main/preload 两侧都校验 URL，只有无凭据 HTTPS 地址会传给 `shell.openExternal`；临时 API Token、认证 Header 和设备密码不得进入 URL。

`openOnlineMrSessionLocation` 不接受 Renderer 路径、目标类型、URL 或回退目录。后端根据当前局点和 `session_id` 解析受管 Session，优先定位正式 ZIP，其次定位 MESH/终端 raw，再回退受管目录或关联报告；不存在时返回稳定安全错误。main 收到目标后只调用 `showItemInFolder` 或 `openPath`，不会把绝对路径回送 Renderer。Server Mode、非 `127.0.0.1`、缺少桌面会话认证或 Feature 关闭时端点失败关闭。

## 文件导出边界

`chooseSavePath` 只返回用户确认并登记为当前会话授权的目标路径；可选默认目录同样必须先由 `selectDirectory` 授权。Main 同时记录目标当时是不存在还是普通文件，以及文件的大小、时间和文件标识。报告生成及 Excel/ZIP/PDF/NAM 内容继续属于 Python Application Service 与 Export Process。`downloadBackendResource` 只搬运既有受控 HTTP 响应：Renderer 可以回传刚取得的另存为路径，但 main 必须在内存授权表中重新校验后才跳过第二次对话框；任意绝对路径仍会被拒绝。Renderer 只能提交设备、配置、文件、AC、MESH、Online MR 和网络工具现有正式 Artifact endpoint 模式及各端点允许的字符串 Query，main 使用当前 `PythonBackendManager` 的动态回环 Origin 与内存令牌请求，先流式写入目标同目录的随机 `.part`，同步计算实际大小和 SHA-256，并在期望元数据存在时完成校验；提交前再次复验目标未被其他进程创建、替换或改变，再安全替换并校验最终文件。目标变化、HTTP 失败、路径不可写、空间不足或完整性不一致均不改变服务端任务终态，且不留下 `.part` 或伪成功文件。Electron Main/Preload 不读取数据库、不解释或生成报告。

Electron Main 为所有受管 Renderer URL 注入 `netconsole_host=electron`。Renderer 看到该标记但未发现 preload bridge 时必须失败关闭，显示“Electron 文件保存组件未加载”，不得创建 `<a download>` 或回退 Browser Adapter。只有未携带 Electron 宿主标记的普通浏览器页面才允许启动浏览器下载，并且 `started` 只表示已交给浏览器，不能转换为“已保存到本地”。

设备管理页面在创建 `web_export_device_csv` 或 `web_export_device_template_csv` 前立即打开一次 Save As；用户取消时不创建任务。确认后页面按 `task_id` 保存另存为授权、范围和预计数量，任务完成时直接把 Artifact 写入该目标，不再弹第二次对话框，也不使用“最近任务”猜测绑定。保存失败后“重新保存”只重选位置并下载现有 Artifact，不重新查询设备或生成 CSV；历史 Artifact 仍可从 Task Center 的“另存 Artifact”人工保存。服务端 Artifact READY、任务 `COMPLETED` 与本地文件保存成功互不替代。只有 Main 完成 `.part` 流式写入、大小/SHA-256 校验、目标竞态复验、安全替换和最终文件 `stat` 复验并返回 `saved` 后，页面才显示文件名和用户选择的目录；后续打开/定位只使用短期 capability。

Save As 以前台实际 IPC sender 窗口为父窗口；Main 在弹窗前恢复最小化窗口并执行 show/focus。诊断日志只记录受控路由类别、文件名、窗口 ID/可见状态、大小和错误码，不记录完整本机路径、URL、Token 或凭据。

Electron Session 拒绝所有 Chromium 原生 `will-download`，因此 `<a download>`、Blob 或页面导航不能绕过该桥接。退出时先关闭新下载入口，取消并等待在途流清理后再停止受管 Python；Browser Platform Adapter 不受该 Electron 专用策略影响。

下载清理完成后，Main 才向 Python 发送 `shutdown`；Python 在 Uvicorn 完全退出后回报 `shutdown_ack`，Main 再发送 `exit`。Electron 只在 Bridge 下载、Python 后端和会话路径授权等受管清理全部结束后退出，不把仍在写入的 `.part` 留给下一次启动。

## 永久禁止

- 通用 `execute(command)`、任意 IPC channel 或完整 `ipcRenderer`；
- PowerShell/cmd、shell 字符串、`shell: true` 或 Renderer 提供的参数数组；
- Renderer 指定 Python/executable、环境变量、工作目录或 backend module；
- 任意文件系统读写、数据库路径、任意 URL/Header/目标路径或未知程序启动；
- 把 Agent Token、SSH/SNMP 凭据、密码或完整环境返回给 Renderer；
- 通过路径选择接口绕过 Artifact/Application Service 权限。

未来新增 `openArtifact`、`launchTerminal` 和 `notification` 仍必须单独增加 DTO、Feature、main 白名单、权限/审计和测试后才能开放。IPOP 仅允许通过 `launch_ipop` 语义动作启动已保存且再次校验的 `IPOP.EXE`；通用外部程序、任意路径和 argv 始终不在白名单。

文件管理模块已实现 `fda1_*`、60 秒有效、一次性消费的强类型动作契约，并在 main/preload/shared 增加独立白名单。Renderer 只能提交动作引用；main 调固定回环端点，Service 仅打开受控目录或启动固定 WinSCP。WinSCP 的 SSH 密码只在 Python 主进程消费动作后读取并 URL 编码，认证 URL 直接交给固定进程启动，不返回 Renderer、IPC 或 API；安全命令遮蔽原始和编码后密码。不得回退到 Renderer 路径、任意程序/argv 或由 Renderer 提供含密码 URL。验收状态见 [文件管理对等规格](development/parity/file-management.md)。
