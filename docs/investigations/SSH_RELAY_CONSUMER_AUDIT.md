# SSH Relay Consumer Audit

日期：2026-09-07
证据边界：`CODE_INSPECTION`、`AUTOMATED_TEST` 及用户提供的核心现场人工验收结论；外部终端、独立 Agent 和未单独确认的细分项目为 `NOT VERIFIED`。

## Manual acceptance status

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

FIT-AP 独立细分、LLDP、设备管理 SSH、局点切换和重启持久化未在附件中
单独确认；外部 SecureCRT/Xshell/PuTTY 与独立 Windows Agent 继续保持
`NOT VERIFIED`。

## Current routing contract

`netmiko_connection.ConnectHandler` 是设备 CLI 的公共 facade，并将 Direct/Jump
选择收口到 `DeviceSSHConnectionFactory`：当前局点 Relay OFF 使用原有 Netmiko
Direct；Relay ON 使用同一 Jump `Transport` 为每个目标打开独立 Paramiko
`direct-tcpip` Channel。业务层没有 `use_relay`、`force_direct`、`skip_jump` 或
`disable_relay` 路由参数。

Relay ON 的 SSH 路径为：

`Windows Backend → Jump Host SSH → direct-tcpip → Target SSH → Netmiko session`

legacy FIT-AP Optical Telnet 仍保留原有 Telnet 命令/解析，但由同一 factory 将
Netmiko Telnet driver 直接绑定到 Jump Channel；Relay 路径没有 `127.0.0.1:xxxxx`
监听器或每设备本地端口映射。

## Consumer matrix

| Consumer | Relay OFF | Relay ON | Credential source | Host Key / protocol | Audit result |
| --- | --- | --- | --- | --- | --- |
| AC CLI / AC resource | Direct Netmiko facade → factory Direct | facade → `DeviceSSHConnectionFactory` → Jump `direct-tcpip` → Target SSH | AC Device record / `ConnectionManager` | Jump managed strict key；Target managed TOFU | Code/test/manual PASS |
| Device Management SSH test/detail | Same facade → factory Direct | Same facade → factory Jump | Device Management Device record | Same Jump/Target separation | Code/test PASS; field NOT VERIFIED |
| Trackside AP Switch | Same facade → factory Direct | Same facade → factory Jump | Stable Device UUID reread; device SSH credential | Target key and stage diagnostics | Code/test/manual PASS |
| FIT-AP / AC CLI branch | Same facade → factory Direct | Same facade → factory Jump | Selected AC/AP device record | Target SSH policy | Code/test PASS; field NOT VERIFIED |
| FIT-AP Optical | Netmiko `hp_comware_telnet` Direct | Same factory → Jump Channel → Netmiko Telnet driver | FIT-AP Telnet credential; never Jump credential | Telnet has no SSH target key; Jump key remains strict | Code/test; trackside optical manual PASS |
| Optical CLI | Same facade → factory Direct | Same facade → factory Jump | Selected device record | Target SSH policy | Code path confirmed; field NOT VERIFIED |
| LLDP CLI | Same facade → factory Direct | Same facade → factory Jump | Selected device record | Target SSH policy | Code path confirmed; field NOT VERIFIED |
| Rail Transit / Online MR / car network SSH | Backend facade from `NetmikoShellConnection` or rail wrapper | Same facade → factory Jump when site context is available | Device / AC record | Target SSH policy | Code path confirmed; field NOT VERIFIED |
| External SSH terminal | External SecureCRT/Xshell/PuTTY process | Not controlled by Backend factory; no direct PASS claim | Device record passed to external tool | External tool must be configured with its own native Jump/Proxy | Explicit integration gap; NOT VERIFIED |

## Full-repository connection audit

| Finding | Location / role | Decision |
| --- | --- | --- |
| `paramiko.SSHClient` | `site_ssh_relay.py` Jump connection and managed target-key inspection | Allowed infrastructure boundary; target shell still enters through the factory |
| Netmiko `ConnectHandler` | AC, device management, Trackside, Optical, LLDP, rail collectors | All internal device CLI calls resolve through `netmiko_connection.ConnectHandler` |
| `paramiko.SSHClient` | `file_transfer_service.py` SFTP subsystem | Explicit file-transfer protocol boundary; not a CLI consumer; retained existing SFTP error/host-key contract |
| `paramiko.SSHClient` / local forward | `ssh_tunnel.py` legacy per-device tunnel | Explicit legacy tunnel feature; not used by site Relay implementation; no Relay code creates a local listener |
| standalone Netmiko | `apps/agent/mr_collector_py/collector_cli.py` | Separate packaged Agent process without Backend site-config authority; requires separate Agent contract before claiming site Relay support |
| subprocess external tools | `external_terminal.py` / SecureCRT session export | Not an in-process SSH session; external Jump/Proxy configuration is outside Backend control |
| Ping / fping / SNMP / syslog | network tools and UDP/ICMP services | Not SSH; intentionally not routed through Jump |
| `AsyncSSH`, `ssh_service`, `terminal_service` | Repository search | No active implementation found |

The only Direct exception in the site Relay implementation is the first-hop Jump
Host connection itself. The legacy `ssh_tunnel.py` and SFTP rows are protocol or
feature boundaries, not a site Relay bypass flag; their behavior is kept explicit
so the audit does not misrepresent them as unified device CLI consumers.

## Stage and error audit

The Relay path emits safe stages for Jump TCP connect, Jump SSH handshake, Jump
authentication, `direct-tcpip` open, Target TCP readiness, Target SSH banner,
Target SSH handshake, Target Host Key, Target authentication, Target session and
Target command. It preserves target/jump endpoint, username, authentication
method, credential-loaded status, exception class and duration; no password or
private key is logged.

The common classifier recognizes `JUMP_CONNECT_FAILED`, `JUMP_AUTH_FAILED`,
`JUMP_HOSTKEY_FAILED`, `JUMP_CHANNEL_FAILED`, `TARGET_TCP_FAILED`,
`TARGET_SSH_BANNER_FAILED`, `TARGET_SSH_HANDSHAKE_FAILED`,
`TARGET_HOSTKEY_FAILED`, `TARGET_HOSTKEY_CHANGED`, `TARGET_AUTH_FAILED`,
`TARGET_SESSION_FAILED`, `TARGET_COMMAND_FAILED` and `CONNECT_TIMEOUT`.

## Verification gap

The supplied field acceptance conclusion confirms the core Relay, Windows
install, AC, Switch, Trackside AP and optical scope. The provided screenshots
remain pre-fix failure evidence. FIT-AP/LLDP/device-management subitems,
concurrency 1/2/4/8/16, site switching, restart persistence, external terminal
and standalone Agent require separate evidence before being marked PASS.
