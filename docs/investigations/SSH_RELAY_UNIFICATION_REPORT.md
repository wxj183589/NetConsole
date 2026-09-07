# SSH Relay Unification Report

日期：2026-09-07
状态：源码统一、自动化验证和核心现场人工验收完成；外部终端、独立 Agent 及未纳入本次范围的细分项目仍待单独验证。

## ROOT CAUSE

1. 车站交换机与 AC 虽然都使用 Netmiko，但原目标连接的 Host Key 策略会
   把首次 Target key 拒绝包装成通用连接失败；错误没有保留 Target Host Key
   和 Target Auth 阶段。
2. FIT-AP Optical 的原实现构造 `hp_comware_telnet` 后直接调用 Netmiko，
   目标地址从 Windows 发起连接；隔离网络下因此表现为约 5 秒直连超时。
3. 不同调用方缺少可审计的站点级统一出口；本次将内部 CLI 连接全部收口到
   `netmiko_connection.ConnectHandler` → `DeviceSSHConnectionFactory`。

## MANUAL_ACCEPTANCE

以下状态依据用户提供的 2026-09-07 现场人工验收结论记录，不扩写具体
IP、数量或耗时：

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

FIT-AP 细分独立项、LLDP 独立项、设备管理 SSH、局点切换和软件重启后
持久化没有在本次附件中单独确认，继续保持 `NOT VERIFIED`。外部终端和
独立 Windows Agent 同样保持 `NOT VERIFIED`。

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

核心现场人工验收已按附件结论确认 PASS，覆盖 Windows 安装运行、局点
Relay、AC、车站交换机、轨旁 AP 和光衰采集。并发 1/2/4/8/16、FIT-AP
细分、LLDP 独立项、设备管理 SSH、局点切换、重启持久化、外部终端和
独立 Agent 未在附件中单独确认，仍需按现场条件补验；此前截图仅作为
修复前失败证据。

## Automated regression

- Targeted Relay/Host Key/Netmiko/File Transfer/AC/Trackside tests: PASS after
  the final direct-Channel change.
- Full repository pytest: `4684 passed, 2 skipped, 4 failed`. The four failures
  are existing architecture-guard/version-policy baseline findings and are not
  caused by the SSH Relay changes; they must remain visible to release review.
- Source audit: no business Relay bypass parameters and no Relay local listener.

## Production package

The existing Windows Production pipeline will be rerun from the pushed main
commit that contains this acceptance and changelog update. `published=false`
remains the expected local Production-package state; it is not changed by
hand and does not create a new product version. Final artifact values are
recorded in `V1.5.5_RELEASE_CLOSURE_REPORT.md` after the rebuild.

```text
PRODUCT_VERSION=1.5.5
BUILD_ID=TO_BE_FILLED_AFTER_MAIN_REBUILD
INSTALLER_FILENAME=TO_BE_FILLED_AFTER_MAIN_REBUILD
INSTALLER_PATH=TO_BE_FILLED_AFTER_MAIN_REBUILD
INSTALLER_SIZE_BYTES=TO_BE_FILLED_AFTER_MAIN_REBUILD
INSTALLER_SHA256=TO_BE_FILLED_AFTER_MAIN_REBUILD
AUTOMATED_PACKAGE_GATE=TO_BE_FILLED_AFTER_MAIN_REBUILD
REAL_WINDOWS_INSTALL_SMOKE=NOT VERIFIED
REAL_DEVICE_SMOKE=NOT VERIFIED
```

The final installer is a deliverable for the user’s现场 validation. The
manifest will retain `published=false` and will record the actual
`packaged_dirty`, `package_smoke`, edition and SHA-256 values.
