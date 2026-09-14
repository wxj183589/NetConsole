# SSH Relay Final Audit

日期：2026-09-14
审计范围：`src/netconsole`、`apps/agent`、Renderer/Electron 调用边界、测试与既有 SSH 隧道模块。

> 历史审计说明：本文中的 Host Key “严格校验/变化失败”属于旧设计快照，已被
> v1.5.8 现场运维自动恢复改造取代。当前规则见
> `docs/device-files/HOST_KEY_TRUST.md`，不得据此恢复确认或阻断状态机。

## Manual acceptance status

本轮代码审计与自动化验证结论：

```text
SITE_RELAY_AUTO_START=PASS
SITE_SWITCH_AUTO_REBIND=PASS
CONFIG_CHANGE_RECONNECT=PASS
JUMP_TRANSPORT_REUSE=PASS
JUMP_KEEPALIVE=PASS
STALE_TRANSPORT_AUTO_RECOVERY=PASS
FILE_TRANSFER_SITE_RELAY=PASS
SFTP_RECONNECT_SITE_RELAY=PASS
WINSCP_SITE_RELAY=NOT_COMPLETED
REAL_DEVICE_SSH_RELAY=PENDING
```

本轮未提供可用的现场 Jump Host，真实设备 Relay、GUI 安装和跨机器验收保持
`PENDING`；SecureCRT/Xshell/PuTTY、WinSCP Site Relay 和独立 Agent 不在本轮
Backend Relay 实现范围内。

## Final conclusion

Backend 内部设备 CLI 的唯一公共出口是
`src/netconsole/services/netmiko_connection.py::ConnectHandler`，其设备会话由
`DeviceSSHConnectionFactory` 统一选择 Direct 或 Jump。Relay OFF 保持原有
Direct Netmiko；Relay ON 强制使用当前局点 Jump Host 的 Paramiko Transport 和
每目标独立 `direct-tcpip` Channel。文件列表、SFTP 和下载也复用同一
`SiteJumpSessionManager`；Relay OFF 仍保留原有直连、备份和 legacy per-device
tunnel 回退。

Relay 实现没有外部 `ssh.exe`，也没有为每台目标创建
`127.0.0.1:xxxxx` 本地监听/端口映射。FIT-AP Optical 的 legacy Telnet 由同一
factory 把 Netmiko Telnet driver 绑定到 direct-tcpip Channel；这不是 SSH
Target Host Key 流程，但仍遵守 Jump/Target 凭据隔离。

## Consumer audit

| Consumer | Source entry | Relay OFF | Relay ON | Direct bypass | Result |
| --- | --- | --- | --- | --- | --- |
| AC / AC resource | `h3c_ac_collect_service.py` | shared facade → factory Direct | shared facade → factory Jump | none in Backend CLI | Code PASS; manual PASS |
| Device Management | `netmiko_connection.test_device_connection` and management jobs | same factory Direct | same factory Jump | none in Backend CLI | Code PASS; field NOT VERIFIED |
| Trackside Switch | `trackside_optical_collection.py::_collect_one_target` | same factory Direct | same factory Jump | none in Backend CLI | Code PASS; manual PASS |
| FIT-AP | Trackside AC/AP CLI branch | same factory Direct | same factory Jump | none in Backend CLI | Code PASS; field NOT VERIFIED |
| FIT-AP Optical | `hp_comware_telnet` via shared facade | Direct Telnet | same factory, Jump Channel, Telnet driver | none in Relay path | Code PASS; trackside optical manual PASS |
| Optical | `h3c_optical_refresh_service.py` and adapters | same factory Direct | same factory Jump | none in Backend CLI | Code PASS; field NOT VERIFIED |
| LLDP | Trackside/AC/device CLI commands | same factory Direct | same factory Jump | none in Backend CLI | Code PASS; field NOT VERIFIED |
| Rail Transit SSH | rail wrappers and `NetmikoShellConnection` | same factory Direct | same factory Jump when site context is present | none in Backend CLI | Code PASS; field NOT VERIFIED |
| FileTransfer / SFTP / download | `file_transfer_service.py` | direct/backup/legacy tunnel | same Site Jump Transport + target channel | none in Backend file path | Code PASS; real device PENDING |
| WinSCP | `external_terminal.py` | direct or legacy temporary tunnel | not implemented in this round | third-party process cannot reuse Backend manager safely | `WINSCP_SITE_RELAY=NOT_COMPLETED` |
| External SSH terminal | `external_terminal.py` | third-party process direct command | out of scope | external tool cannot be forced by Backend | `EXTERNAL_TERMINAL_SITE_RELAY=OUT_OF_SCOPE` |

