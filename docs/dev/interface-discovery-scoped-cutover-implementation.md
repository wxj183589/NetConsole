# Interface Discovery Scoped Cutover Implementation

> 日期：2026-09-07
> 阶段：Phase 2D-D
> 状态：实现完成，生产激活关闭

本文记录 Phase 2D-D 的最小软件实现。它不批准或执行 Production Cutover；当前生产默认仍使用 Legacy。

相关决策：[interface-discovery-cutover-decision.md](./interface-discovery-cutover-decision.md)

## 1. 实现范围

唯一实现范围为：

```text
vendor=H3C
role=switch
comware_major=7
capability=interface.discovery
```

以下范围没有进入 Capability route，继续 Legacy：Comware 9 Switch、wireless_controller、mobile_router、ZTE、unknown vendor/role/version、LLDP、Optical、Trackside、FIT-AP、MR 和 MESH。

没有新增 Operation ID，没有修改 `resources/device_command_profiles.json`，没有新增 public API、UI 开关或全局 Feature Flag。

## 2. Current execution seam

实际调用链保持不变：

```text
DeviceDetailApplicationService.refresh
  -> DeviceOperationService.start
  -> LocalProcessAdapter / device_detail_collect
  -> run_device_inventory_refresh
  -> collect_h3c_device_details
  -> existing H3C parser / DeviceInterfaceDTO projection
  -> DeviceFactRepository.replace_device_interfaces
```

Phase 2D-D 增加的路由判断位于 `DeviceOperationService._plan` 和 worker 的 Profile re-check 之后。Collector 在收到 Capability route 后还会用本次冻结的 platform facts 和已解析 Profile 再校验一次 envelope；缺少 facts 时直接 Legacy。

Shadow Runner 仍是独立的 observe-only 工具，不是 Capability Primary 的生产输入，也不调用 Collector 或 Repository writer。

## 3. Migration envelope matcher

实现文件：`src/netconsole/services/interface_discovery_routing.py`

`evaluate_interface_discovery_route()` 只返回 `LEGACY` 或 `CAPABILITY_PRIMARY`。判断顺序为：

1. Operation 必须是现有 `device.inventory.collect`，能力必须是内部 selector `interface.discovery`。
2. vendor、role、platform 必须分别为 H3C、switch、Comware。
3. software version 必须存在，并由已有可信 fact 解析为 `V7`；报告的 `software_major` 必须与版本文本一致。
4. version fact 必须来自 `device_fact.software_version` 且 confidence 为 `high`。
5. Profile 必须是 read-only inventory Profile，并包含现有 `inventory.interfaces` selector。
6. 设备 UUID 必须在内部 scoped rollout policy 的精确 allowlist 中。

任何缺失、过期、malformed、未知或不可信条件都会返回 Legacy。不会根据型号、IP、站点或设备名称推测版本。

实际 policy 文件路径为数据根下的：

```text
runtime/interface_discovery_rollout.json
```

文件不存在时为默认关闭。文件格式是受限的内部 policy，不是用户配置：`schema_version=1`、`mode=disabled|scoped`、`device_uuids=[...]`。未知字段、空 scoped allowlist、重复/非法目标或 JSON 错误均 fail-closed 到 Legacy。

## 4. Routing and default behavior

`DeviceOperationService` 在计划阶段记录路由 decision，worker 在正式执行前重新加载 policy 并重新评估。这样 policy 归零或关闭后，后续任务无需重启即可回到 Legacy；worker 不信任过期的 Capability 选择。

默认行为：

```text
policy missing / invalid / disabled
  -> LEGACY

H3C + switch + trusted V7 + interface.discovery
  + exact scoped activation
  -> CAPABILITY_PRIMARY
```

当前生产没有该 policy 文件或激活目标，因此：

```text
DEFAULT_PRODUCTION_PATH=LEGACY
PRODUCTION_CAPABILITY_PRIMARY_ENABLED=NO
```

## 5. Capability Primary and Legacy fallback

实现位于现有 `h3c_collect_service.py` 的 `inventory.interfaces` selector 边界：

1. Capability Primary 复用现有 Profile command、Command Guard、SSH connection、`display interface` 和 H3C parser。
2. Capability candidate 先在内存中完成 parser/contract validation；非空、接口名存在且 identity 不重复才算有效。
3. Capability 有效时，Legacy interface command 不再执行，最终使用 Capability candidate。
4. Capability 执行错误、timeout、空结果、重复/非法接口、parser/contract mismatch 时，丢弃 candidate，才执行一次 Legacy interface selector。
5. Legacy fallback 的有效结果继续进入现有 `_parse_and_write()`；Capability 本身不调用 Repository。
6. Repository 持久化失败时沿用既有 failure semantics，不为了掩盖失败再次采集或再次写入。

