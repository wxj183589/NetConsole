# Interface Discovery Limited Real-device Validation Report

> Phase: `PHASE 2D-B2`
> Status: `PARTIAL` (`COMWARE7_VALIDATION=PASS`; no eligible C9 SW candidate; C9 role extension not authorized)
> Scope: H3C interface discovery Shadow only
> Real device connection: `YES` (one authorized C7 target only)
> Production Shadow enabled: `NO`

## 1. Result and authorization gate

本轮在取得目标设备和维护窗口的明确人工批准后，仅对 `DEVICE-NB10-C7-01` 建立了一次既有连接路径，确认实际软件版本为 Comware 7，并完成三个串行 interface discovery capture cycle。Legacy 是唯一事实来源；Shadow 只在内存中比较同一份真实 CLI capture 的 normalized interface projection，不调用正式 Legacy collector，也不写入 Repository。

```text
PHASE2D_B2_STATUS=PARTIAL
REAL_DEVICE_READONLY_AUTHORIZED=YES
MAINTENANCE_WINDOW_APPROVED=YES
REAL_DEVICE_CONNECTION_ATTEMPTED=YES
VALIDATION_TARGET_COMWARE7=DEVICE-NB10-C7-01
VALIDATION_TARGET_COMWARE9=NONE
COMWARE7_VALIDATION=PASS
COMWARE9_VALIDATION=NOT_EXECUTED
ENGINEERING_GATES_READY=YES
PHASE2D_C_READY=NO
PHASE2D_READY=NO
```

本报告不把数据库历史记录当作现场版本的唯一证据：实际版本由本次真实只读 `display version` capture 确认。没有连接 C9、杭州10号线或任何其它设备，也没有因为 C7 通过而扩大范围。

## 2. Preflight identity and scope

```text
BRANCH=codex-A/engineering-hardening
START_HEAD=df6a31b352d9cc2a1bf77302e515a8572c6f37fc
HEAD=df6a31b352d9cc2a1bf77302e515a8572c6f37fc (validation source HEAD; report commit follows)
WORKTREE_DIRTY=NO
VENDOR=H3C
AUTHORIZED_SITE_SCOPE=杭州10号线; 宁波10号线
COMWARE7_TARGET=DEVICE-NB10-C7-01
COMWARE9_TARGET=NONE
SERIAL_EXECUTION=YES
MAX_DEVICES=1 (this run)
CYCLES_PER_DEVICE=3
```

本次人工授权进一步收窄为一台宁波10号线 H3C Comware 7 switch，最多三个连续 cycle；Comware 9 明确为 `NONE`。验证期间不扫描网络，不连接杭州10号线、C9 AC、其它设备，也不扩展到 ZTE、MR、AC、Optical、LLDP、MESH 或其它角色。

### 2.1 Candidate screening result

候选筛选仅对 `D:\NetConsoleData-dev` 中两个授权线路目录执行 SQLite `mode=ro` 查询，未读取地址、MAC、用户名、密码、SNMP 或隧道凭据字段，也未复制数据库：

```text
C7_CANDIDATE=DEVICE-NB10-C7-01
C9_CANDIDATE=NONE
SITE=宁波10号线
ROLE=SW
VERSION_EVIDENCE=Version 7.1.070 Release 7756P10
```

`DEVICE-NB10-C7-01` 是去标识化目标别名：本次绑定前只读核验其仍为 `in_service`、`included` 的宁波10号线 H3C/SW，既有 `device_facts` 为 `S10508X-G`、Comware 7，且关联 Legacy 采集成功。连接前使用既有 credential resolver/preflight，未输出凭据。实际 CLI 版本仍为 `Version 7.1.070 Release 7756P10`；未执行 C9。

### 2.2 Phase 2D-B2.1 Comware 9 switch candidate completion

2026-09-07 对两个授权线路的开发数据根进行了候选筛选。查询使用 SQLite `mode=ro`，只读取设备角色、状态、版本事实、模型和 Legacy 采集状态；没有扫描网络、连接设备、读取凭据字段或访问 `D:\NetConsoleData`。

```text
C9_SWITCH_CANDIDATE=NONE
SITE=杭州10号线; 宁波10号线
ROLE=SW
MODEL_FAMILY=NONE
VERSION_EVIDENCE=VERSION_EVIDENCE_INSUFFICIENT (no eligible H3C/SW Comware 9 current or historical fact)
LEGACY_EVIDENCE=NONE (no eligible C9 switch; C9 switch validation not executed)
STATUS=BLOCKED_ROLE_SCOPE
```