## Direct connection audit findings

- `site_ssh_relay.py` creates the first-hop Paramiko `SSHClient` to the Jump
  Host. This is the only Direct exception in the site Relay implementation.
- `site_ssh_relay.py` uses the Jump `Transport.open_channel("direct-tcpip", ...)`
  for every target. The target SSH layer uses the returned Channel as `sock`.
- All in-process Backend Netmiko device callers found by repository search enter
  the shared facade. The rail diagnostic compatibility function delegates to
  that facade rather than importing Netmiko directly.
- `file_transfer_service.py` now routes Relay ON file listing, SFTP and download
  through `SiteSSHRelayService.open_target_channel`; `ssh_tunnel.py` remains the
  existing Relay OFF legacy per-device tunnel feature only.
- `apps/agent/mr_collector_py/collector_cli.py` is a separately packaged
  standalone Netmiko process without Backend site-config/DPAPI authority. It
  needs an Agent transport contract before it can be claimed as site Relay
  support.
- Repository search found no active `AsyncSSH`, `ssh_service`, or
  `terminal_service` implementation.

## Bypass and protocol checks

The source audit found no business parameters named `use_relay`, `force_direct`,
`skip_jump`, or `disable_relay`, and no `_netconsole_*relay` bypass parameter.
Relay selection is owned by the central facade/factory. Ping, ICMP, fping, SNMP
UDP/161, syslog UDP and other non-SSH protocols intentionally stay outside this
transport and may independently fail without proving SSH unreachable.

## Credentials and Host Key

Jump credentials come only from the site-scoped DPAPI credential store and are
used only for the first hop. Target credentials come from the selected Device
record and are used only for the target session. Stage logs include username,
authentication method, credential-loaded state and exception class, never a
password or private key.

Site SSH Relay Jump Host and Target SSH keys use the managed `AUTO_REPLACE`
policy: `UNKNOWN` automatically adds the current `host:port`, `MATCH` continues,
and `MISMATCH` atomically replaces only that exact `host:port` before continuing,
with an audit event. Relay target keys use the original target identity, never
`127.0.0.1:random`; Jump and Target keys are never conflated. The same rule is
used by Backend CLI, file listing, SFTP and download.

## Lifecycle and concurrency

One Python worker reuses at most one healthy Jump Transport per site/config
revision; each target gets an independent Channel and target session. The Jump
Transport uses a 25-second keepalive. If opening a channel proves that the Jump
Transport itself is stale, the manager closes/reconnects it and retries that
channel once; target ACL, refusal, timeout and unreachable errors do not enter
this recovery loop. Closing a target session does not close the shared Jump
Transport. Config revision changes or site switching close the old manager;
site identity and data-root boundaries prevent cross-site reuse.

## Required error stages

The implementation distinguishes Jump TCP connect/auth/Host Key/channel and
Target TCP/banner/handshake/Host Key/auth/session/command. The common classifier
recognizes:

`JUMP_CONNECT_FAILED`, `JUMP_AUTH_FAILED`, `JUMP_HOSTKEY_FAILED`,
`JUMP_CHANNEL_FAILED`, `TARGET_TCP_FAILED`, `TARGET_SSH_BANNER_FAILED`,
`TARGET_SSH_HANDSHAKE_FAILED`, `TARGET_HOSTKEY_FAILED`,
`TARGET_AUTH_FAILED`, `TARGET_SESSION_FAILED`, `TARGET_COMMAND_FAILED`,
`CONNECT_TIMEOUT`. `TARGET_HOSTKEY_CHANGED` remains a legacy compatibility
label only; the current managed policy handles `UNKNOWN` with auto-add,
`MATCH` by continuing, and `MISMATCH` with exact-identity auto-replace before
continuing.

## Evidence status

Automated targeted source/tests: PASS (`199 passed`) for the Relay, Host Key,
The additional `tests/test_device_sftp_operation.py` check also passed (`7 passed`).
Netmiko, file-transfer, site-storage and Electron-runtime contract paths,
including a real Paramiko Jump → direct-tcpip → target SFTP topology. The full
local Gate was also executed: Renderer/Electron/architecture/main smoke passed,
while Python retained 3 pre-existing baseline failures and Ruff retained 1
unused-exception failure in untouched `file_management_service.py`; these are
not attributed to this Relay change. GUI/device acceptance was not run in this
no-package round. WinSCP Site Relay is `NOT_COMPLETED`; external terminal and
Agent are `OUT_OF_SCOPE`.
