# NetConsole 独立 Agent

仓库的 `agent/` 是 Windows x64 优先的独立 Go 子项目，用于现场采集和远程执行。它不进入 Python Qt6 主程序进程，也不共享 SQLite connection、Job Center 或 Export Process。

V1 已实现 iPerf server/client、并发 TCP fallback `ping_probe`、MR 持久 SSH Shell 原始日志采集、目标管理、统一任务生命周期、优雅退出和停止后 ZIP 包。最终任务状态在打包提交后发布。Agent 暴露 HTTP REST API，并内嵌同一套 API 驱动的轻量 Web 页面。完整构建、运行、配置、API 和限制见 [Agent README](../agent/README.md)。

边界：

- Controller 主动访问 Agent；Agent 不主动注册或上传；
- Agent 只保存最小目标连接信息，不复制完整业务点表；
- 密码不进入 API 明文响应、任务元数据、运行日志或采集包；
- MR 命令集中在 `agent/internal/mr/templates.go`，命令文本应持续与 `netconsole/services/online_mr/collection_commands.py` 对齐；
- Agent 运行数据限定在自己的 `agent/data`、`agent/logs`、`agent/packages`，不写入主程序数据目录；
- Windows 工具只读取配置指定的 `agent/tools/windows-x64/{iperf3,fping}` 标准目录，不扫描 Agent 旧目录；iPerf 子进程工作目录固定为 exe 所在目录，以加载同目录 Cygwin DLL；
- V1 尚不是 Python 主程序的多 Agent 管理页面，主程序集成属于后续工作。
- `GET /api/v1/capabilities` 是 Controller 的能力事实来源；旧 Agent 没有该接口时，Controller 必须保留未知状态，不能按操作系统推断。

Windows 构建入口：

```bat
agent\scripts\build_windows.bat
```

输出为 `agent/bin/windows-x64/netconsole-agent.exe`，不进入当前 Python 主程序发布白名单；正式联合发布前需要单独设计签名、版本和第三方许可证流程。
