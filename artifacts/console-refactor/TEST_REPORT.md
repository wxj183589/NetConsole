# Console R2 Test Report

日期：2026-11-23

| 检查 | 结果 |
| --- | --- |
| Terminal/Feature Python 定向测试 | PASS：78 passed；1 个 Starlette/httpx 弃用 warning |
| SSH 隔离 Server | PASS：Paramiko 认证、PTY、`invoke_shell()`、实时输入输出、resize |
| Telnet 隔离 Server | PASS：登录、IAC 分片、TTYPE、NAWS、配置模式输入 |
| SFTP 隔离 Server | PASS：独立 Paramiko subsystem、浏览、上传、下载、复制、路径边界 |
| 控制台/自动化同时运行 | PASS：终端 transport 与 Netmiko `ConnectHandler` 为独立对象，关闭终端不影响自动化线程 |
| Renderer 定向 Vitest | PASS：4 files，27 tests |
| Renderer build | PASS：`vue-tsc -b && vite build`；仅既有大 chunk warning |
| Electron Vitest + typecheck | PASS：38 files，318 tests；`tsc --noEmit` PASS |
| 真实 Electron 隔离视觉捕获 | PASS：1920×1080、2560×1440、1024×680、SFTP、设置；无 page/console error |
| Python wheel 资源 | PASS：包内包含两份 `terminal_rules/*.json` |
| 附件规则逐行一致性 | PASS：高亮 22/22、高危命令 226/226，逐字段零差异 |
| 自动化代表性 Netmiko 回归 | PASS：15 passed；AC、光衰并发/异常隔离、配置备份、受控保存、批量和取消 |
| Workspace layout gate | BLOCKED：任务前已有根级 `artifacts/build` 和两个未纳管 worktree 目录；未清理 |
| 真实网络设备 | NOT RUN（没有现场设备授权） |

## 控制台覆盖

- Paramiko interactive Shell，不调用 Netmiko `send_command`。
- Telnet IAC/login/TTYPE/NAWS，不使用 SSH Jump Host。
- Ticket 单次消费、过期、非法 Origin、输入/resize/ping WebSocket 契约。
- 多会话状态、关闭、重连、活动标签重新附着和有界显示缓冲。
- 自动 JSONL 与手动日志独立 writer、暂停/恢复/导出、队列满标记不完整。
- SFTP 独立连接、传输进度、取消、重试和结果下载。
- 高危命令只产生警告和审计，原始命令仍写入交互 transport。

## 自动化边界

- 既有 AC/光衰/设备采集、配置备份与受控保存继续统一走共享 Netmiko 适配层。
- 有界并发、单设备失败隔离、批量结果和任务取消已做代表性回归。
- 仓库当前没有“任意配置命令下发”的完整产品/API 闭环；本轮未新增危险的通用下发入口，状态为 `NOT_IMPLEMENTED`。
- 真实设备上的光衰、AC、配置备份/写入和控制台并行运行仍为 `NOT VERIFIED`。
