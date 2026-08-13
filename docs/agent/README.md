# NetConsole 独立 Agent

仓库的 `apps/agent/` 是 Windows x64 优先的独立 Go 子项目，用于现场采集和远程执行。它不进入 Electron 受管 Python Backend 进程，也不共享 SQLite connection、Job Center 或 Export Process。

V1 已实现 iPerf server/client、真实 fping、并发 TCP fallback `ping_probe`、Python Netmiko MR sidecar、fping/iPerf 跟随采集、实时视图、目标管理、统一任务生命周期、优雅退出和停止后 ZIP 包。最终任务状态在打包提交后发布。Agent 暴露 HTTP REST API，并内嵌原生 HTML/CSS/JS 现场采集控制台。完整构建、运行、配置、API 和限制见 [Agent README](../../apps/agent/README.md)。

边界：

- Controller 主动访问 Agent；Agent 不主动注册或上传；
- Agent 只保存最小目标连接信息，不复制完整业务点表；
- 密码不进入 API 明文响应、任务元数据、运行日志或采集包；
- Go Agent 不执行 MR SSH；`apps/agent/mr_collector_py/collector_cli.py` 通过 Netmiko 执行采集，命令文本应持续与 `src/netconsole/services/online_mr/collection_commands.py` 对齐；
- Agent 的配置、目标、任务、日志和采集包统一位于 `D:\NetConsoleData\agents\local\{config.json,targets.json,data,logs,packages}`；`NETCONSOLE_DATA_ROOT` 可指向已持久化的唯一根，`NETCONSOLE_AGENT_HOME` 只能是其 `agents/` 子目录，绝不回退 LocalAppData、用户目录、交付目录或源码目录；
- `resources/tools/windows-x64/{iperf3,fping}` 是版本化第三方工具的唯一打包来源；Agent 构建复制前后均运行离线来源、精确文件集合、哈希、GPLv3/LGPLv3/链接例外、实际 fping 补丁与对应源码 Guard，不联网下载业务工具。交付包内配置使用 `tools/windows-x64/{iperf3,fping,mr_collector}`，不扫描 `apps/agent/tools/` 或其他旧目录。Cygwin 工具和 sidecar 子进程工作目录固定为 exe 所在目录；
- `apps/agent/resources/config/{config.example.json,targets.example.json}` 只保存脱敏模板；首次通过源码或交付包启动脚本运行时，仅在缺失时初始化统一 Agent 目录中的 `config.json` 与 `targets.json`，绝不覆盖真实配置；
- Windows 启动默认通过 `SetThreadExecutionState` 防止休眠，任务运行时可保持屏幕，退出时恢复系统电源行为；失败只写入状态，不阻断采集；
- Traffic 已通过 Application Service、Agent Adapter/Supervisor 和阶段 4C Web 入口完成调度同步；Online MR 的单 Agent、单 MR executor 与独立 Web AGENT 页签也已实现，默认由 `ONLINE_MR_AGENT_EXECUTOR_ENABLED=1` 开启，只允许固定 start/status/normal stop、Controller 到期停止、包下载和安全导入。远端强停、多 Agent 编排、包删除和任意命令仍未开放。
- `GET /api/v1/capabilities` 是 Controller 的能力事实来源；旧 Agent 没有该接口时，Controller 必须保留未知状态，不能按操作系统推断。

Windows 构建入口：

```bat
apps\agent\scripts\build_windows.bat
```

输出为 `dist/agent/windows-x64/`，临时构建目录为 `dist/agent/.build-windows-x64/`，包含 console 版、GUI 托盘版、sidecar（若构建环境可用）、工具目录和启动/兼容检查脚本；不进入当前 Python 主程序发布白名单。`apps/agent/bin|data|dist|logs|packages|tmp` 不作为源码子目录保留。

当前构建和开发验收目标仍是 Windows 11 x64。Windows Server 2012 x64 的 Agent 已有用户现场运行确认，证据等级为 `USER_FIELD_CONFIRMED`；仓库没有隔离 Server 2012 自动化 VM 记录，自动化证据记为 `AUTOMATION_NOT_RECORDED`。这记录的是现场兼容事实，不等同于正式安装包 GUI 或完整工具链自动化通过；不新增按操作系统阻断 Agent 启动的逻辑。Windows 10 仍无仓库或现场确认，不得写成已支持。CentOS 7.4 没有 Agent 实现或离线交付包。离线 Windows 构建只使用仓库锁定依赖、Go module 缓存和 `resources/tools/windows-x64/` 白名单资源，不在构建时联网补齐业务工具。

Python 控制面、凭据与数据库边界见 [Agent Controller](./CONTROLLER.md)，Online MR 远程生命周期见 [Online MR Agent 远程执行器](../rail-transit/online-mr/AGENT_EXECUTOR.md)，流量任务协议见 [Agent 流量测试协议](./TRAFFIC_API.md)，统一执行与恢复见 [流量测试架构](../traffic/README.md)。
