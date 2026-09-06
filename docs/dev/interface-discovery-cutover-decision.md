# Interface Discovery Scoped Cutover Decision

> 日期：2026-09-07
> 评审阶段：Phase 2D-C — Scoped Production Cutover Decision Review
> 评审基线：`e5f1cbf45f8f24a7281a515c8704e09c3c246e37`
> 生产切换：未执行

本文是工程决策评审，不是生产切换批准书，也不改变当前生产运行路径。本文只决定是否允许进入下一阶段的受控实现工作。

## 1. 决策结论

`CUTOVER_DECISION=APPROVE_SCOPED_IMPLEMENTATION`

结论含义：允许开始 Phase 2D-D 的受控实现与验证设计，范围仅为：

- H3C
- 角色 `switch`
- Comware 7
- 能力 `interface.discovery`
- Capability Primary + Legacy Fallback 的后续实现

本结论不等于 Production Cutover，不等于已修改生产路由，也不等于 C9 已验证。当前正式路径仍为 Legacy。

`IMPLEMENTATION_STATUS=NOT_IMPLEMENTED`
`PRODUCTION_CUTOVER_EXECUTED=NO`
`CURRENT_PRODUCTION_ROUTE=LEGACY`

批准的理由是：C7 已完成授权范围内的真实只读验证并通过，Repository 隔离、回滚/备份演练和迁移契约已通过，且可以把下一步实现严格收敛在一个可验证的 envelope 内。C9 Switch 没有候选，继续保持 deferred，不以 C9 AC 或其他角色替代。

## 2. Evidence / Gate Decision Matrix

| Evidence / Gate | Status | Decision / Boundary |
|---|---|---|
| Replay | PASS | 保持 Legacy 事实来源；接口规范化结果可比较 |
| Golden | PASS | 使用既有 Device Inventory 等价性与 golden 约束 |
| Shadow isolated rehearsal | PASS | Shadow observe-only；失败不能使 Legacy 主流程失败 |
| C7 real validation | PASS | `DEVICE-NB10-C7-01`，3/3 MATCH，0 DIFFERENT，0 ERROR，0 TIMEOUT |
| C9 switch validation | DEFERRED | 授权范围和候选不足；不连接 C9 AC，不用其他角色替代 |
| Repository effect | PASS | C7 三个 cycle 均无 Current/Recent/History/Revision 非预期变化 |
| Rollback rehearsal | PASS | 已验证停止 Shadow、恢复 Legacy、隔离写路径的演练边界 |
| Backup rehearsal | PASS | 已完成备份前置与恢复说明的 rehearsal；不是生产备份 |
| Production backup | NOT EXECUTED | 本阶段禁止触碰生产；未来 Phase 2D-D 切换前强制执行 |
| Scoped routing design | PASS | 已定义 envelope、默认 Legacy、allowlist、fail-closed 规则 |
| Scoped rollback design | PASS | 可将受控范围路由归零为 Legacy；任何写路径异常都停止扩展 |
| Production monitoring plan | PASS | 已定义 Wave 0/1/2、指标、退出条件和停止条件 |
| No new failures | PASS | 本次仅新增文档；既有 baseline debt 与新增失败核对通过 |

门禁的 PASS 只表示该项满足本阶段的评审要求。`Production backup=NOT EXECUTED` 是因为本阶段明确禁止执行，不是把未执行的生产动作伪装为完成。

## 3. Evidence scope and exclusions

### 3.1 已验证证据

本阶段依赖的 C7 真实只读证据来自既有 Phase 2D-B2 报告：

- 目标：`DEVICE-NB10-C7-01`
- 线路：宁波10号线
- 角色：`SW`，归一化为 `switch`
- 实际设备族：H3C S10508X-G
- 实际 Comware 主版本：7
- Cycle 1/2/3：全部 `MATCH`
- 每个 cycle：Legacy 220 接口、Shadow 220 接口，added/removed/changed 均为 0
- 每个 cycle：Repository Current/Recent/History/Revision effect 均为 none
- Shadow stop、Legacy resume、设备配置未变化均通过

原始 CLI evidence 仍只保存在本地 gitignored evidence 路径；本仓库不提交原始现场输出、凭据或现场敏感字段。

### 3.2 Deferred / Out of scope

以下范围本阶段不验证、不连接、不切换：

- H3C Comware 9 Switch：无可用候选，`C9_SWITCH_VALIDATION=DEFERRED`
- H3C wireless controller / AC：不可作为 C9 Switch 替代
- mobile router、ZTE
- LLDP、Optical、Trackside、FIT-AP、MR、MESH
- 其他杭州10号线或宁波10号线设备
- 任何设备配置、SFTP/FTP、AAA、SNMP、VLAN、interface 配置
- Command Profile JSON、Parser、DTO、Repository contract、API、UI、Task state machine、版本、安装包、发布
- 生产数据库备份、生产数据修复、生产路由改变

