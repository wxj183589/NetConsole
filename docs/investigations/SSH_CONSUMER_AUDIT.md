# NetConsole SSH Consumer Audit

日期：2026-09-07
范围：共享 SSH 基础设施、局点配置、轨旁 AP、AC、设备管理、轨道交通采集及非 SSH 传输边界。

## 结论

NetConsole 的 Backend CLI 主栈是 Netmiko 4.7.0 + Paramiko 4.0.0。现有
`netmiko_connection.ConnectHandler` 是兼容性、站点路由和诊断入口；本次修复
确认车站交换机与 AC 共用该入口，FIT-AP Optical 的 legacy Telnet 连接也在
Relay 开启时经同一站点 Jump TCP 通道转发。Relay 配置使用现有局点元数据和
DPAPI 密文凭据库。

Paramiko `direct-tcpip` 可复用：Netmiko 4.7 的 `BaseConnection` 接收 `sock`
并传给 Paramiko `SSHClient.connect`，因此 SSH 目标设备使用 Jump Host 返回的
Channel 建立原有 Netmiko Shell。实现采用每个 Python Worker 进程、每个 site
一个健康 Transport，每个目标独立 Channel。legacy Telnet 目标也在同一
`DeviceSSHConnectionFactory` 中将 Netmiko Telnet driver 绑定到 Paramiko
Channel；Relay 路径不创建 localhost listener 或 per-device 本地端口映射。

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
| FIT-AP Optical | H3C FIT-AP optical 内部的 `hp_comware_telnet` → `DeviceSSHConnectionFactory` | 目标 AP Telnet 命令 | Relay 开启时将 Netmiko Telnet driver 绑定到 Jump `direct-tcpip` Channel；Relay 关闭时 Direct |
| SFTP/文件传输 | `file_transfer_service.py`、旧 `ssh_tunnel.py` | Paramiko SFTP/本地临时转发 | 第一版不走站点 Relay；旧隧道显式不叠加 Relay |
| 外部终端 | `external_terminal.py` → SecureCRT/PuTTY/WinSCP | 外部进程，不创建 Backend SSH session | 外部进程不受 Backend factory 控制；Relay ON 不宣称已通过内部 Jump，需外部工具原生 Proxy/Jump 配置后现场验证 |
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
- `netmiko_connection.ConnectHandler` 是唯一业务连接 facade；Relay OFF 也进入
  `DeviceSSHConnectionFactory` 的 Direct 分支，Relay ON 进入同一 factory 的
  Jump 分支。业务参数中不再提供 `use_relay`、`force_direct`、`skip_jump` 或
  `disable_relay` 之类路由开关。

## Host key and failure boundaries

Jump Host 与 Target Device 使用独立 SSH 身份。Jump 继续使用 managed
`known_hosts` 的严格校验；Target SSH 使用同一 managed 文件做受控 TOFU：首次
连接登记完整 key/fingerprint，后续同 key 通过，已登记 key 变化时由
`BadHostKeyException`/managed trust gate 拒绝。Target Host Key 不会因为 Jump
Host 已信任而被视为已信任。

公共错误码保留以下边界：

- `JUMP_CONNECT_FAILED`
- `JUMP_AUTH_FAILED`
- `JUMP_HOSTKEY_FAILED`
- `JUMP_CHANNEL_FAILED`
- `TARGET_CONNECT_FAILED`
- `TARGET_TCP_FAILED`
- `TARGET_SSH_BANNER_FAILED`
- `TARGET_SSH_HANDSHAKE_FAILED`
- `TARGET_HOSTKEY_FAILED`
- `TARGET_HOSTKEY_CHANGED`
- `TARGET_AUTH_FAILED`
- `TARGET_SESSION_FAILED`
- `TARGET_COMMAND_FAILED`
- `CONNECT_TIMEOUT`

Ping/ICMP、SNMP UDP/161、Syslog UDP、fping、VPN、SOCKS、ProxyChain 和多级
Jump 不在本能力范围内。

## Parallelism and lifecycle

轨旁 AP 同时运行 AC/FIT-AP 分支与交换机线程池。一个 Python Worker、一个 site
复用一个健康 Jump Transport，并为每个目标创建独立 direct-tcpip Channel。Transport
的创建、健康检查、失效和 Channel 创建受站点 manager 锁保护；Target Session 关闭不会关闭 Jump
Transport。Transport inactive 或配置 revision 变化时会失效并重连；切换站点会
关闭旧站点 manager，缓存 key 同时包含数据根和 `site_id`，不跨站点复用。

## Verification gaps

自动化审计和定向测试未连接现场设备，也未将真实网络、Jump 主机、Target SSH、
GUI 安装或人工验收标记为 PASS。用户提供的现场截图属于现场失败证据，不能替代
修复后重新执行。需要在受控现场网络执行：Jump 登录、direct-tcpip、目标认证/
命令、轨旁 AP/光衰/LLDP、AC、设备 SSH、错误密码、站点切换和重启持久化。
