# NetConsole 独立 Agent

仓库的 `apps/agent/` 是 Windows x64 优先的独立 Go 子项目，用于现场采集和远程执行。它不进入 Python Qt6 主程序进程，也不共享 SQLite connection、Job Center 或 Export Process。

V1 已实现 iPerf server/client、真实 fping、并发 TCP fallback `ping_probe`、Python Netmiko MR sidecar、fping/iPerf 跟随采集、实时视图、目标管理、统一任务生命周期、优雅退出和停止后 ZIP 包。最终任务状态在打包提交后发布。Agent 暴露 HTTP REST API，并内嵌原生 HTML/CSS/JS 现场采集控制台。完整构建、运行、配置、API 和限制见 [Agent README](../apps/agent/README.md)。

边界：

- Controller 主动访问 Agent；Agent 不主动注册或上传；
- Agent 只保存最小目标连接信息，不复制完整业务点表；
- 密码不进入 API 明文响应、任务元数据、运行日志或采集包；
- Go Agent 不执行 MR SSH；`apps/agent/mr_collector_py/collector_cli.py` 通过 Netmiko 执行采集，命令文本应持续与 `src/netconsole/services/online_mr/collection_commands.py` 对齐；
- Agent 运行数据默认位于 `%LOCALAPPDATA%\NetConsole\Agent\{data,logs,packages}`，开发态可通过 `NETCONSOLE_AGENT_PROJECT_ROOT` 使用 `.local/agent/{data,logs,tmp,runtime,packages}`，不写入主程序数据目录或源码目录；
- `resources/tools/windows-x64/{iperf3,fping}` 是版本化第三方工具的唯一源码来源；交付包内配置使用 `tools/windows-x64/{iperf3,fping,mr_collector}`，不扫描 `apps/agent/tools/` 或其他旧目录。Cygwin 工具和 sidecar 子进程工作目录固定为 exe 所在目录；
- `apps/agent/resources/config/{config.example.json,targets.example.json}` 只保存脱敏模板；首次通过源码或交付包启动脚本运行时，会仅在缺失时初始化 `%LOCALAPPDATA%\NetConsole\Agent\config.json` 与 `targets.json`，绝不覆盖真实配置；
- Windows 启动默认通过 `SetThreadExecutionState` 防止休眠，任务运行时可保持屏幕，退出时恢复系统电源行为；失败只写入状态，不阻断采集；
- Traffic 已通过 Application Service、Agent Adapter/Supervisor 和阶段 4C Web 入口完成调度同步；Online MR 阶段 5B-8 仅接入状态/任务/包查询、安全下载和本地 importer，尚未启用 AGENT executor 或远程 start/stop。
- `GET /api/v1/capabilities` 是 Controller 的能力事实来源；旧 Agent 没有该接口时，Controller 必须保留未知状态，不能按操作系统推断。

Windows 构建入口：

```bat
apps\agent\scripts\build_windows.bat
```

输出为 `dist/agent/windows-x64/`，临时构建目录为 `dist/agent/.build-windows-x64/`，包含 console 版、GUI 托盘版、sidecar（若构建环境可用）、工具目录和启动/兼容检查脚本；不进入当前 Python 主程序发布白名单。`apps/agent/bin|data|dist|logs|packages|tmp` 不作为源码子目录保留。

Python 控制面、凭据与数据库边界见 [Agent Controller](AGENT_CONTROLLER.md)，流量任务协议见 [Agent 流量测试协议](AGENT_TRAFFIC_API.md)，统一执行与恢复见 [流量测试架构](TRAFFIC_TEST_ARCHITECTURE.md)。
