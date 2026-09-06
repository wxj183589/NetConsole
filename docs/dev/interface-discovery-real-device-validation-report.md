# Interface Discovery Limited Real-device Validation Report

> Phase: `PHASE 2D-B2`
> Status: `BLOCKED_AUTHORIZATION`
> Scope: H3C interface discovery Shadow only
> Real device connection: `NO`
> Production Shadow enabled: `NO`

## 1. Result and authorization gate

本轮已完成离线 preflight，但当前执行上下文没有提供本轮明确的真实设备只读授权、批准的 Comware 7/9 目标和维护窗口授权。依据 Phase 2D-B2 安全门禁，真实连接和真实命令均未尝试；这不是工程失败，而是等待人工授权。

```text
PHASE2D_B2_STATUS=BLOCKED_AUTHORIZATION
REAL_DEVICE_READONLY_AUTHORIZED=NO
MAINTENANCE_WINDOW_APPROVED=NO
REAL_DEVICE_CONNECTION_ATTEMPTED=NO
ENGINEERING_GATES_READY=YES
PHASE2D_C_READY=NO
PHASE2D_READY=NO
```

本报告不从历史设备记录、凭据存在性、旧任务授权或 `REAL_DEVICE_READY=YES` 推断本轮授权，也不选择生产设备来凑足验证范围。

## 2. Preflight identity and scope

```text
BRANCH=codex-A/engineering-hardening
START_HEAD=b1fe6255b3420cd11ed4cf7d4400b6c1c6e6e5ae
HEAD=b1fe6255b3420cd11ed4cf7d4400b6c1c6e6e5ae
WORKTREE_DIRTY=NO
VENDOR=H3C
COMWARE7_TARGET=NONE
COMWARE9_TARGET=NONE
SERIAL_EXECUTION=YES
MAX_DEVICES=2
CYCLES_PER_DEVICE=3
```

范围冻结为最多一台 Comware 7 和最多一台 Comware 9，按设备串行、每台最多三个连续可比 cycle。没有批准目标时不扫描网络、不自行选择设备、不扩展到 ZTE、MR、AC、Optical、LLDP、MESH 或其它角色。

## 3. Existing-path reuse preflight

离线检查确认未来获得授权后应复用以下现有能力：

| Boundary | Existing path | Preflight result |
| --- | --- | --- |
| Operation envelope | `device.inventory.collect` / `DeviceOperationService` | 已存在；本轮未调用 |
| Profile | `resolve_device_inventory_profile` / `resources/device_command_profiles.json` | 已存在；C7/C9 profile 需现场版本证据再次绑定 |
| Command safety | `validate_operation_commands` / `command_reject_reason` | 已存在；不绕过 Guard |
| Connection/session | `netmiko_connection.ssh_connection_context`、`ConnectHandler` | 已存在；本轮未建立 session |
| H3C collection/parser | `collect_h3c_device_details`、既有 H3C interface parser | 已存在；正式 collector 会写 collect run/Repository，不作为 Shadow writer |
| Repository | `DeviceFactRepository`、`Database.connect_readonly()` | fingerprint 可只读；本轮无真实数据访问 |
| Shadow/compare | `InterfaceDiscoveryShadowRunner`、既有 normalized comparator | 已在 B1 隔离演练通过 |

正式 `collect_h3c_device_details` 会创建 collect run、保存运行产物并写入既有 Repository。因此真实验证必须先冻结 Legacy 预期 delta，再证明 Shadow 没有额外 writer/effect；不得新增第二套采集、连接、Parser、Repository 或 Task runtime。

## 4. Device validation matrix

| Device | Version | Cycle 1 | Cycle 2 | Cycle 3 | Repo Effect | Resume | Result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| DEVICE-C7-01 | Comware 7 | `NOT_EXECUTED` | `NOT_EXECUTED` | `NOT_EXECUTED` | `NOT_EXECUTED` | `NOT_EXECUTED` | `NOT_EXECUTED` |
| DEVICE-C9-01 | Comware 9 | `NOT_EXECUTED` | `NOT_EXECUTED` | `NOT_EXECUTED` | `NOT_EXECUTED` | `NOT_EXECUTED` | `NOT_EXECUTED` |

```text
COMWARE7_EXECUTED=NO
COMWARE7_MODEL_FAMILY=NONE
COMWARE7_VERSION=NONE
COMWARE7_MATCH_COUNT=0
COMWARE7_DIFFERENT_COUNT=0
COMWARE7_ERROR_COUNT=0
COMWARE7_TIMEOUT_COUNT=0
COMWARE7_REPOSITORY_EFFECT=NOT_EXECUTED
COMWARE7_UNEXPECTED_WRITES=0
COMWARE7_STOP_SHADOW=NOT_EXECUTED
COMWARE7_LEGACY_RESUME=NOT_EXECUTED
COMWARE7_DEVICE_RESULT=NOT_EXECUTED

COMWARE9_EXECUTED=NO
COMWARE9_MODEL_FAMILY=NONE
COMWARE9_VERSION=NONE
COMWARE9_MATCH_COUNT=0
COMWARE9_DIFFERENT_COUNT=0
COMWARE9_ERROR_COUNT=0
COMWARE9_TIMEOUT_COUNT=0
COMWARE9_REPOSITORY_EFFECT=NOT_EXECUTED
COMWARE9_UNEXPECTED_WRITES=0
COMWARE9_STOP_SHADOW=NOT_EXECUTED
COMWARE9_LEGACY_RESUME=NOT_EXECUTED
COMWARE9_DEVICE_RESULT=NOT_EXECUTED
```