筛选事实如下：杭州10号线没有同时满足 `H3C + SW + in_service + included` 的设备；宁波10号线有 71 台符合状态/角色范围的 H3C/SW，其中当前 `device_facts` 明确为 Comware 7 的 25 台、版本未知的 46 台、Comware 9 为 0 台，`device_facts_history` 中也没有 Comware 9 的 SW 版本事实。宁波10号线符合范围且有成功 Legacy 记录的 SW 设备中，没有一台具备 C9 版本证据，因此不能猜测或生成 C9 switch alias。

现有资料另显示两条授权线路各有 1 台 `in_service + included`、已有成功 Legacy 记录的 H3C Comware 9 `AC`，因此仅记录角色扩展候选，不把它们用于本轮验证：

```text
C9_SWITCH_FOUND=NO
C9_WIRELESS_CONTROLLER_AVAILABLE=YES
PROPOSED_ROLE_EXTENSION=wireless_controller
ROLE_EXTENSION_REVIEW_REQUIRED=YES
C9_ROLE_EXTENSION_AUTHORIZED=NO
MAINTENANCE_WINDOW_APPROVED=NO (no C9-specific approval; prior C7 approval is not inherited)
REAL_DEVICE_CONNECTION_ATTEMPTED_C9=NO
PHASE2D_B2_C9_STATUS=BLOCKED_ROLE_SCOPE
```

本轮在候选筛选和 preflight 后停止，没有自动连接 AC、MR 或其它角色，也没有扩大线路或设备范围。后续只有取得明确的角色扩展批准（如选择 `wireless_controller`）以及独立的 C9 维护窗口批准，才可另行评估真实连接；本报告不作任何 C9 验证结论。

## 3. Existing-path reuse preflight

运行前和运行中确认并复用以下现有能力：

| Boundary | Existing path | Preflight result |
| --- | --- | --- |
| Operation envelope | `device.inventory.collect` / `DeviceOperationService` | 正式 worker 未调用，避免 LLDP/Optical 与 Repository 写入 |
| Profile | `resolve_device_inventory_profile` / `resources/device_command_profiles.json` | `h3c.comware.switch.generic.device-inventory.v1` v1；只取既有 `session.pagination`、`inventory.version`、`inventory.interfaces` |
| Command safety | `validate_command_list` / `command_reject_reason` | 三条实际命令逐条通过既有 `device.inventory.collect` Guard |
| Connection/session | `ssh_connection_context`、`ConnectHandler`、`choose_connection_target`、`prepared_connection_target` | 使用既有唯一 SSH target；单次 session，未手工拼接地址或凭据 |
| H3C collection/parser | 既有 `H3CParser.parse_interfaces`、Comware version parser | Legacy/Shadow 均只消费本次 CLI capture；正式 `collect_h3c_device_details` 未调用 |
| Repository | `Database.connect_readonly()`、现有 repository fingerprint/effect helper | 每个 cycle 前后均只读 fingerprint；Current/Recent/History/Revision 均 `NONE` |
| Shadow/compare | `InterfaceDiscoveryShadowRunner`、既有 normalized comparator | B1 已通过；本轮内存调用 3 次，无 writer/transport/repository 依赖 |

正式 `collect_h3c_device_details` 会创建 collect run、保存运行产物并写入既有 Repository，因此本轮没有调用它。operator-only harness 只复用既有 Profile/Guard/connection/parser/Shadow comparator；Shadow callback 只接收第二个 parser instance 生成的同一 capture normalized 结果，不得把该 capture-only 证据解释为生产 Shadow 已启用。

## 4. Device validation matrix

| Device | Role | Version | Cycle 1 | Cycle 2 | Cycle 3 | Repo Effect | Resume | Result |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DEVICE-NB10-C7-01 | SW | `Version 7.1.070 Release 7756P10` / `S10508X-G` | `MATCH` | `MATCH` | `MATCH` | `NONE` | `PASS` | `PASS` |
| C9 switch candidate `NONE` | SW | Comware 9 | `NOT_EXECUTED` | `NOT_EXECUTED` | `NOT_EXECUTED` | `NOT_EXECUTED` | `NOT_EXECUTED` | `NOT_EXECUTED` |