`C9_DEFAULT_PATH=LEGACY`
`C9_WIRELESS_CONTROLLER_USED_AS_SUBSTITUTE=NO`

## 4. Current code facts

### 4.1 Legacy entry and fact source

当前用户触发入口仍是 `POST /devices/{device_uuid}/refresh`，请求只选择稳定的 `device.inventory.collect` Operation ID。调用链为：

`DeviceDetailApplicationService.refresh` → `DeviceOperationService.start` → `run_device_inventory_refresh` → `collect_h3c_device_details`。

`DeviceOperationService` 从受管设备记录和既有 `DeviceFactRepository` fact 构造 `DevicePlatformFacts`，再经 `resolve_device_operation_profile` 解析 Profile。Worker 会再次用提交的 platform facts 解析并核对 Profile identity，之后才进入现有 H3C collector。

现有 H3C collector 是全量 inventory 采集路径：按 Profile/Command Guard 执行版本、设备信息、接口、光模块和 LLDP 等步骤，并分别写入 facts、interfaces、optical、LLDP。现有接口 writer 是 `DeviceFactRepository.replace_device_interfaces`，其职责包含 Current 和 bounded history 维护。

因此，当前正式 Legacy entry 是唯一事实来源和唯一生产路径；当前代码没有 Capability Primary 路由。

### 4.2 Shadow entry and authority

`InterfaceDiscoveryShadowRunner` 只接收已归一化的 Legacy result 和受控 callback：

- `CAPABILITY_NAME=interface.discovery`
- 只比较规范化的 `interfaces`
- Shadow status 不取代 Legacy status
- Shadow failure / timeout 只形成诊断结果，不能使 Legacy 主流程失败
- `repository_write=FORBIDDEN`
- 不创建 transport、collector、Repository、数据库、API、UI 或新的 Operation ID

当前 Shadow 没有正式生产入口，也没有写 Current、Recent、History、Revision 的能力。

### 4.3 Existing seam and what is absent

可以复用的既有 seam：

- 设备平台事实识别与角色归一化
- `resolve_device_operation_profile` 及 submitted Profile identity re-check
- 现有 read-only Command Guard
- 现有 SSH connection context
- 现有接口 parser、规范化 DTO 和等价性比较
- 现有 `DeviceFactRepository.replace_device_interfaces`

当前不存在且必须在 Phase 2D-D 设计/实现/测试中补齐的部分：

- 按设备、角色和软件主版本选择 Capability route 的内部策略
- capability 成功/失败后的单写入 fallback seam
- 能确保 capability 失败时不先写 Repository 的 selector-level result boundary
- 只允许 Wave 0/1/2 目标的内部受控 rollout policy

`FeatureGate` / Feature Registry 是全局 edition、runtime 或内部功能可见性机制，不含 vendor/role/version/device scope。因此不得把它直接当作本次设备级路由开关，也不新增泛化 Feature Flag。

## 5. Frozen migration envelope

只有同时满足下列条件，未来实现才可以选择 Capability route：

```text
operation_id       == device.inventory.collect
capability         == interface.discovery
vendor              == h3c
role                == switch
platform            == comware
software_major     == 7
version_evidence   == trusted_and_current
profile_binding    == expected_inventory_profile
rollout_target     == explicit_scoped_allowlist
```

其中：

- `software_major` 必须来自真实、可信且仍适用的版本事实；缺失、过期、未知或只凭设备型号推断时拒绝 Capability。
- Profile 的 generic `software_version="*"` 只能证明现有 read-only command contract 可解析，不能单独证明 Comware 7 envelope。
- 角色必须是明确的 `switch`；未知角色、AC、MR 或角色映射不确定时回到 Legacy。
- rollout target 必须来自未来实现提供的内部、不可由普通用户请求任意扩大范围的 allowlist。allowlist 缺失、为空、格式不可信时默认 Legacy。
- 任何 envelope 条件不满足时，行为必须是 `route=LEGACY`，而不是报错后尝试猜测版本或角色。

`DEFAULT_ROUTE=LEGACY`
`UNKNOWN_VERSION_ROUTE=LEGACY`
`UNKNOWN_ROLE_ROUTE=LEGACY`
`PROFILE_MISMATCH_ROUTE=LEGACY`
`CAPABILITY_OUTSIDE_ENVELOPE=LEGACY`

## 6. Scoped routing design for Phase 2D-D

### 6.1 Placement

建议新增一个小型、纯策略的内部模块，例如：

`src/netconsole/services/device_inventory_routing.py`

该模块只接收已解析的 operation、platform facts、Profile identity 和内部 rollout policy，返回不可变的 route decision。它不连接设备、不解析 CLI、不写 Repository。