Capability 与 Legacy 共用一个已解析的 `DeviceInterfaceDTO`/normalized projection 和现有 `replace_device_interfaces` writer；没有第二套 Collector、Parser、DTO 或 Repository。

## 6. Single-writer guarantee

接口 selector 的结果选择发生在 Repository mutation 之前：

```text
Capability PASS
  -> selected Capability DTO
  -> one existing interface writer

Capability FAIL / invalid
  -> discard Capability candidate
  -> Legacy DTO
  -> one existing interface writer
```

因此保证：

```text
CAPABILITY_PASS_REPOSITORY_WRITES=1
CAPABILITY_FAIL_LEGACY_PASS_REPOSITORY_WRITES=1
DOUBLE_WRITE_ALLOWED=NO
```

Current、Recent10、bounded history、revision、empty snapshot protection 和 unchanged suppression 均继续由现有 Repository contract 负责。没有增加 source 列、migration 列、shadow revision 或新表。

## 7. Rollback seam

rollback 通过动态读取 scoped policy 实现：将 `mode` 设为 `disabled` 且清空目标 allowlist，后续计划/worker 都回到 Legacy，不需要 Git revert、数据库 restore、history rebuild 或 process restart。

必须立即归零该 scope 并停止扩大 wave 的条件包括：

- Repository unexpected mutation 或 writer 调用超过一次
- DTO semantic mismatch、contract mismatch 或 interface count anomaly
- Capability failure 后 Legacy fallback failure
- task failure/timeout 明显上升或用户可见回归
- version、role、Profile identity 无法确认
- Command Guard violation 或设备配置变化

rollback 只影响 H3C Comware 7 Switch 的 `interface.discovery`，不影响其他设备类型、Capability 或业务域。

## 8. Audit and observability

复用现有 structured application log，使用不含凭据、IP、MAC、CLI 原文的安全摘要：

- `INTERFACE_DISCOVERY_ROUTE`
- `INTERFACE_DISCOVERY_CAPABILITY_SUCCESS`
- `INTERFACE_DISCOVERY_CAPABILITY_FAILED`
- `INTERFACE_DISCOVERY_FALLBACK_TO_LEGACY`
- `INTERFACE_DISCOVERY_ROUTE_REJECTED`

decision reason 可区分 `LEGACY_DEFAULT`、`LEGACY_OUT_OF_SCOPE_*`、`LEGACY_UNKNOWN_VERSION`、`LEGACY_POLICY_FAILURE`、`CAPABILITY_PRIMARY` 和 fallback 失败原因。后续监控至少统计 Capability success、fallback、error、contract mismatch、interface count anomaly 和 Repository effect anomaly。

## 9. Test coverage

新增 `tests/test_interface_discovery_routing.py`，覆盖：

- C7 envelope eligible；C9、AC、MR、ZTE、unknown vendor/role/version Legacy
- actual `Version 7.1.070 Release 7756P10` major parsing
- missing/invalid policy fail-closed
- 默认 Legacy
- Capability PASS 且 Legacy interface command 不执行
- error、timeout、empty、invalid、duplicate/contract mismatch fallback
- Capability PASS 和 fallback 各自单次 interface Repository write
- C9/AC/MR/ZTE 在 C7 scoped activation 下仍 Legacy

现有 Shadow、B1 rehearsal、Replay、Repository 和 Device Inventory tests 保持兼容；未修改 Replay Golden 或 Parser expected。

## 10. Remaining production gates

本阶段完成的是软件能力，不是生产激活。仍需下一阶段独立完成：

1. 当前有效 Wave 0 目标复核与 owner sign-off。
2. 正式 Production pre-switch backup、manifest、可读性和恢复演练。
3. 受控 maintenance window 批准。
4. Wave 0 单台、Wave 1 少量同角色同版本、Wave 2 C7 Switch 范围扩展。
5. 每波观察、hard-stop、rollback 和 Current/Recent10/history/revision 对照。

```text
PHASE2D_D_IMPLEMENTATION=PASS
PRODUCTION_CUTOVER_EXECUTED=NO
PRODUCTION_ACTIVATION_DEFAULT=OFF
PRODUCTION_BACKUP_REQUIRED=YES
MAINTENANCE_WINDOW_REQUIRED=YES
PHASE2D_E_READY=NO
```
