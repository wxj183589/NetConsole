# Console R2 Phase 0 基线

日期：2026-11-23

## 结论

| 项目 | 状态 | 证据 |
| --- | --- | --- |
| 旧版 NetConsole 基线 | TESTED | `main`，起始 HEAD `9e463778`；开始前已检查 status、diff、未跟踪文件和 worktree |
| Device Management R1-R6 保护 | TESTED | 既有 dirty 文件保留；本专项只增量触碰路由/导航中的必要行 |
| SmartHub 研究 | TESTED | 仅读取 `device-console-modules` 与 UI reconstruction 文档 |
| NetConsole-Next 研究 | TESTED | 用户给出的 Workspace 内路径不存在；仅读取实际 `D:\study\NetConsole-Next-Workspace\NetConsole-Next` 当前源码 |
| Production 数据 | TESTED | 未访问 `D:\NetConsoleData`，未连接真实设备 |
| Workspace layout gate | BLOCKED | 既有根级 `artifacts/` 和两个未纳管 worktree 目录导致检查失败；未移动或清理历史内容 |

## 旧版能力基线

- Renderer：Vue + Electron；此前没有 xterm.js 内置交互终端。
- Backend：Python/FastAPI、Device Repository、SiteManager、凭据保护、Site SSH Relay、Paramiko 和 Netmiko。
- 连接边界：控制台使用 Paramiko `invoke_shell()`、独立 Telnet IAC 和 Paramiko SFTP；自动化继续使用 Netmiko。两者只共享设备、Site、凭据引用和连接配置，不共享活动连接。
- 文件保存：已有 `downloadBackendResource` 可承接 Electron 用户选定保存位置。

## 变更范围

- IMPLEMENTED：独立 `module.console` 路由和门禁、设备/会话/保存会话树、快速连接、多标签、双向分屏、xterm、TerminalSessionManager、Ticket WebSocket、完整交互输入、独立 SFTP、双日志、规则设置、历史与 TXT/JSONL 导出。
- NOT_IMPLEMENTED：AI、COM 串口、HTML 导出、跨进程崩溃恢复。批量命令属于 Netmiko 自动化任务，不进入交互 Shell 引擎。
- REAL_DEVICE_VERIFIED：否；任务明确禁止现场设备操作。
