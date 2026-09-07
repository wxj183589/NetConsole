# SSH Relay Consumer Audit

日期：2026-09-07
证据边界：`CODE_INSPECTION`、`AUTOMATED_TEST`；现场设备、安装包 GUI 和生产数据验收为 `NOT VERIFIED`。

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
| AC CLI / AC resource | Direct Netmiko facade → factory Direct | facade → `DeviceSSHConnectionFactory` → Jump `direct-tcpip` → Target SSH | AC Device record / `ConnectionManager` | Jump managed strict key；Target managed TOFU | Code/test PASS; field NOT VERIFIED |
| Device Management SSH test/detail | Same facade → factory Direct | Same facade → factory Jump | Device Management Device record | Same Jump/Target separation | Code/test PASS; field NOT VERIFIED |
| Trackside AP Switch | Same facade → factory Direct | Same facade → factory Jump | Stable Device UUID reread; device SSH credential | Target key and stage diagnostics | Code/test PASS; field NOT VERIFIED |
| FIT-AP / AC CLI branch | Same facade → factory Direct | Same facade → factory Jump | Selected AC/AP device record | Target SSH policy | Code/test PASS; field NOT VERIFIED |
| FIT-AP Optical | Netmiko `hp_comware_telnet` Direct | Same factory → Jump Channel → Netmiko Telnet driver | FIT-AP Telnet credential; never Jump credential | Telnet has no SSH target key; Jump key remains strict | Code/test PASS; field NOT VERIFIED |
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

No real target or Jump endpoint was contacted in the automated run. The provided
field screenshots remain pre-fix failure evidence. Field acceptance must execute
AC, one known-good Switch, the reported wrong-credential Switch, one FIT-AP
Optical, LLDP, Optical, a 1–2 station sample, concurrency 1/2/4/8/16, site
switching, restart persistence and installed-package checks in that order.
