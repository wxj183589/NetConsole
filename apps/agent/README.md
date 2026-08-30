# NetConsole Agent V1（Windows）

`netconsole-agent.exe` 是 NetConsole 的独立现场采集与远程执行 Agent，不是第二套主程序。它既能由 NetConsole 后续通过 HTTP API 控制，也能在没有主程序时通过内置 Web 页面操作。

## V1 功能范围

- iPerf3 server/client 启停、强类型参数与增量原始事件；
- 真实 fping/ICMP 高频 Ping、结构化样本和摘要；
- 车载 MR 在线收集由 Python + Netmiko sidecar 执行，包含 fping 和可选 iPerf Client 跟随采集、实时预览和原始日志 tail；
- `ping_probe` TCP Connect 连通性探测；
- 本地目标设备管理、统一任务状态、事件游标、结果描述、日志 tail、停止后 ZIP 打包和下载。

V1 不实现通用命令平台、AP/AC/SNMP 采集、离线分析、报表导出、主动注册/上传或多 Controller。

## Windows 构建

要求 Windows x64 和 Go 1.26.5，不要求 Node、Python、数据库或外部服务。项目通过 `go.mod` 中的 `go 1.26.5` 和 `go.sum` 固定构建基线与依赖，不需要 Python 式虚拟环境：

```bat
cd apps\agent
scripts\build_windows.bat
```

输出：`dist/agent/windows-x64/`，同时生成 console 版和 Windows 托盘版。构建脚本会先对仓库根 `resources/tools/windows-x64/` 执行离线哈希/来源/许可证 Guard，再尝试构建 MR Collector、执行 `go mod tidy` 和 `go test ./...`；fping/iPerf 只从该本地白名单复制，复制后的交付目录还会复验一次，不从 Agent 子目录或根 `tools/` 复制，也不在构建中下载业务工具。临时构建目录位于 `dist/agent/.build-windows-x64/`，不会写回 `apps/agent/`。

构建脚本优先使用 PATH 中的 `go.exe`；若未加入 PATH，会回退到 `D:\Program Files\Go\bin\go.exe`。Go 的模块缓存和编译缓存默认位于用户目录并由不同项目共享，不应复制到 `apps/agent/` 或提交仓库。

## Windows 运行

```bat
cd dist\agent\windows-x64
start_agent.bat
```

首次运行 `apps\agent\scripts\start_windows.bat`、交付包的 `start_agent.bat` 或 `start_console.bat` 时，脚本会仅在缺失时自动创建：

```text
D:\NetConsoleData\agents\local\config.json
D:\NetConsoleData\agents\local\targets.json
```

源码启动脚本从 `apps/agent/resources/config/` 复制模板；交付包脚本从包内的 `config.example.json` 和 `targets.example.json` 复制。已有真实配置绝不会被覆盖。首次初始化后按提示编辑上述统一数据根文件，再填入现场 MR / iPerf 目标；真实配置不得提交到 Git。

源码联调同样使用正式数据根；只有自动测试才可显式改用 `D:\study\NetConsole-Workspace\test-data\NetConsole\<run-id>`：

```powershell
$agentHome = 'D:\NetConsoleData\agents\local'
New-Item -ItemType Directory -Force $agentHome | Out-Null
if (!(Test-Path "$agentHome\config.json")) { Copy-Item apps\agent\resources\config\config.example.json "$agentHome\config.json" }
if (!(Test-Path "$agentHome\targets.json")) { Copy-Item apps\agent\resources\config\targets.example.json "$agentHome\targets.json" }
$env:NETCONSOLE_DATA_ROOT = 'D:\NetConsoleData'
$env:NETCONSOLE_AGENT_PROJECT_ROOT = (Get-Location).Path
Set-Location apps\agent
go run .\cmd\netconsole-agent --console --open
```

默认监听 `0.0.0.0:18080`，浏览器访问 `http://127.0.0.1:18080`。涉及中文日志时建议使用 UTF-8 终端；批处理已执行 `chcp 65001`。