调用位置：

1. `DeviceOperationService._plan` 在 Profile resolver 完成后计算 route decision。
2. `run_device_inventory_refresh` 对 submitted facts 和 Profile identity 再次执行同一 fail-closed 检查。
3. 真正的 selector-level execution 在 H3C collector 内部复用现有 connection、Guard 和 parser；不能让 capability 输出在 fallback 前触发 Repository write。

不新增 public API、不增加 Operation ID、不改变现有 `device.inventory.collect` 的用户入口。

### 6.2 Future decision model

未来实现可用如下最小模型表达策略：

- `ValidatedMigrationEnvelope`：冻结 vendor、role、platform、software major、capability、Profile identity 和 rollout scope。
- `DeviceInventoryRouteDecision`：`LEGACY` 或 `CAPABILITY_PRIMARY_WITH_LEGACY_FALLBACK`，附带安全的 reason code。

决策优先级必须是 fail-closed：

1. operation/capability 不匹配 → Legacy
2. vendor/role/platform/version 任一不匹配或不可信 → Legacy
3. Profile identity 不匹配 → Legacy
4. device 不在内部 rollout allowlist → Legacy
5. 所有条件满足 → 允许进入后续受控 capability primary 逻辑

这只是下一阶段实现的设计，不是本阶段对代码的修改授权。

## 7. Capability Primary + Legacy Fallback

未来 Phase 2D-D 的单设备、单次采集顺序必须是：

1. 保持一次正式 `device.inventory.collect` 任务和一次冻结的 Profile/Platform facts。
2. 仅对 envelope 内的 `interface.discovery` selector 尝试 Capability Primary。
3. Capability 复用现有 read-only Guard、连接层、`display interface` command contract 和接口 parser。
4. Capability 必须先得到完整、可验证、规范化的接口结果；在结果通过 contract validation 前不得写 Repository。
5. Capability 成功时由选中的路径调用既有接口 writer 一次。
6. Capability 失败、timeout、unsupported、contract mismatch 或输出无效时，丢弃 capability candidate，由 Legacy selector 执行并写入一次。
7. Capability 已经写入后才发现失败、或出现第二次 writer 调用，均视为实现缺陷，立即停止 rollout；不得用“最终数据相同”掩盖双写。
8. 其他 inventory selector 的行为保持既有 Legacy 语义，不因本 envelope 自动迁移。

期望写入不变量：

```text
one collection selector -> at most one Repository writer
capability success      -> capability candidate writes once
capability failure      -> legacy candidate writes once
no capability selection -> legacy writes once
```

现有全量 collector 的分段写入结构说明：Phase 2D-D 必须先建立 selector-level result boundary，再接入 fallback；不能仅通过一个全局布尔开关包住现有全量 collector。

## 8. Repository contract and rollback

### 8.1 Repository contract

本决策不要求数据库 schema migration。未来实现应继续使用现有 Repository contract：

- Current、Recent10 和已有 bounded history 的语义不变
- unchanged suppression、empty snapshot protection 和 revision 语义不变
- 不增加 capability source 列、不增加 shadow revision、不增加第二套历史表
- Legacy 与 Capability 共享同一个规范化 `DeviceInterfaceDTO` contract
- Repository 只看到最终被选中的一个 candidate，不知道 Shadow 或路由试验细节

若后续发现必须增加 source/schema 才能区分两条 writer，必须回到新的设计评审，不能在 Phase 2D-D 中隐式扩张。

### 8.2 Scoped rollback

未来 rollback 的最小范围只能是：

`H3C + switch + Comware 7 + interface.discovery`

触发 rollback 时将该内部 rollout scope 置为空或显式禁用，所有请求回到 Legacy；不恢复数据库、不重建 history、不修改其他 vendor/role/capability。

必须立即 rollback/停止扩展的条件包括：

- 任意 unexpected Current/Recent/History/Revision write
- capability 与 Legacy 的稳定语义差异
- capability failure 后 Legacy 未成功接管
- writer 被调用超过一次
- command guard violation、配置变化或非只读命令迹象
- 持续 timeout、任务失败或用户可见回归
- 版本、角色、Profile identity 无法确认
- 接口数量或字段出现未解释异常

代码级 rollback 仍应保留 Legacy 默认路径；配置级 rollback 只能由受控内部 rollout policy 完成，不能依赖 public FeatureGate。Phase 2D-D 必须用测试证明“路由归零后无生产数据恢复动作要求”。

## 9. Production monitoring and waves

监控优先复用现有 task/result 和结构化日志，不引入新的数据库或监控系统。只记录脱敏的状态、reason code、计数、耗时和 Repository effect，不记录凭据或原始 CLI。

建议最少具备以下指标：

