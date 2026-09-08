# Interface Discovery Phase 2D-E3 Real-device Revalidation Report

## Decision

```text
PHASE2D_E3_STATUS=FAIL
E3_ACCEPTANCE=NOT_EXECUTED
STOP_REASON=ERROR_BEFORE_FIRST_COMPARABLE_CYCLE
REAL_DEVICE_CONNECTION_ATTEMPTED=YES
PRODUCTION_ACTIVATION_EXECUTED=NO
PRODUCTION_CUTOVER_EXECUTED=NO
WAVE0_EXECUTED=NO
WAVE1_EXECUTED=NO
```

This report records the fresh Phase 2D-E3 read-only attempt authorized for one
device. The attempt stopped immediately after the existing SSH connection path
reported an error, before a comparable interface cycle completed. No reconnect
or retry was made.

## Execution provenance

```text
BRANCH=codex-A/formal-main-merge
VALIDATION_START_HEAD=ff7282f3b1f2d4ac77dac54c07fe280c17c8046f
WORKTREE_DIRTY=NO
VALIDATION_DATA_ROOT=D:\NetConsoleData-dev
RAW_EVIDENCE_LOCAL_ONLY=YES
```

The validation ran from the existing formal worktree. The temporary capture
harness and generated evidence are under the ignored `.local-reports` path and
are not production source changes.

## Authorization and scope

```text
REAL_DEVICE_READONLY_AUTHORIZED=YES
MAINTENANCE_WINDOW_APPROVED=YES
TARGET=DEVICE-NB10-C7-01
SITE=宁波10号线
VENDOR=H3C
ROLE=switch
AUTHORIZED_COMWARE_MAJOR=7
CAPABILITY=interface.discovery
```

No other device, site, vendor, role, version, capability, Wave 0, or Wave 1
scope was selected. No production activation or cutover path was invoked.

## Preflight

The development database was opened read-only. Exactly one existing H3C/SW
record matched the target mapping criteria and its stored fact was
`S10508X-G` / `Version 7.1.070 Release 7756P10`. The existing credential
resolver reported an available local credential without exposing its value.

The existing H3C inventory profile resolved to:

```text
PROFILE_ID=h3c.comware.switch.generic.device-inventory.v1
OPERATION_ID=device.inventory.collect
COMMAND_GUARD=PASS
COMMANDS=screen-length disable; display version; display interface
CONNECTION_CANDIDATES=1
PROTOCOL=SSH
```

The command set was checked through the existing Command Guard. No formal
collector was called, so no DeviceFactRepository writer was entered.

## Real-device attempt

```text
CONNECTION_ATTEMPTED=YES
CONNECTION_RESULT=ERROR
FIRST_COMPARABLE_CYCLE=NOT_STARTED
ACTUAL_COMWARE_VERSION=NOT_CONFIRMED
MODEL_FAMILY=NOT_CONFIRMED
RAW_CLI_OUTPUT_CAPTURED=NO
```

The single authorized connection attempt ended with an error before any raw
CLI evidence was written and before the first `display interface` result could
be compared. Because the authorized stop rule applies to this error, the run
did not reconnect and did not try to force a 3/3 result. The exact connection
diagnostic is intentionally not copied into the tracked report because it may
contain environment or endpoint details; the local machine-readable summary
retains only the safe error classification.

## Cycle matrix

| Cycle | Routing | Legacy | Shadow | Compare | Interfaces | Repository | Result |
|---|---|---|---|---|---:|---|---|
| 1 | NOT_STARTED | NOT_EXECUTED | NOT_EXECUTED | NOT_EXECUTED | N/A | NONE | STOPPED_BEFORE_CYCLE |
| 2 | NOT_STARTED | NOT_EXECUTED | NOT_EXECUTED | NOT_EXECUTED | N/A | NONE | NOT_EXECUTED |
| 3 | NOT_STARTED | NOT_EXECUTED | NOT_EXECUTED | NOT_EXECUTED | N/A | NONE | NOT_EXECUTED |

```text
COMPLETED_CYCLES=0
MATCH_COUNT=0
DIFFERENT_COUNT=0
ERROR_COUNT=1
TIMEOUT_COUNT=0
CONTRACT_MISMATCH_COUNT=0
INTERFACE_COUNT_ANOMALY_COUNT=0
STOP_SHADOW=PASS
LEGACY_RESUME=NOT_EXECUTED
```

`STOP_SHADOW=PASS` means the shadow invocation was not continued after the
pre-cycle error; it does not mean the E3 validation passed.

## Repository and device safety

The post-attempt read-only SQLite check produced the same repository fingerprint
as the pre-attempt baseline. SQLite integrity remained `ok`.

```text
CURRENT_EFFECT=NONE
RECENT_EFFECT=NONE
HISTORY_EFFECT=NONE
REVISION_EFFECT=NONE
UNEXPECTED_REPOSITORY_WRITES=0
DATABASE_REPAIR_REQUIRED=NO
PROCESS_RESTART_REQUIRED=NO
HISTORY_REBUILD_REQUIRED=NO
DEVICE_CONFIG_CHANGED=NO
```

Only the existing read-only connection path was authorized. No configuration
command, `system-view`, `save`, `reboot`, `reset`, `shutdown`, `undo`, SFTP/FTP,
AAA/SNMP, VLAN/interface configuration, LLDP/Optical, Trackside, FIT-AP,
MR/MESH, or other capability command was selected.

## Evidence

```text
EVIDENCE_BUNDLE=PASS
RAW_EVIDENCE_LOCAL_ONLY=YES
RAW_CLI_EVIDENCE_FILES=0
SECRET_VALUES_IN_TRACKED_REPORT=NO
LOCAL_EVIDENCE_ROOT=.local-reports/phase2d-e3-real-device/20260908T151916Z-d14fb02f
POSTFLIGHT_MANIFEST=postflight.json
```

The local summary and postflight manifest contain no password, token, SNMP
community, IP address, hostname, MAC address, or serial number. No
de-identified long-term real capture was created because no command output was
captured.

## Follow-up boundary

Phase 2D-E3 is not accepted. The current maintenance window is considered
consumed for this attempt and no further device connection is made in this run.
A future attempt requires a new explicit maintenance-window approval and must
first investigate the connection-path error. Production activation remains
disabled; the default path remains Legacy.

```text
PHASE2D_E3_READY=NO
PHASE2D_E_READY=NO
PHASE2D_READY=NO
```