```text
COMWARE7_EXECUTED=YES
COMWARE7_MODEL_FAMILY=S10508X-G
COMWARE7_VERSION=Version 7.1.070 Release 7756P10
COMWARE7_MATCH_COUNT=3
COMWARE7_DIFFERENT_COUNT=0
COMWARE7_ERROR_COUNT=0
COMWARE7_TIMEOUT_COUNT=0
COMWARE7_REPOSITORY_EFFECT=NONE
COMWARE7_UNEXPECTED_WRITES=0
COMWARE7_STOP_SHADOW=PASS
COMWARE7_LEGACY_RESUME=PASS (capture-only Legacy parser health; no fourth device command)
COMWARE7_DEVICE_RESULT=PASS
COMWARE7_CYCLE1_LEGACY=SUCCESS
COMWARE7_CYCLE1_SHADOW=SUCCESS
COMWARE7_CYCLE1_COMPARE=MATCH
COMWARE7_CYCLE1_INTERFACE_COUNTS=220/220
COMWARE7_CYCLE1_ADDED_REMOVED_CHANGED=0/0/0
COMWARE7_CYCLE1_DURATION_MS=29275.3
COMWARE7_CYCLE1_REPOSITORY=current:NONE,recent:NONE,history:NONE,revision:NONE,writes:0
COMWARE7_CYCLE2_LEGACY=SUCCESS
COMWARE7_CYCLE2_SHADOW=SUCCESS
COMWARE7_CYCLE2_COMPARE=MATCH
COMWARE7_CYCLE2_INTERFACE_COUNTS=220/220
COMWARE7_CYCLE2_ADDED_REMOVED_CHANGED=0/0/0
COMWARE7_CYCLE2_DURATION_MS=27684.2
COMWARE7_CYCLE2_REPOSITORY=current:NONE,recent:NONE,history:NONE,revision:NONE,writes:0
COMWARE7_CYCLE3_LEGACY=SUCCESS
COMWARE7_CYCLE3_SHADOW=SUCCESS
COMWARE7_CYCLE3_COMPARE=MATCH
COMWARE7_CYCLE3_INTERFACE_COUNTS=220/220
COMWARE7_CYCLE3_ADDED_REMOVED_CHANGED=0/0/0
COMWARE7_CYCLE3_DURATION_MS=28431.9
COMWARE7_CYCLE3_REPOSITORY=current:NONE,recent:NONE,history:NONE,revision:NONE,writes:0

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
COMWARE9_CANDIDATE_STATUS=BLOCKED_ROLE_SCOPE
COMWARE9_REAL_DEVICE_CONNECTION=NO
```

每个 cycle 均完成了 Repository fingerprint BEFORE/AFTER、Legacy normalized interface DTO、Shadow normalized projection、compare/difference 和 effect 检查；第三个 cycle 后停止 Shadow invocation。停止后只对最后一份已保存 capture 做内存中的 Legacy-only parser health confirmation，没有执行第四次真实设备命令。

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

本轮只连接了授权目标一次并执行了五条既有只读会话/查询命令：`screen-length disable` 一次、`display version` 一次、`display interface` 三次；未执行 `system-view/configure/save/reboot/reset/shutdown/undo` 或 VLAN/interface 配置命令。`D:\NetConsoleData` 未访问；`D:\NetConsoleData-dev` 只读打开，未执行 SQL 写入、production backup、schema migration、History rebuild、Process restart 或 Cutover。设备配置未观察到变化。

本次 C9 候选补完未建立真实连接，不产生 C9 CLI evidence、Repository effect 或设备配置变化；C7 的历史真实验证结果保持不变。

## 6. Evidence and credential handling

```text
RAW_EVIDENCE_LOCAL_ONLY=YES
REAL_CAPTURE_C7=YES (raw CLI retained locally only)
REAL_CAPTURE_C7_DEIDENTIFIED=NO
REAL_CAPTURE_C9=NO
REAL_CAPTURE_C9_DEIDENTIFIED=NO
REAL_CAPTURE_DEIDENTIFIED=NO
SECRET_SCAN=PASS (summary and raw-file credential-pattern scan)
EVIDENCE_BUNDLE=PASS (local ignored bundle; no fixture submitted)
EVIDENCE_PATH=.local-reports/phase2d-b2-real-device/20260906T124204Z
REPORT_PATH=docs/dev/interface-discovery-real-device-validation-report.md
```

真实 CLI raw files 仅保存在仓库 `.local-reports` ignored 目录，未打印、未提交，也未生成 `REAL_CAPTURE` fixture；raw 文件可能包含现场标识，因此 `REAL_CAPTURE_DEIDENTIFIED=NO`。已完成 summary 与 raw-file credential-pattern scan，未发现凭据模式；凭据本身未输出。若后续需要长期 fixture，必须另行脱敏并明确标记 `REAL_CAPTURE`。

## 7. Offline regression record

真实 C7 证据完成后，重新执行以下隔离测试和工程门禁；这些门禁不把 C9 或 Production Cutover 标记为完成：

```text
REAL_CAPTURE_REGRESSION=NOT_EXECUTED (no deidentified fixture submitted)
SHADOW_TESTS=PASS
B1_REHEARSAL=PASS
REPLAY=PASS
REPOSITORY=PASS
DOCS_PATH=23 passed
MAIN_CONTRACT=12 passed, 3 warnings
ARCHITECTURE=PASS (stable green gates 8/8)
BASELINE_AUDIT=PASS
RUFF=PASS
COMPILE=PASS
DIFF_CHECK=PASS
CI_SELECTION=1 passed (included in DOCS_PATH gate)
FULL_SUITE=4696 passed, 2 skipped, 4 deselected, 33 warnings
NEW_FAILURES=0
BASELINE_DEBT_MATCH=PASS
```