## 配置

V1 使用标准库可直接读取的 JSON 配置，不引入 YAML 依赖。版本化模板位于 `apps/agent/resources/config/config.example.json`；真实配置不得放回源码目录。默认配置为 `D:\NetConsoleData\agents\local\config.json`；`NETCONSOLE_DATA_ROOT` 可选择唯一根，`NETCONSOLE_AGENT_HOME`、命令行 `--config` 和 `NETCONSOLE_AGENT_CONFIG` 仅可指定该根 `agents/` 子树中的绝对路径。不存在 LocalAppData、用户目录、当前工作目录、源码目录或可执行文件旁的回退。`agent` 运行目录和用户显式配置的相对工具路径均以活动配置文件所在目录为基准；默认工具路径按交付包和源码资源规则解析。主要配置段：

- `agent`：Agent ID/名称、监听地址；数据、日志和采集包默认相对于活动配置目录写入 `D:\NetConsoleData\agents\local\{data,logs,packages}`，配置覆盖也必须仍位于统一根的 `agents/` 子树；
- `security`：Token 和预留 Web 账号字段；`enable_auth` 默认 `false`；
- `tools`：Windows x64 `iperf3`、fping 和 MR sidecar 的交付包路径；所有路径均可覆盖，但不会扫描或回退旧目录；
- `power`：启动防休眠、任务运行时保持屏幕和退出恢复，默认均为 `true`；
- `runtime`：自动打包及保留天数（V1 记录配置，尚不自动清理现场数据）；MR 请求的 `auto_package_on_stop=true` 可在全局关闭时单任务启用打包；
- `ping_probe`：默认间隔、超时、包大小、目标上限和 TCP fallback 端口。

启用鉴权后，API 请求必须携带 `X-Agent-Token`。Web 页顶部可保存 Token 到当前浏览器会话；Token、Web 密码和目标密码不会由配置/目标 API 明文返回。

## targets.json

真实目标文件默认与活动 `config.json` 放在同一运行目录；版本化模板为 `apps/agent/resources/config/targets.example.json`。目标文件只保存最小连接信息：

```json
{
  "targets": [
    {
      "id": "mr-ct-001",
      "name": "列车07-MR-CT",
      "type": "mr",
      "host": "192.168.10.11",
      "protocol": "ssh",
      "port": 22,
      "username": "admin",
      "password": "",
      "remark": "车头MR"
    }
  ]
}
```

密码 V1 可明文保存在本机运行目录的 `targets.json`，文件写入权限为仅当前用户优先；API、任务元数据、日志和 ZIP 快照均使用 `******` 脱敏。导出的 JSON 也是脱敏版本，不能作为带密码备份。示例目标含演示地址，不得直接当作生产目标使用。

## iperf3.exe

Windows 工具统一使用以下标准目录：

```text
tools/windows-x64/
├─ iperf3/
│  ├─ iperf3.exe
│  ├─ cygwin1.dll
│  ├─ cygcrypto-3.dll
│  └─ cygz.dll
└─ fping/
   ├─ fping.exe
   └─ cygwin1.dll
└─ mr_collector/
   └─ netconsole-mr-collector.exe
```

默认配置路径分别为：

```text
./tools/windows-x64/iperf3/iperf3.exe
./tools/windows-x64/fping/fping.exe
./tools/windows-x64/mr_collector/netconsole-mr-collector.exe
```

不再支持 `apps/agent/tools/iperf/` 等旧目录，也不做 legacy fallback。使用 Cygwin 版工具时，exe 和对应 DLL 必须位于同一个工具目录；Agent 启动子进程时会把工作目录设置为 exe 所在目录。缺少 exe 或 DLL 时不会创建伪运行任务，API 和 Web 会给出当前配置路径及放置提示。