由于没有授权，以下证据链没有开始：Repository fingerprint BEFORE、Legacy evidence/DTO、Shadow command/DTO、compare/difference report、fingerprint AFTER 和 Legacy health confirmation。

## 5. Production and repository safety

```text
LEGACY_COLLECTOR_CHANGED=NO
PARSER_CHANGED=NO
DTO_CHANGED=NO
REPOSITORY_WRITE_PATH_CHANGED=NO
PROFILE_CHANGED=NO
OPERATION_ID_ADDED=NO
FEATURE_FLAG_ADDED=NO
API_CHANGED=NO
UI_CHANGED=NO
TASK_STATE_MACHINE_CHANGED=NO
DEVICE_CONFIG_CHANGED=NO

CURRENT_UNEXPECTED_EFFECT=NONE
RECENT_UNEXPECTED_EFFECT=NONE
HISTORY_UNEXPECTED_EFFECT=NONE
REVISION_UNEXPECTED_EFFECT=NONE
UNEXPECTED_SHADOW_WRITES=0
```

本轮没有连接设备、没有执行命令、没有访问或修改 `D:\NetConsoleData` / `D:\NetConsoleData-dev`，没有运行真实设备 harness，也没有执行 production backup、schema migration、SQL 写入或 Cutover。

## 6. Evidence and credential handling

```text
RAW_EVIDENCE_LOCAL_ONLY=YES (no raw evidence created)
REAL_CAPTURE_C7=NO
REAL_CAPTURE_C9=NO
REAL_CAPTURE_DEIDENTIFIED=NO
SECRET_SCAN=PASS (no real evidence submitted)
EVIDENCE_BUNDLE=NOT_EXECUTED
```

没有保存真实 CLI、IP、hostname、serial、MAC、username、credential 或任何现场标识；没有把模拟 fixture 标记为 `REAL_CAPTURE`。未来获批后，Raw Evidence 只能保存在 gitignored 本地证据目录，提交前仅允许人工复核后的去标识化 fixture。

## 7. Offline regression record

本轮只执行隔离测试和文档/工程门禁，不宣称真实设备验证完成：

```text
REAL_CAPTURE_REGRESSION=NOT_EXECUTED
SHADOW_TESTS=PASS
B1_REHEARSAL=PASS
REPLAY=PASS
REPOSITORY=PASS
DOCS_PATH=22 passed
MAIN_CONTRACT=12 passed, 3 warnings
ARCHITECTURE=PASS (stable green gates 8/8)
BASELINE_AUDIT=PASS
RUFF=PASS
COMPILE=PASS
DIFF_CHECK=PASS
CI_SELECTION=1 passed
FULL_SUITE=KNOWN_ENV_ORDER_SENSITIVE_FAILURE
NEW_FAILURES=0
BASELINE_DEBT_MATCH=PASS
```

本轮离线定向回归共 `167 passed`；另执行文档/路径测试 `22 passed`、CI selection `1 passed`、Main Contract `12 passed, 3 warnings`、稳定架构绿门 `8/8 PASS`、baseline audit `NEW_FAILURES=0`。架构聚合测试仍报告 2 个既有失败，对应 4 项未豁免 finding（direct SQL、UI business logic、runtime path、storage registry）；不属于本次 B2 文档变更，未修改也未归因于 B2。

既有全量基线记录为 `4695 passed, 2 skipped, 4 deselected, 1 failed`；失败为 release runtime subset 的既有顺序/环境敏感测试，隔离重跑通过，未归因于 B2。真实验证完成前不将该记录写成 Full Suite Green。

## 8. Remaining blockers and next authorization request

开始真实验证前必须由人工明确提供：

1. `REAL_DEVICE_READONLY_AUTHORIZED=YES`，并明确批准的目标 alias；
2. `VALIDATION_TARGET_COMWARE7=<approved target or NONE>`；
3. `VALIDATION_TARGET_COMWARE9=<approved target or NONE>`；
4. `MAINTENANCE_WINDOW_APPROVED=YES`，或明确当前验证可立即执行；
5. 设备 owner、低风险维护状态、Legacy 正常基线和 stop/resume 责任人。

在这些条件满足前：

```text
PHASE2D_B2_STATUS=BLOCKED_AUTHORIZATION
REAL_DEVICE_CONNECTION_ATTEMPTED=NO
PHASE2D_C_READY=NO
PHASE2D_READY=NO
```

即使未来 B2 完整通过，也不得在本轮启用生产 Shadow、替换 Legacy、删除 Legacy 或直接进入 Cutover；下一阶段仅为 `Phase 2D-C Interface Discovery Production Cutover Decision`。
