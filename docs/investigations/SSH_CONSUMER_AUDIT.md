# NetConsole SSH Consumer Audit

日期：2026-09-07
范围：共享 SSH 基础设施、局点配置、轨旁 AP、AC、设备管理、轨道交通采集及非 SSH 传输边界。

## 结论

NetConsole 的 Backend CLI 主栈是 Netmiko 4.7.0 + Paramiko 4.0.0。现有
`netmiko_connection.ConnectHandler` 是兼容性与诊断入口，但业务代码仍有若干
直接调用点。当前没有局点级 SSH Relay 配置，也没有通用的持久化加密凭据库。

Paramiko `direct-tcpip` 可复用：Netmiko 4.7 的 `BaseConnection` 接收 `sock`
并传给 Paramiko `SSHClient.connect`，因此目标设备可以使用 Jump Host 返回的
Channel 建立原有 Netmiko Shell。实现采用每个 Python Worker 进程、每个 site
一个健康 Transport，每个目标独立 Channel；不创建本地监听端口。

## Consumer matrix

| 模块 | 当前建连入口 | 数据/行为 | Relay 状态 |
| --- | --- | --- | --- |
| 轨旁 AP / 车站交换机 | `services/rail_transit/trackside_optical_collection.py::_collect_one_target` → `netmiko_connection.ConnectHandler` | 接口、LLDP、光模块、RX/TX | 已接入公共 facade |
| 轨旁 AP / AC 资源 | `services/rail_transit/trackside_optical_collection.py::_collect_fit_ap_optical_subtasks` → `h3c_ac_collect_service` | AC AP 状态、连接记录、AP 资源 | 已接入公共 facade |
| AC 管理 | `services/h3c_ac_collect_service.py` | `display wlan ...` 等现有 CLI 与 Parser | 已接入公共 facade |
| Optical | `services/h3c_optical_refresh_service.py`、轨旁交换机 adapter | 接口/光模块/光衰 | 已接入公共 facade |
| LLDP | 轨旁光衰采集、H3C collector、车载诊断 | CLI LLDP 邻居 | Backend SSH 走公共 facade |
| Device Management | `test_device_connection`、`run_netmiko_with_retry`、H3C detail collector | 版本、接口、PVID、LLDP、光模块、CLI | 已接入公共 facade |
| 轨道交通/Online MR | `online_mr_collector`、`car_network_diagnostic`、车辆采集 job | 实际 SSH CLI | 共享 facade 可路由；仍需专项现场验证 |
| FIT-AP 直接目标 | H3C FIT-AP optical 内部的 `hp_comware_telnet` | 目标 AP Telnet 命令 | 不属于 SSH Relay，保持原逻辑 |
| SFTP/文件传输 | `file_transfer_service.py`、旧 `ssh_tunnel.py` | Paramiko SFTP/本地临时转发 | 第一版不走站点 Relay；旧隧道显式不叠加 Relay |
| 外部终端 | `external_terminal.py` → SecureCRT/PuTTY/WinSCP | 外部进程 | 不透明代理，保持不支持内部 Relay |
| Windows MR Agent | `apps/agent/mr_collector_py/collector_cli.py` | 独立进程 standalone Netmiko | 第一版不传播站点 Relay 配置 |
| SNMP / Ping / Syslog | `device_snmp_client.py`、fping、syslog runtime | UDP/ICMP | 明确不支持 SSH Relay |

## Credentials and site storage

- 非秘密 Relay 配置写入现有局点 `sites/<directory>/site_meta.json`，字段为
  `ssh_relay_enabled`、`ssh_relay_host`、`ssh_relay_port`、
  `ssh_relay_username`、`ssh_relay_credential_ref` 和 revision。
- Jump 密码单独写入 `sites/<directory>/db/site_ssh_credentials.sqlite3`，
  仅保存 Windows DPAPI 密文；普通 JSON、设备密码字段和日志不保存 Jump 密码。
- 目标设备账号仍来自现有设备记录；不会复制到 Relay 配置，也不会用 Jump 账号
  登录目标设备。
- 新局点和没有新增字段的旧局点默认 `ssh_relay_enabled=false`，继续 Direct。

## Host key and failure boundaries

Jump Host 与 Target Device 使用独立 SSH 身份。Relay 路径使用 NetConsole
`known_hosts` 的严格校验；未知或变更的主机密钥不会被静默接受。

公共错误码保留以下边界：

- `JUMP_CONNECT_FAILED`
- `JUMP_AUTH_FAILED`
- `JUMP_CHANNEL_FAILED`
- `TARGET_CONNECT_FAILED`
- `TARGET_AUTH_FAILED`
- `TARGET_COMMAND_FAILED`

Ping/ICMP、SNMP UDP/161、Syslog UDP、fping、VPN、SOCKS、ProxyChain 和多级
Jump 不在本能力范围内。

## Parallelism and lifecycle

轨旁 AP 同时运行 AC/FIT-AP 分支与交换机线程池。Transport 的创建、健康检查、
失效和 Channel 创建受站点 manager 锁保护；Target Session 关闭不会关闭 Jump
Transport。Transport inactive 或配置 revision 变化时会失效并重连；切换站点会
关闭旧站点 manager，缓存 key 同时包含数据根和 `site_id`，不跨站点复用。

## Verification gaps

本审计未连接现场设备，也未将真实网络、Jump 主机、Target SSH、GUI 安装或
人工验收标记为 PASS。需要在受控现场网络执行：Jump 登录、direct-tcpip、目标
认证/命令、轨旁 AP/光衰/LLDP、AC、设备 SSH、错误密码、站点切换和重启持久化。
