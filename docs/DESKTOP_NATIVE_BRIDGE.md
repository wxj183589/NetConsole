# Desktop Native Bridge 契约

## 当前状态

Electron Desktop 第一阶段 Native Bridge 已实现基础白名单，代码位于 `apps/desktop_electron/src/{main,preload,shared}`。它只用于验证桌面宿主能力，不表示 Artifact、终端、通知或完整业务导出已经迁移。普通 Browser/Server Mode 没有 `window.netconsoleDesktop`，仍不能调用本机选择器或打开路径。

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
| `selectFile` | 过滤器、是否多选 | 数量、名称、扩展名、未知字段白名单 | 原生选择器 |
| `selectDirectory` | 无 | 原生目录选择器 | 原生选择器 |
| `chooseSavePath` | 安全文件名、过滤器 | 不接受路径或命令作为文件名 | 只选择目标位置 |
| `openPath` | 本轮对话框返回的路径 | 当前进程临时授权；仅目录或数据/报告扩展名白名单 | 打开已选择文件/目录 |
| `showItemInFolder` | 本轮对话框返回的路径 | 当前进程临时授权 | 在资源管理器定位 |
| `onBackendStatusChanged` | 固定回调 | 只接收脱敏状态 | 意外退出通知 |

`reportRendererReady` 仅用于自动开发冒烟的 health 结果回报，不接受 URL、路径、命令或令牌。

## 路径授权模型

Renderer 不能提交任意绝对路径。`selectFile`、`selectDirectory` 或 `chooseSavePath` 的 Electron 原生对话框返回值先由 main 规范化，再登记到当前进程内存授权表；后续 `openPath`/`showItemInFolder` 只接受与已登记项精确匹配的路径。退出时授权表清空，不持久化。

`openPath` 对文件使用允许列表，当前只接受常见文本、JSON/CSV、Markdown、PDF、Excel 和 ZIP；目录必须由目录选择器单独授予。`.exe`、`.py`、`.reg`、`.chm`、`.msc`、快捷方式、安装包和其他未知扩展名默认拒绝。此接口不是 `openArtifact` 的最终业务实现；后续 Artifact 必须通过 `artifact_id`、局点和受控路径解析。

## 文件导出边界

`chooseSavePath` 只返回用户确认的目标路径。报告生成、Excel/ZIP/PDF 内容、临时文件、原子替换、取消和文件占用处理继续属于 Python Application Service 与 Export Process。Electron Main/Preload 不读取数据库、不生成报告、不复制 Artifact 内容。

## 永久禁止

- 通用 `execute(command)`、任意 IPC channel 或完整 `ipcRenderer`；
- PowerShell/cmd、shell 字符串、`shell: true` 或 Renderer 提供的参数数组；
- Renderer 指定 Python/executable、环境变量、工作目录或 backend module；
- 任意文件系统读写、数据库路径、URL 打开或未知程序启动；
- 把 Agent Token、SSH/SNMP 凭据、密码或完整环境返回给 Renderer；
- 通过路径选择接口绕过 Artifact/Application Service 权限。

未来 `openArtifact`、受控 `openFolder`、`launchTerminal` 和 `notification` 必须单独增加 DTO、Feature、main 白名单、权限/审计和测试后才能开放。WinSCP、IPOP 与通用外部程序不在当前白名单。
