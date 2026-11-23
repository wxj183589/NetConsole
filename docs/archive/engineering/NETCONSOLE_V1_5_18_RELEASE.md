# NetConsole v1.5.18 发布收口审查

日期：2026-11-23（Asia/Shanghai）。RELEASE_STATUS=PARTIAL。当前为发布候选，尚未合并、推送 main 或生成正式制品。

## 范围与保护

原分支 codex-A/console-r2-independent-terminal-netmiko，原 HEAD aa0a7c0a146432f6786149afb816488c62463d15。隔离分支 codex-A/release-v1.5.18-20261123 基于该 HEAD；github/main 为其直接父提交 9e463778，未丢弃主线历史。

只从原工作树带入逐项确认的控制台代码、测试与脚本；设备管理、导航重组、Syslog、MR 及其调查资料未纳入。共享保存路径 helper 是控制台手动日志的真实依赖，原导出消费者仍沿用原默认前缀规则。原工作树、其他 Worktree、DevStatus、Production/Dev 业务数据未改动。

## L4 Consumer Audit

| 契约 | 写入方 / Authority | 读取与缓存 | 展示 / 导出 / 兼容 | 回归 |
| --- | --- | --- | --- | --- |
| 产品版本 | core/version.py；Electron package 元数据同步 | Vite、Backend health、Main、Installer/Portable | HTML title、运行时日志、两份 CHANGELOG；Renderer 内部 package 0.1.0 不是产品版本 | shell-copy、changelog sync、version/build contract |
| 控制台生命周期 | TerminalSessionManager，Session ID | 常驻 Console Workspace、原 xterm buffer | SSH/Telnet 独立连接；路由隐藏不结束会话；局点切换重新初始化 | terminal tests、AppLayout、真实 Electron 80 次切换 |
| 命令分发 | Python BatchCommandDispatcher | 每会话 dispatch lock、独立 job receipt | Send String / 批量 / 新标签 / 独立窗口；仅汇总 Toast；SENT 只代表写入终端 | terminal_controls、ConsoleCommandBar、真实 SSH |
| SFTP / 下载 | SftpConnectionService 为每调用方创建独立实例 | TerminalSftpManager 独立队列、staging、任务日志 | Main 白名单端点保存；原后台下载生命周期独立；旧内部任务读取兼容保留 | terminal_sftp、file transfer、job center、Main/Preload、真实 SFTP |
| Electron IPC | Main 私有路径授权和 Session claim | Preload 白名单、DetachedTerminalWindowManager | Renderer 不接触 Socket 或明文密码；旧工作区状态不恢复过期终端连接 | Electron 全量、Renderer bridge、main contract smoke |

并行修改：原主检出存在其他任务 dirty；device-refactor-baseline-9e463778 和 syslog-phase5-main-20261119 是既有 detached Worktree，本任务不改动其源码。所有验证在隔离发布组合进行；尚未发生 main 集成，不能宣称合并后复验通过。

## 本轮修正

- 删除发送详情按钮、弹窗、逐会话表格及仅用于详情的取消/重试状态和调用；后端接口仍有 API/Dispatcher 测试消费者，保留。
- Toast 汇总实际写入/失败/未确认状态；并行提交分别轮询，失败不会自动重发，组件卸载清理监听。
- 显式选择 Session ID 优先于设备勾选，防止同一设备其他终端被意外纳入批量发送。
- 保留预览、逐行空行、CR/LF、间隔、快捷按钮、新标签和独立窗口协议。
- 版本 Authority、Electron package/productName、HTML title 为 1.5.18；运行时 CHANGELOG 由仓库正式同步工具生成，历史版本号未批量替换。
- 验收脚本使用真实终端 buffer / 后端回显代替已删除的详情表格；managed Worktree 的 fixture 复用 canonical test root helper。

## 已确认发布阻断

- Architecture Guard 的 ui-business-logic 发现 Ground 的 normalizeMac、normalizedStatus、classifyPingStatus、naturalSecondLossBuckets 四个未登记符号。相关源码与 github/main 一致，已在干净 main 基线复现。未降低 Guard、添加豁免或扩展修改 Ground 业务。
- Root Layout 报告 main 已跟踪的 NETCONSOLE_V1_5_17_RELEASE_NOTES.md 与 V1_5_17_CHANGELOG.md；未移动或删除历史文件。
- Workspace Layout 报告原主检出的 artifacts/build 和两个既有未纳管 DevStatus worktree 目录。本任务不移动、删除或清理这些历史内容。

按用户要求及发布 Skill 的“任一门失败停止发布”，完整 Gate 未通过前不合并正式主分支、不生成正式安装包，不满足条件时不删除本地分支。

## 当前真实 Electron 证据

独立 SSH/SFTP 回环服务器与真实 Electron，非 Mock UI。80 次业务切换保持三个原终端、未提交输入、原 xterm 实例及 Session ID；切换前后均为 4 TCP / 4 authentication / 3 Shell / 3 PTY。选中两个会话发送，第三个无该命令；新标签和独立窗口各有独立 Session ID，关闭独立窗口不影响原会话。分屏 54.3% / 45.7% 保留；离页下载保持同一 task_id；五个会话最终录制 COMPLETED。

1920×1080 是实际 Electron 窗口截图，物理显示模式为 2560×1440；原生 Save As 完整人工操作、Explorer 最终拖放、H3C/GBK 现场、安装/升级及长时运行仍 NOT VERIFIED。

详细命令日志、源文件范围哈希、Session ID 和最终 Git/制品结果位于 Workspace/reports/build/release-v1.5.18-20261123。最终结果见该目录 RELEASE_REPORT.md；本文件不将尚未执行的发布步骤写成成功。

PRODUCTION_DATA_MODIFIED=0
DATABASES_REMOVED=0
MAINTENANCE_AUTHORIZED=NO
