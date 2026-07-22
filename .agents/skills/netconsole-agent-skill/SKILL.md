---
name: netconsole-agent-skill
description: "NetConsole Windows Go Agent、apps/agent、Agent HTTP API、内嵌 Web、目标管理、config/targets、fping/iPerf 工具检测、MR sidecar、Agent 构建打包、防休眠、任务事件、采集包或 Agent 运行目录任务时使用。纯 Python Controller 使用相关服务文档；流量测试参数语义使用 traffic-test-skill；MR 命令规则使用 netconsole-online-mr-skill。"
---

# 目标

维护 `apps/agent/` Windows Go Agent V1 的 API、内嵌 Web、配置、目标文件、工具路径、任务事件、采集包、sidecar 和构建/运行目录边界。Agent 是独立执行端，不是 Electron/Python Core 的第二套业务核心。

# 触发场景

- 修改 `apps/agent/` 的 HTTP API、Web、目标管理、任务生命周期或采集包。
- 修改 Agent 的 `config.json`/`targets.json` 查找、工具检测、fping/iPerf/MR sidecar 调度或防休眠。
- 修改 Agent Windows 构建、启动、清理脚本、交付包布局或运行数据目录。
- 评审 Python Controller 与 Agent Traffic Adapter/Supervisor 的接入边界。

# 不适用范围

- 不处理 Electron/Vue 主界面；相关任务按 Vue、FastAPI 和 Electron Main/Preload 边界处理。
- 不修改 MR 命令顺序、回显解析或采集规则，除非同时读取 `netconsole-online-mr-skill`。
- 不修改 fping/iPerf 参数语义、阈值、模板或流量指标，除非同时读取 `traffic-test-skill`。
- 不处理 CentOS 离线部署，除非任务明确要求。
- 不把 Windows Go Agent 误写成 Job Center 已完全远程化；普通 Job Center 仍以本地 Worker Process 为主。

# 关键代码和资源

- `apps/agent/cmd/`
- `apps/agent/internal/`
- `apps/agent/web/`
- `apps/agent/scripts/build_windows.bat`
- `apps/agent/mr_collector_py/`
- `apps/agent/resources/config/`
- `src/netconsole/services/agent/`
- `src/netconsole/models/agent_traffic.py`
- `resources/tools/windows-x64/`

# 目录规则

- Agent 运行数据不得写入 `apps/agent/`。
- 开发态使用 `.local/agent/`；打包态使用 `%LOCALAPPDATA%\NetConsole\Agent`。
- 构建输出统一使用 `dist/agent/`，不得在 `apps/agent/bin`、`apps/agent/dist` 或 sidecar 的 `build/dist` 留存产物。
- 版本化第三方工具唯一来自 `resources/tools/`；`tools/` 只用于开发、诊断、维护和协议分析。
- `apps/agent/tools/` 永久禁止使用；交付包内的 `tools/windows-x64/` 只是包内部布局。
- `apps/agent/resources/config/` 只保存 `config.example.json`、`targets.example.json` 等模板；不得提交真实配置、密码、Token 或现场目标。

# 工具与 sidecar 规则

- Agent 只白名单打包 fping、iperf3 和自建 MR sidecar。
- IPOP 不是 Agent 依赖，不复制到 Agent 包；用户自备 IPOP 仍遵守桌面端许可证和发布规则。
- 缺失 fping、iperf3、DLL 或 MR sidecar 时，构建/启动/API 必须给出明确路径提示，不静默回退旧目录。
- 第三方二进制必须记录来源、版本、许可证和运行依赖；iPerf3/Cygwin 许可证或 NOTICE 材料未齐全前，不随意替换或扩大分发范围。

# 工作流程

1. 先读取 `docs/AGENT.md`、`apps/agent/README.md`、`docs/BUILD_AND_RELEASE.md`、`docs/AGENT_TRAFFIC_API.md` 和 `resources/tools/README.md`。
2. 先确认实际代码、测试和构建脚本，再判断改动属于 Agent、Controller、Traffic 或 Online MR 边界。
3. 修改路径时同步检查 CLI 参数、环境变量、配置/目标查找顺序、交付包内部路径、启动脚本和运行数据目录。
4. 不跨进程共享 SQLite connection、Renderer 状态、Repository 或凭据；Agent Token 只由 Controller 在请求时提供。
5. 保留失败、取消、停止、强制结束和采集包清理语义；不通过吞异常、扩大超时或静默跳过掩盖问题。
6. 核对能力现状：Traffic 已接入；Online MR 单 Agent executor/Web 入口已实现但默认关闭，只提供固定 start/status/normal stop、截止时间和包导入。不得继续写成“尚未接远程生命周期”，也不得扩写为强停、多 Agent或主动注册。

# 验证

```powershell
cd apps/agent
go test ./...
cd ../..
python -m pytest -q tests -k "agent or traffic"
python -m compileall apps/agent src
```

同时检查：

- 构建脚本只从 `resources/tools/` 复制 fping/iPerf；
- `apps/agent/tools/`、源码目录运行数据和旧 `apps/agent/dist/` 没有实现依赖；
- 配置模板为 example 命名，真实 `config.json`/`targets.json` 不在 Git；
- 构建和启动缺失工具时的错误信息包含可操作路径；
- 不提交 `.local/`、日志、任务目录、采集包、缓存、构建产物或来源不明 EXE。

# 风险与报告

报告必须区分：

- Agent V1 已实现的 API、Web、任务、工具、sidecar 和采集包能力；
- Controller/Traffic 已接入的 REST/WebSocket/Vue 能力与仍待真实环境验收的边界；
- Online MR AGENT executor 的开关、固定路由、Token 内存边界、包最终化和真实 MR 待验收状态；
- CentOS 离线部署、主动注册、多 Controller 和完整远程运维等规划项；
- iPerf3/Cygwin 许可证、NOTICE、来源哈希和对应源码分发责任；
- 已执行的 Go/Python/compileall/路径检查命令和未执行的构建或现场验证。

常见失败模式：把 `ping_probe` 当作 ICMP、让 Agent 主动注册、把 Token 写入配置/Task、让 Go Agent 执行任意 MR 命令、把远端终态在包导入前标成 Controller 完成。