仓库内置 iPerf3 固定为用户提供并经哈希核验的 `ar51an/iperf3-win-builds` 3.21 `win64-dynamic-auth`。fping 固定为本地构建的 v5.5 加已归档 Cygwin ICMP 兼容补丁，运行时为 Cygwin 3.6.9-1。两套工具的 `SOURCE_PROVENANCE.json`、固定文件哈希、GPLv3/LGPLv3/链接例外与对应源码说明必须随工具目录一起进入 Agent 包；fping 还必须携带补丁和构建配方。不能用同名未知二进制替换、混入额外文件或在构建时联网补齐。

默认工具路径先检查 Agent 可执行文件同级的 `tools/windows-x64/`；开发态其次检查 `$NETCONSOLE_AGENT_PROJECT_ROOT/resources/tools/windows-x64/`，再从活动配置目录向上查找仓库 `resources/tools/windows-x64/`，最后才回退到配置目录相对路径。用户显式配置的绝对路径直接使用，相对路径仍以 `config.json` 所在目录解析。MR sidecar 使用同一交付包优先规则。`apps/agent/resources/` 只保存 Agent 示例配置；运行时工具不在此目录复制第二份，避免与根 `resources/tools/` 产生双来源。`apps/agent/tools/` 永久禁止使用。

真实 fping 使用独立 `fping` 任务类型，固定调用随 Agent 部署的 fping 5.5 参数，不接受任意命令、工具路径或输出路径。`ping_probe` 继续使用并发 TCP Connect，事件保持 `mode=tcp`，不等同于 ICMP Ping。

## API 摘要

基础：

```text
GET /api/v1/ping
GET /api/v1/status
GET /api/v1/capabilities
GET /api/v1/config
GET /api/v1/tools/status
GET /api/v1/power/status
POST /api/v1/power/prevent-sleep
POST /api/v1/power/prevent-sleep-display
POST /api/v1/power/restore
```

目标：`GET/POST /api/v1/targets`、`PUT/DELETE /api/v1/targets/{id}`、导入、导出和连接测试。

任务：`GET /api/v1/tasks`、`GET /api/v1/tasks/{id}`、`POST /api/v1/tasks/{id}/stop`、`GET /api/v1/tasks/{id}/logs?tail=200`、`GET /api/v1/tasks/{id}/events`、`GET /api/v1/tasks/{id}/result`。

能力入口：`/api/v1/iperf/server/*`、`/api/v1/iperf/client/*`、`/api/v1/fping/*`、`/api/v1/ping-probe/*`、`/api/v1/mr/collect/*`。MR 页面还使用 `/api/v1/mr/collect/live`、`raw-tail` 和 `raw-summary`。

采集包：`GET /api/v1/packages`、`GET /api/v1/packages/{id}/download`、`DELETE /api/v1/packages/{id}`。

统一响应：成功为 `{"ok":true,"data":...}`，失败为 `{"ok":false,"error":{"message":"..."}}`。工具错误会额外返回 `path`、`hint` 和 `required_files`；同类任务重复启动返回 HTTP 409，并包含已有 `task_id`。Web 状态页会显示 iperf3/fping 的检测结果、iPerf 路径和版本；排错时先查看 `/api/v1/tools/status`。

`GET /api/v1/capabilities` 返回 Agent 自报能力。内建 `ping_probe`/`tcp_ping_probe`、任务事件、结果和 Online MR 采集直接报告可用；iPerf/fping 能力依据 Agent 当前工具检测结果报告。Controller 不应根据操作系统猜测能力，旧 Agent 缺少该接口时应将能力保留为未知。

流量参数、事件游标、结果和错误码的完整契约见 [Agent 流量测试协议](../../docs/agent/TRAFFIC_API.md)。旧 iPerf `extra_args` 只为兼容保留并继续过滤，新 Python Typed Client 不发送该字段。

## 任务与采集包

每个任务写入：