本轮真实验证后，定向核心回归为 `167 passed`；文档/目录/CI selection 合计 `23 passed`；Main Contract 为 `12 passed, 3 warnings`；稳定架构绿门 `8/8 PASS`；baseline audit 为 Architecture expected/actual `7/7`、new `0`，Ruff new `0`，`BASELINE_DEBT_MATCH=PASS`；Ruff、compileall、diff check 均通过。baseline-aware Python 全量为 `4696 passed, 2 skipped, 4 deselected, 33 warnings`，退出码通过并输出 `NEW_FAILURES=0`。没有生成去标识化真实 fixture，因此 Real Capture regression 标记为 `NOT_EXECUTED`，不影响本次 raw-local C7 结果。

此前一次未排除基线项的全量记录为 `4695 passed, 2 skipped, 4 deselected, 1 failed`；该历史失败为 release runtime subset 的顺序/环境敏感问题，隔离重跑通过，未归因于 B2。本轮按精确 baseline exclusions 的全量回归已通过，见上方 `FULL_SUITE`。

### 7.1 Candidate-only preflight gates (2026-09-07)

本次 B2.1 只有候选筛选和文档变更，没有修改生产 Python、Profile、Parser、DTO、Repository、API、UI 或任务状态机。因此按测试基线不触发 Full Suite；以下是本次候选补完后实际重跑的离线门禁，不能替代 C9 真实设备验证：

```text
REAL_CAPTURE_REGRESSION=NOT_EXECUTED (no deidentified C9 fixture)
SHADOW_TESTS=PASS (75 passed with B1/Replay/Repository related coverage)
B1_REHEARSAL=PASS
REPLAY=PASS
REPOSITORY=PASS
DOCS_PATH=22 passed
MAIN_CONTRACT=12 passed, 3 warnings (existing Starlette deprecation warnings)
ARCHITECTURE=BASELINE_RETAINED (run_all reports 4/12 guard failures; baseline audit actual=7, new=0)
BASELINE_AUDIT=PASS (ARCHITECTURE_BASELINE_NEW=0; RUFF_BASELINE_NEW=0)
RUFF=PASS (All checks passed)
COMPILE=PASS
DIFF_CHECK=PASS
CI_SELECTION=1 passed
FULL_SUITE=NOT_RUN (docs-only change; no production-adjacent Python changed)
NEW_FAILURES=0
BASELINE_DEBT_MATCH=PASS
```

`ARCHITECTURE=BASELINE_RETAINED` 是对本次直接运行 `scripts/architecture/run_all.py` 非零结果的准确记录；失败项均已被 Baseline Debt Audit 识别为既有债务，本轮没有新增架构发现。此前 C7 验证记录中的全量测试结果仍保留为历史 C7 证据，不被本次 C9 候选筛选重新包装为 C9 结果。

## 8. Remaining boundary and next decision gate

本轮 C7 已按批准范围完成并通过；C9 没有授权目标、没有连接、没有执行，不能据此宣称 Phase 2D-B2 完整完成。下一步若要进入 Phase 2D-C，必须重新取得独立 C9 目标/版本/维护窗口批准，并满足全量 B2 通过条件；本轮不得启用生产 Shadow 或执行 Production Cutover。

```text
REMAINING_BLOCKER_1=No eligible H3C Comware 9 SW candidate in the two authorized sites
REMAINING_BLOCKER_2=Role extension review required before considering the existing C9 AC records
REMAINING_BLOCKER_3=No independent C9 maintenance-window approval
```

```text
PHASE2D_B2_STATUS=PARTIAL
REAL_DEVICE_READONLY_AUTHORIZED=YES
MAINTENANCE_WINDOW_APPROVED=YES
REAL_DEVICE_CONNECTION_ATTEMPTED=YES
COMWARE7_VALIDATION=PASS
COMWARE9_VALIDATION=NOT_EXECUTED
PHASE2D_B2_C9_STATUS=BLOCKED_ROLE_SCOPE
ROLE_EXTENSION_REVIEW_REQUIRED=YES
C9_WIRELESS_CONTROLLER_AVAILABLE=YES
C9_ROLE_EXTENSION_AUTHORIZED=NO
PHASE2D_C_READY=NO
PHASE2D_READY=NO
```

即使 C7 验证通过，也不得启用生产 Shadow、替换 Legacy、删除 Legacy 或直接进入 Cutover；本轮的下一阶段决策仍保持 `Phase 2D-C Interface Discovery Production Cutover Decision` 未就绪。
