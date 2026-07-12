# NetConsole Agent V1（Windows）

`netconsole-agent.exe` 是 NetConsole 的独立现场采集与远程执行 Agent，不是第二套主程序。它既能由 NetConsole 后续通过 HTTP API 控制，也能在没有主程序时通过内置 Web 页面操作。

## V1 功能范围

- iPerf3 server/client 启停与原始日志；
- 车载 MR SSH 在线原始回显采集；
- `ping_probe` 高频连通性探测；
- 本地目标设备管理、统一任务状态、日志 tail、停止后 ZIP 打包和下载。

V1 不实现通用命令平台、AP/AC/SNMP 采集、离线分析、报表导出、主动注册/上传或多 Controller。

## Windows 构建

要求 Windows x64 和 Go 1.26.5，不要求 Node、Python、数据库或外部服务。项目通过 `go.mod` 中的 `go 1.26.5` 和 `go.sum` 固定构建基线与依赖，不需要 Python 式虚拟环境：

```bat
cd agent
scripts\build_windows.bat
```

输出：`agent/bin/windows-x64/netconsole-agent.exe`。构建脚本会执行 `go mod download`、`go test ./...` 后再构建。

构建脚本优先使用 PATH 中的 `go.exe`；若未加入 PATH，会回退到 `D:\Program Files\Go\bin\go.exe`。Go 的模块缓存和编译缓存默认位于用户目录并由不同项目共享，不应复制到 `agent/` 或提交仓库。

## Windows 运行

```bat
cd agent
scripts\start_windows.bat
```

也可直接从 `agent` 目录运行：

```bat
bin\windows-x64\netconsole-agent.exe -config config.json -targets targets.json
```

默认监听 `0.0.0.0:18080`，浏览器访问 `http://127.0.0.1:18080`。涉及中文日志时建议使用 UTF-8 终端；批处理已执行 `chcp 65001`。

## 配置

V1 使用标准库可直接读取的 `config.json`，不引入 YAML 依赖。相对路径均以配置文件所在目录为基准。主要配置段：

- `agent`：Agent ID/名称、监听地址、数据/日志/采集包目录；
- `security`：Token 和预留 Web 账号字段；`enable_auth` 默认 `false`；
- `tools`：Windows x64 `iperf3` 和可选 fping 的配置路径；所有路径均可覆盖，但不会扫描或回退旧目录；
- `runtime`：自动打包及保留天数（V1 记录配置，尚不自动清理现场数据）；MR 请求的 `auto_package_on_stop=true` 可在全局关闭时单任务启用打包；
- `ping_probe`：默认间隔、超时、包大小、目标上限和 TCP fallback 端口。

启用鉴权后，API 请求必须携带 `X-Agent-Token`。Web 页顶部可保存 Token 到当前浏览器会话；Token、Web 密码和目标密码不会由配置/目标 API 明文返回。

## targets.json

目标文件只保存最小连接信息：

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

密码 V1 可明文保存在本机 `targets.json`，文件写入权限为仅当前用户优先；API、任务元数据、日志和 ZIP 快照均使用 `******` 脱敏。导出的 JSON 也是脱敏版本，不能作为带密码备份。

## iperf3.exe

Windows 工具统一使用以下标准目录：

```text
agent/tools/windows-x64/
├─ iperf3/
│  ├─ iperf3.exe
│  ├─ cygwin1.dll
│  ├─ cygcrypto-3.dll
│  └─ cygz.dll
└─ fping/
   └─ fping.exe
```

默认配置路径分别为：

```text
./tools/windows-x64/iperf3/iperf3.exe
./tools/windows-x64/fping/fping.exe
```

不再支持 `agent/tools/iperf/` 等旧目录，也不做 legacy fallback。使用 Cygwin 版 iPerf3 时，exe 和三个 DLL 必须位于同一个 `iperf3/` 目录；Agent 启动子进程时会把工作目录设置为该目录。缺少 exe 或 DLL 时不会创建伪运行任务，API 和 Web 会给出当前配置路径及放置提示。

