# SSH Relay Field Fix Report

日期：2026-09-07
结论状态：源码修复和自动化定向验证完成；真实设备、真实轨旁 AP、小批量、并发梯度和安装包 GUI 验收 `NOT VERIFIED`。

## ROOT_CAUSE

### 车站交换机

`CODE_INSPECTION` confirms the pre-fix Target SSH path supplied the Jump
`direct-tcpip` channel to Netmiko while forcing `ssh_strict=True`. Netmiko then
installed Paramiko `RejectPolicy` for the Target connection. A Target whose key
was not yet in the managed `known_hosts` file was rejected and wrapped as a
generic Netmiko connection failure. This explains the fast failure pattern and
the difference from a TCP timeout. The user-provided Linux transcript, which
reached the Target Host Key confirmation and then the password prompt, is
consistent with this diagnosis, but the repaired build must still be rerun in
the field to identify the first failing stage for the actual device.

The transcript also shows a separate possible `TARGET_AUTH_FAILED`: the
manually entered password was rejected. The software must report that result
as target authentication failure when the stored Target credential is wrong;
it must not bypass or rewrite the device credential.

### FIT-AP Optical

`CODE_INSPECTION` confirms the pre-fix FIT-AP Optical collector constructed a
`hp_comware_telnet` target and called Netmiko directly. It therefore attempted
the AP address from Windows and could produce the observed approximately five
second timeout even when the Jump could reach the target network.

## FIXES

- Target SSH now uses the managed host-key file with controlled TOFU: first
  use persists the Target key, an identical later key passes, and a changed
  key fails with `TARGET_HOSTKEY_CHANGED`.
- Jump and Target identities remain separate. Jump remains strict and is never
  auto-added by the Target policy.
- Target connection failures preserve safe stage, exception class, target,
  Jump, username, authentication method, credential-loaded flag and duration.
  Passwords and private keys are never placed in these diagnostics.
- Relay error classification now distinguishes Jump connection/auth/Host Key/
  channel, Target TCP/banner/handshake/Host Key/auth/session/command and
  timeout outcomes.
- FIT-AP Optical legacy Telnet now uses the same `DeviceSSHConnectionFactory`.
  Its Netmiko Telnet driver is bound directly to one independent Paramiko
  `direct-tcpip` Channel backed by the per-site Jump Transport. No localhost
  listener or per-device local port mapping is created. Relay OFF remains
  direct.
- Existing H3C `ssh-rsa` compatibility fallback is retained and remains
  scoped to the existing H3C SSH negotiation condition. No global legacy
  algorithm enablement or keyboard-interactive guess was added without field
  evidence.
- AP identity, station/segment rules, FIT-AP business rules, commands,
  parsers, the `-13.90 dBm` threshold and default concurrency were not changed.

## Required error codes

`JUMP_CONNECT_FAILED`, `JUMP_AUTH_FAILED`, `JUMP_HOSTKEY_FAILED`,
`JUMP_CHANNEL_FAILED`, `TARGET_TCP_FAILED`, `TARGET_SSH_BANNER_FAILED`,
`TARGET_SSH_HANDSHAKE_FAILED`, `TARGET_HOSTKEY_FAILED`,
`TARGET_HOSTKEY_CHANGED`, `TARGET_AUTH_FAILED`, `TARGET_SESSION_FAILED`,
`TARGET_COMMAND_FAILED`, and `CONNECT_TIMEOUT` are now recognized by the
common connection classification layer. The legacy `TARGET_CONNECT_FAILED`
code remains for compatibility with older callers.

## REAL_DEVICE_VALIDATION

`NOT VERIFIED` in this environment. No field credential was read, changed or
logged. Required order is: Jump control, one AC control, one switch with
known-good credentials, one switch with the reported credential, then one
FIT-AP. The first failing stage must be recorded, not inferred from the final
`CollectionError` wrapper.

## TRACKSIDE_VALIDATION

`NOT VERIFIED`. The repaired code path is unified for Trackside Switch and
FIT-AP Optical, but the Jump must independently reach every FIT-AP target
subnet. If it cannot, report `JUMP_TO_TARGET_NETWORK_UNREACHABLE` rather than
calling that a software fix. Then validate 1–2 stations for switch collection,
FIT-AP collection, LLDP, AP state and optical values before any full run.

## CONCURRENCY_RESULT

`NOT VERIFIED`. No concurrency default was changed. The required 1/2/4/8/16
gradient, success/failure/timeout, average, P95, Jump reconnect count and
channel-open failure count still require a successful single-device field
baseline first.

## REGRESSION_RESULT

Automated targeted result after the final direct-Channel correction: `388
passed, 3 warnings` across Relay, File Transfer, Netmiko, File Management,
Device Management, AC Management and Trackside AP suites. Renderer targeted
validation passed; the Windows Production package also passed its Web
`180 files / 1290 tests`, Electron `37 files / 298 tests`, build, NSIS,
package-smoke, identity and SHA-256 gates. This does not cover real device,
real-data, GUI installation or production-network acceptance. Direct mode,
site isolation, persistence and secret-log checks are covered by code/tests;
field confirmation remains `NOT VERIFIED`.

## PACKAGE_RESULT

`PASS` for automated package generation and package smoke from source commit
`bc0d20544e8dce004703adb7b6c01abec71a01fe`.

- Artifact: `D:\study\NetConsole-Workspace\release\v1.5.5\build-0-bc0d2054\NetConsole-Full-1.5.5.0-bc0d2054-x64-setup.exe`
- Size: `157037904` bytes
- SHA-256: `5570af852749c47fb1028fae60937cb7d6cf8b827473437b183371cd78c898cf`
- Manifest: `published=false`, `packaged_dirty=false`,
  `package_smoke=PASS`, `edition_payload_verified=true`

Real Windows install/upgrade/uninstall smoke remains `NOT VERIFIED`; an
automated package pass is not an installer or field-device acceptance result.

## Boundary

The site Relay is an SSH/TCP transport aid for the supported in-process
consumers. It does not proxy Ping/ICMP, SNMP/UDP, Syslog/UDP, fping or external
terminal processes. External SecureCRT/Xshell/PuTTY sessions must use their
own native Jump/Proxy configuration; Backend does not claim that route as
verified.
