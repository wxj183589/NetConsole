# SSH Relay Unification Report

日期：2026-09-07
状态：源码统一和自动化验证完成；现场设备、真实网络和安装后 GUI 仍待现场执行。

## ROOT CAUSE

1. 车站交换机与 AC 虽然都使用 Netmiko，但原目标连接的 Host Key 策略会
   把首次 Target key 拒绝包装成通用连接失败；错误没有保留 Target Host Key
   和 Target Auth 阶段。
2. FIT-AP Optical 的原实现构造 `hp_comware_telnet` 后直接调用 Netmiko，
   目标地址从 Windows 发起连接；隔离网络下因此表现为约 5 秒直连超时。
3. 不同调用方缺少可审计的站点级统一出口；本次将内部 CLI 连接全部收口到
   `netmiko_connection.ConnectHandler` → `DeviceSSHConnectionFactory`。

## Unified design

| Site relay state | Device CLI route |
| --- | --- |
| OFF / old site without relay fields | `DeviceSSHConnectionFactory` → Direct Netmiko |
| ON | `DeviceSSHConnectionFactory` → site Jump Transport → Paramiko `direct-tcpip` → Target Netmiko session |
| Jump Host itself | First hop Direct SSH only; it is the sole transport exception |

Jump and Target credentials are independent. The Relay path does not use
external `ssh.exe` and does not create a per-device localhost port mapping.
Legacy FIT-AP Optical Telnet is adapted on the same Paramiko Channel without
changing its commands or parser.

## Consumer result

AC, Device Management, Trackside Switch, FIT-AP, FIT-AP Optical, Optical, LLDP
and Backend Rail Transit SSH consumers now share the facade/factory. Relay OFF
keeps Direct and Relay ON selects Jump from the current site configuration.
Ping/ICMP, fping, SNMP/UDP, syslog/UDP and other non-SSH protocols remain outside
the Relay by design.

SFTP/file transfer and the separately packaged Windows MR Agent are explicit
boundaries requiring separate transport contracts; the external SecureCRT,
Xshell and PuTTY process is also not controlled by the Backend factory. Their
routes are not reported as verified Jump support.

## Host Key and Target Auth

Jump Host uses the managed strict Host Key policy. Target SSH uses role-separated
managed TOFU: first-use key records its fingerprint, the same key passes, and a
changed key returns `TARGET_HOSTKEY_CHANGED`. Target authentication failures
return `TARGET_AUTH_FAILED`; they are not reported as Jump channel failures.
The logs retain stage, target, Jump, username, authentication method,
credential-loaded state, exception class and duration, without passwords.

## Concurrency and lifecycle

The implementation uses one healthy Jump Transport per Python worker/site/config
revision and multiple independent target Channels. Target disconnect cannot
close the shared Jump Transport. Relay config revision changes and site changes
invalidate the old manager. Existing business concurrency defaults and AP
business rules, commands, parsers, identity rules and the `-13.90 dBm` threshold
were not changed. Field concurrency 1/2/4/8/16 is still `NOT VERIFIED`.

## Validation order

The required field order is: AC control, reported Switch with wrong credentials,
known-good Switch, one FIT-AP Optical, 1–2 station sample, concurrency 2/4/8/16,
then complete Trackside AP flow, restart persistence, site switching and package
smoke. Current environment had no field credentials or target network, so every
real-device item is `NOT VERIFIED`; the supplied screenshots are pre-fix evidence.

## Automated regression

- Targeted Relay/Host Key/Netmiko/File Transfer/AC/Trackside tests: PASS after
  the final direct-Channel change.
- Full repository pytest: `4684 passed, 2 skipped, 4 failed`. The four failures
  are existing architecture-guard/version-policy baseline findings and are not
  caused by the SSH Relay changes; they must remain visible to release review.
- Source audit: no business Relay bypass parameters and no Relay local listener.

## Production package

The existing Windows Production pipeline completed from source commit
`bc0d20544e8dce004703adb7b6c01abec71a01fe`. The artifact manifest and an
independent SHA-256 recheck agree:

```text
PRODUCT_VERSION=1.5.5
BUILD_ID=netconsole-1.5.5-bc0d2054-20260907T071601Z-full
INSTALLER_FILENAME=NetConsole-Full-1.5.5.0-bc0d2054-x64-setup.exe
INSTALLER_PATH=D:\study\NetConsole-Workspace\release\v1.5.5\build-0-bc0d2054\NetConsole-Full-1.5.5.0-bc0d2054-x64-setup.exe
INSTALLER_SIZE_BYTES=157037904
INSTALLER_SHA256=5570af852749c47fb1028fae60937cb7d6cf8b827473437b183371cd78c898cf
AUTOMATED_PACKAGE_GATE=PASS
REAL_WINDOWS_INSTALL_SMOKE=NOT VERIFIED
REAL_DEVICE_SMOKE=NOT VERIFIED
```

The final installer is a deliverable for the user’s现场 validation, not proof
of AC/Switch/FIT-AP/Optical/LLDP real-network acceptance. The manifest also
records `published=false`, `packaged_dirty=false`, `package_smoke=PASS`, and
`edition_payload_verified=true`.