- collection success / failure
- capability primary success
- fallback to Legacy 次数
- capability error / timeout / contract mismatch
- interface count 与既有 baseline 的异常
- compare added / removed / changed
- Repository effect anomaly
- 用户可见任务回归

### Wave 0

- 目标：已完成 C7 真实只读验证的 `DEVICE-NB10-C7-01`
- 前提：Phase 2D-D 实现通过 isolated rehearsal、Repository write counter、rollback rehearsal
- 退出条件：连续受控运行均无差异、无非预期写入、无 fallback failure、无 timeout、Legacy fallback 可用

### Wave 1

- 目标：少量同一线路范围内的 H3C Switch Comware 7 设备
- 每台必须有可信、最新的 C7 版本事实和正常 Legacy 记录
- 不包含 C9、unknown version、unknown role、AC、MR 或未授权站点
- 退出条件：预先约定的样本量完成，所有 hard-stop 指标为零，且任何 fallback 后 Legacy 结果仍符合契约

### Wave 2

- 目标：授权范围内、证据充分的 H3C Switch Comware 7 集合
- 只有 Wave 1 稳定并完成 owner sign-off 后才可进入
- 不自动扩展到 C9 或其他角色

任何 Wave 的 hard-stop 事件都要求先归零 rollout scope、恢复 Legacy、保留诊断证据并重新评审。错误/timeout 的具体比例阈值必须在实现前由 owner 明确；Wave 0 不接受以平均值抵销单台 hard-stop。

## 10. Production backup gate

本阶段不读取、不复制、不修改生产数据：

`PRODUCTION_BACKUP_REQUIRED=YES`
`PRODUCTION_BACKUP_EXECUTED=NO`
`PRODUCTION_DATA_TOUCHED=NO`

未来 Phase 2D-D 进入任何生产切换前，必须先完成并验证正式生产备份，至少绑定：

- 备份时间、应用版本、Git SHA
- 生产数据库清单、大小和校验摘要
- 备份文件可读性
- 恢复步骤与恢复 owner
- 备份与即将执行的 rollout scope 的对应关系

备份失败、无法读取或无法说明恢复路径时，不能进入 Production Cutover。当前 B1 backup rehearsal PASS 不替代该 gate。

## 11. C7 real capture handling

`REAL_CAPTURE_C7=YES`
`REAL_CAPTURE_C7_DEIDENTIFIED=NO`
`DEIDENTIFIED_FIXTURE=DEFERRED`
`REAL_CAPTURE_REGRESSION=NOT_RUN`

当前没有把真实 C7 原始输出制作成长期 fixture，因为脱敏完成前存在把现场用户名、地址、MAC、序列号或其他敏感信息带入 Git 的风险。该 deferred 不阻塞本阶段“批准进入实现”的决策；Phase 2D-D 若需要 fixture，必须先生成最小、脱敏、标记 `REAL_CAPTURE` 的样本并通过 secret scan。

## 12. Final gate values

```text
SCOPED_ROUTING_DESIGNED=YES
SCOPED_ROLLBACK_DESIGNED=YES
DEFAULT_LEGACY=YES
CAPABILITY_PRIMARY_DESIGNED=YES
LEGACY_FALLBACK_DESIGNED=YES
DOUBLE_REPOSITORY_WRITE_ALLOWED=NO
DATABASE_SCHEMA_CHANGE_REQUIRED=NO
C9_SWITCH_VALIDATION=DEFERRED
C9_AC_USED_AS_SUBSTITUTE=NO
PRODUCTION_BACKUP_REQUIRED=YES
PRODUCTION_BACKUP_EXECUTED=NO
PRODUCTION_CUTOVER=NO

PHASE2D_D_READY=YES
PHASE2D_READY=NO
```

`PHASE2D_D_READY=YES` 仅表示可以开始下一阶段的受控实现；下一阶段仍必须实现并验证上述 routing、fallback、single-writer、rollback、backup 和 monitoring gates。`PHASE2D_READY=NO` 表示尚未达到整体 Phase 2D 完成或生产切换条件。

## 13. Source references

- `docs/dev/interface-discovery-real-device-validation-report.md`
- `docs/dev/interface-discovery-limited-validation-plan.md`
- `docs/dev/interface-discovery-capability-inventory.md`
- `docs/dev/command-capability-design-review.md`
- `docs/dev/interface-discovery-migration-contract.md`
- `docs/dev/interface-discovery-shadow-rehearsal-report.md`
- `src/netconsole/services/device_operation_service.py`
- `src/netconsole/services/device_command_profile_service.py`
- `src/netconsole/services/h3c_collect_service.py`
- `src/netconsole/services/interface_discovery_shadow.py`
- `src/netconsole/repositories/device_fact_repository.py`
- `src/netconsole/core/feature_registry.py`
- `src/netconsole/core/feature_flags.py`