```text
D:\NetConsoleData\agents\local\data\tasks\<task_id>\
├─ task.json
├─ events.jsonl
├─ result.json（支持结构化结果的任务）
├─ runtime.log
├─ stop_reason.json
├─ target_snapshot.json（有关联目标时）
├─ raw/
└─ meta/
```

完成/停止/失败后默认在 `D:\NetConsoleData\agents\local\packages\<task_id>.zip` 原子提交采集包。包内包含 `manifest.json`、任务/目标/Agent/系统/停止信息、`agent_runtime.log` 和实际存在的 `raw/` 文件。用户停止后的终态为 `cancelled`；自然完成为 `completed`，执行或打包失败为 `failed`。终态只在事件、结果和打包提交完成后发布；打包失败保留任务目录和原始日志。

## MR Netmiko sidecar 与命令边界

Go Agent 不执行 MR SSH；它只创建私有请求、启动和停止 sidecar。sidecar 使用 Netmiko `hp_comware`/`hp_comware_telnet`，命令与 `src/netconsole/services/online_mr/collection_commands.py` 对齐，生成主程序兼容的 `raw/`、`view/`、`session_meta.json`。标准 sidecar 路径为 `tools/windows-x64/mr_collector/netconsole-mr-collector.exe`；构建临时产物写入 `dist/agent/.build-windows-x64/`，不写入 `apps/agent/mr_collector_py/dist/`。停止时创建 `stop.request`，该文件不会进入最终 ZIP。

MR session 必须包含 `init_raw.log`、`config_collect_raw.log`、`terminal_monitor_raw.log`、`mesh_link_raw.log`、`channel_busy_raw.log`、`ap_radio_statistics_raw.log`、`switch_history_latest.log`、`interface_rate_raw.log`、`wireless_status_raw.log`、`collector_output_raw.log`、fping 三件套和 `iperf_client_raw.log`。实时视图位于 `view/live_mr_status.json`、`live_link_status.json`、`live_fping_status.json`、`live_iperf_status.json`。

Agent 收到 Ctrl+C 或终止信号时会先停止 HTTP 接入，再取消运行任务并等待日志关闭和打包；超过等待上限才退出。iPerf 子进程使用 Windows 进程终止语义回收，不在任务停止后留驻。

构建 MR Collector：

```bat
\.venv\Scripts\python.exe -m pip install -r requirements-build.txt -c constraints.txt
apps\agent\scripts\build_windows.bat
```

构建脚本优先使用仓库 `.venv` 中的 PyInstaller，只有项目虚拟环境不可用时才回退到 `PATH`；sidecar 构建失败或产物缺失会终止整个 Agent 构建，不允许生成缺组件的“成功”交付目录。普通 Agent 运行包不依赖开发机 Python。Go Agent 启动 sidecar 时会注入 `PYTHONUTF8=1` 和 `PYTHONIOENCODING=utf-8`。

## 当前限制

- Windows x64 第一版；
- Agent 不主动注册、上传，也不知道 Controller 地址；
- 当前正式构建/验收目标仍为 Windows 11 x64；Windows Server 2012 x64 的 Agent 有用户现场运行确认（`USER_FIELD_CONFIRMED`），仓库无隔离 Server 2012 自动化 VM 记录（`AUTOMATION_NOT_RECORDED`），不增加 OS 启动阻断；Windows 10 仍无仓库或现场确认，CentOS 7.4 Agent/离线包尚未实现；
- Agent 不做复杂业务分析；
- MR 第一版仅实现 SSH，Telnet 仅在目标连接测试中做 TCP 检查；
- `ping_probe` V1 采用 TCP connect fallback，事件明确标记 `mode=tcp`，默认端口 80 可在请求中用 `tcp_port` 修改；它验证端口连通性，不等同于 ICMP 丢包；
- 任务/采集包保留天数尚未启用自动清理，避免静默删除现场证据；
- 未在真实 MR 和真实车地无线链路上验证，需按局点账号、命令权限、周期和链路条件现场验收。
