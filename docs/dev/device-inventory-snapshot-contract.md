# Device Inventory Golden Snapshot Contract

日期：2026-09-04
适用 Operation：`device.inventory.collect`
范围：测试专用 replay normalized snapshot，不是新的生产 DTO 或 API contract。

## 1. 与现有 DTO 的锚定

Replay snapshot 不直接实例化生产 DTO；它保存 Parser 结果的稳定测试投影。Required 字段不能从样例猜测，必须以当前 DTO 定义为边界：

| 当前 DTO | Pydantic Required 字段 | 说明 |
| --- | --- | --- |
| `DeviceFactDTO` | 无；字段均有默认空字符串 | 设备事实允许空值，partial/empty 不伪造身份字段 |
| `DeviceInterfaceDTO` | `name`、`normalized_name`、`category` | 页面接口 DTO 的记录身份和分类字段 |
| `DeviceTransceiverDTO` | `interface_name`、`normalized_interface_name`、`severity` | 页面光模块 DTO 的记录身份和状态字段 |
| `DeviceLldpNeighborDTO` | `local_interface`、`normalized_local_interface` | 页面 LLDP DTO 的本地接口身份字段 |

Replay 的 `interface_name`、`optical_modules[].interface_name` 和 `lldp_neighbors[].local_interface` 是 Parser 投影的稳定身份键，不声称已经是上述页面 DTO；未来映射到页面 DTO 时仍必须补齐该 DTO 的 Required 字段。当前 replay 不改变 DTO。

## 2. Golden Required fields

每个 Golden 顶层必须精确包含以下结构字段，新增字段必须人工审阅并同步 contract：

```text
fixture_id, fixture_type, operation_id, device, parser_contract,
facts, interfaces, optical_modules, lldp_neighbors,
statuses, warning_counts
```

`device` 必须包含 `vendor`、`role`、`platform`、`software_version`、`profile_id`。`facts` 和各 collection record 的字段集合按 H3C/ZTE 当前 replay parser contract 固定；这些字段在快照中结构上存在，但值可以是 `null`，collection 也可以为空。

每个非空接口、光模块和 LLDP record 必须有对应的接口身份字段。身份字段存在不代表其它业务字段成功解析；其余字段保持可空，缺失由 Parser status、空 collection 或 warning count 表达。

## 3. Optional fields and values

当前 snapshot schema 不把“所有字段都有值”当作成功条件：

- `facts` 的型号、序列号、MAC、版本、sysname、uptime 等值可以为空；`DeviceFactDTO` 本身也没有 Pydantic Required 字段。
- interfaces、optical modules、LLDP neighbors 可以为空；各记录的状态、描述、VLAN、DOM、邻居属性等字段可以为 `null`。
- H3C/ZTE 的可选输入 selector 缺失时，相关 status 可以是 `EMPTY`、`MISSING`、`NO_NEIGHBOR`、`PARSE_FAILED` 或 Parser 当前返回的其它明确状态。
- `capabilities` 不属于当前 Parser replay snapshot；未来 Legacy/Profile 等价比较允许单独携带该 normalized DTO section，但新增到 Golden 前必须另行审阅。

## 4. Ignored fields

Golden 禁止保存或比较以下运行态/证据路径字段：

- raw CLI、raw output reference、机器路径；
- `collected_at`、`observed_at`、`timestamp`、`started_at`、`ended_at`；
- execution duration、session ID、collect run UUID、task ID 和 runtime metadata。

这些字段不是 Parser 业务事实；需要保留原始证据时使用生产 Collector 已有的 raw evidence 边界，不把它混入稳定 Golden。

## 5. 验证与更新

`tests/support/device_inventory_snapshot_contract.py` 对每个 Golden 执行结构、厂商字段集合、类型和 Ignored fields 校验。测试失败时不自动更新快照。任何新增/删除字段必须先确认实际 DTO/Parser contract，再人工审阅 Golden 差异并在同一变更中说明原因。