Windows V1 的 fping 仅做工具检测，不参与 `ping_probe`。`ping_probe` 继续使用并发 TCP connect fallback。

## API 摘要

基础：

```text
GET /api/v1/ping
GET /api/v1/status
GET /api/v1/capabilities
GET /api/v1/config
GET /api/v1/tools/status
```

目标：`GET/POST /api/v1/targets`、`PUT/DELETE /api/v1/targets/{id}`、导入、导出和连接测试。

任务：`GET /api/v1/tasks`、`GET /api/v1/tasks/{id}`、`POST /api/v1/tasks/{id}/stop`、`GET /api/v1/tasks/{id}/logs?tail=200`。

能力入口：`/api/v1/iperf/server/*`、`/api/v1/iperf/client/*`、`/api/v1/ping-probe/*`、`/api/v1/mr/collect/*`。

采集包：`GET /api/v1/packages`、`GET /api/v1/packages/{id}/download`、`DELETE /api/v1/packages/{id}`。

统一响应：成功为 `{"ok":true,"data":...}`，失败为 `{"ok":false,"error":{"message":"..."}}`。工具错误会额外返回 `path`、`hint` 和 `required_files`；同类任务重复启动返回 HTTP 409，并包含已有 `task_id`。Web 状态页会显示 iperf3/fping 的检测结果、iPerf 路径和版本；排错时先查看 `/api/v1/tools/status`。

`GET /api/v1/capabilities` 返回 Agent 自报能力。内建 `ping_probe`、Online MR 采集直接报告可用；iPerf/fping 能力依据 Agent 当前工具检测结果报告。Controller 不应根据操作系统猜测能力，旧 Agent 缺少该接口时应将能力保留为未知。

## 任务与采集包

每个任务写入：

```text
data/tasks/<task_id>/
├─ task.json
├─ runtime.log
├─ stop_reason.json
├─ target_snapshot.json（有关联目标时）
├─ raw/
└─ meta/
```

完成/停止/失败后默认在 `packages/<task_id>.zip` 原子提交采集包。包内包含 `manifest.json`、任务/目标/Agent/系统/停止信息、`agent_runtime.log` 和实际存在的 `raw/` 文件。最终 `completed/failed` 状态只在打包成功或明确失败后发布，因此成功响应中的 `package_id` 与下载地址已可用；打包失败保留任务目录和原始日志。

## MR 命令边界

MR V1 优先 SSH，只保存原始回显，不做解析。固定命令集中在 `internal/mr/templates.go`，与 Python 主程序 `netconsole/services/online_mr/collection_commands.py` 的命令文本对齐。Terminal Monitor 和四类周期采集分别使用持久 PTY Shell，停止时协作关闭全部 Session 和 SSH Client，避免按固定等待时间截断设备回显。SSH Host Key V1 尚未配置已知主机校验，适用于受控现场网；后续应加入指纹固定。

Agent 收到 Ctrl+C 或终止信号时会先停止 HTTP 接入，再取消运行任务并等待日志关闭和打包；超过等待上限才退出。iPerf 子进程使用 Windows 进程终止语义回收，不在任务停止后留驻。

## 当前限制

- Windows x64 第一版；
- Agent 不主动注册、上传，也不知道 Controller 地址；
- Agent 不做复杂业务分析；
- MR 第一版仅实现 SSH，Telnet 仅在目标连接测试中做 TCP 检查；
- `ping_probe` V1 采用 TCP connect fallback，事件明确标记 `mode=tcp`，默认端口 80 可在请求中用 `tcp_port` 修改；它验证端口连通性，不等同于 ICMP 丢包；
- 任务/采集包保留天数尚未启用自动清理，避免静默删除现场证据；
- 未在真实 MR 和真实车地无线链路上验证，需按局点账号、命令权限、周期和链路条件现场验收。
