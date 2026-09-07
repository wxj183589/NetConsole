# SSH Relay Final Audit

日期：2026-09-07
审计范围：`src/netconsole`、`apps/agent`、Renderer/Electron 调用边界、测试与既有 SSH 隧道模块。

## Manual acceptance status

依据用户提供的现场验收结论：

```text
MANUAL_ACCEPTANCE=PASS
WINDOWS_INSTALL=PASS
SITE_SSH_RELAY=PASS
AC_OVER_RELAY=PASS
SWITCH_OVER_RELAY=PASS
TRACKSIDE_AP_OVER_RELAY=PASS
TRACKSIDE_OPTICAL_COLLECTION=PASS
MANUAL_FIELD_VALIDATION=PASS
```

FIT-AP 独立细分、LLDP、设备管理 SSH、局点切换、重启持久化、外部终端和
独立 Agent 未在本次附件中单独确认，保持 `NOT VERIFIED`。

## Final conclusion

Backend 内部设备 CLI 的唯一公共出口是
`src/netconsole/services/netmiko_connection.py::ConnectHandler`，其设备会话由
`DeviceSSHConnectionFactory` 统一选择 Direct 或 Jump。Relay OFF 保持原有
Direct Netmiko；Relay ON 强制使用当前局点 Jump Host 的 Paramiko Transport 和
每目标独立 `direct-tcpip` Channel。

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
| External SSH terminal | `external_terminal.py` | third-party process direct command | third-party process is outside Backend factory | external tool cannot be forced by Backend | Integration NOT VERIFIED; no PASS claim |

## Direct connection audit findings

- `site_ssh_relay.py` creates the first-hop Paramiko `SSHClient` to the Jump
  Host. This is the only Direct exception in the site Relay implementation.
- `site_ssh_relay.py` uses the Jump `Transport.open_channel("direct-tcpip", ...)`
  for every target. The target SSH layer uses the returned Channel as `sock`.
- All in-process Backend Netmiko device callers found by repository search enter
  the shared facade. The rail diagnostic compatibility function delegates to
  that facade rather than importing Netmiko directly.
- `file_transfer_service.py` SFTP uses its existing separate file-transfer
  protocol boundary; `ssh_tunnel.py` remains the existing legacy per-device
  tunnel feature. Neither is advertised as site Relay device CLI support.
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

Site SSH Relay Jump Host keys use the managed `AUTO_REPLACE` policy: first use
records the fingerprint, the same key is verified, and a changed key is
atomically replaced for that host:port with an audit event. Target SSH keys
retain managed role-separated TOFU: first use records the fingerprint, same key
passes, and a changed key returns `TARGET_HOSTKEY_CHANGED`. A Jump key and a
Target key are never treated as the same identity. The separate SFTP/file
consumer keeps its existing strict confirmation boundary.

## Lifecycle and concurrency

One Python worker reuses at most one healthy Jump Transport per site/config
revision; each target gets an independent Channel and target session. Closing a
target session does not close the shared Jump Transport. Config revision changes
or site switching close the old manager; site identity and data-root boundaries
prevent cross-site reuse. The existing collector concurrency defaults were not
changed. Field concurrency 1/2/4/8/16 remains `NOT VERIFIED`.

## Required error stages

The implementation distinguishes Jump TCP connect/auth/Host Key/channel and
Target TCP/banner/handshake/Host Key/auth/session/command. The common classifier
recognizes:

`JUMP_CONNECT_FAILED`, `JUMP_AUTH_FAILED`, `JUMP_HOSTKEY_FAILED`,
`JUMP_CHANNEL_FAILED`, `TARGET_TCP_FAILED`, `TARGET_SSH_BANNER_FAILED`,
`TARGET_SSH_HANDSHAKE_FAILED`, `TARGET_HOSTKEY_FAILED`,
`TARGET_HOSTKEY_CHANGED`, `TARGET_AUTH_FAILED`, `TARGET_SESSION_FAILED`,
`TARGET_COMMAND_FAILED`, `CONNECT_TIMEOUT`.

## Evidence status

Automated source/tests: PASS for the changed Relay, Host Key, Netmiko, file
transfer and Trackside paths. Full repository regression: 4684 passed, 2
skipped, 4 unrelated baseline failures in architecture guards/version policy;
see final task report. The user-reported core field scope and Windows install
are PASS; FIT-AP/LLDP/device-management subitems, external terminal Jump and
standalone Agent remain `NOT VERIFIED` where not separately confirmed.
