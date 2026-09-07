# Device Inventory Legacy/Profile 等价比较契约

日期：2026-09-04
状态：未来迁移 scaffold；不是迁移方案实施，不改变生产 Collector、Operation、Profile、DTO、API 或 DB。

## 1. 比较边界

未来 Legacy Collector 与 Command Profile Collector 只能比较已经通过各自 Parser 归一化的 Device Inventory normalized DTO/result。比较入口是：

```text
Legacy Collector -> existing Parser -> normalized result
Command Profile Collector -> existing Parser -> normalized result
                                         ↓
                              equivalence projection
```

禁止比较 raw CLI、命令字符串、命令顺序或 session 日志来替代业务结果比较。命令/profile 是否等价仍需另行比较 profile binding、命令安全门、证据覆盖和失败语义。

## 2. 必须比较的 normalized sections

`tests/support/device_inventory_equivalence.py` 的 projection 固定比较以下内容：

| Section | 必须比较的语义 |
| --- | --- |
| `device_identity` | vendor、platform、system name、serial number、MAC；缺失值仍需保持一致 |
| `model` | 归一化设备型号 |
| `version` | 归一化软件版本 |
| `interfaces` | 接口身份及当前 Parser 输出的稳定接口字段 |
| `optical_modules` | 光模块身份、DOM/功率和当前 Parser 输出的稳定字段 |
| `neighbors` | LLDP 邻居身份、接口和当前 Parser 输出的稳定字段 |
| `capabilities` | 已确认的 capability 集合；当前 replay 没有 resolver 输出，调用方需显式提供 |

H3C 的 `sysname` 与 ZTE 的 `system_name` 在 projection 中映射为同一比较语义；这只是 normalized result 的字段映射，不修改任何生产 DTO。接口/邻居列表顺序必须由上游 normalized contract 稳定化，比较器不会用 raw CLI 重排或猜测身份。

## 3. 明确忽略的字段

比较器递归忽略以下运行态字段：

- `raw`、`raw_output`、`raw_output_ref`、机器路径；
- `collected_at`、`observed_at`、`timestamp`、`started_at`、`ended_at`；
- `duration_ms`、`execution_duration_ms`、`session_id`、`collect_run_uuid`、`task_id`、`runtime_metadata`。

这些字段不参与 Legacy/Profile 业务等价判断。`model`、`version`、接口/光模块/邻居字段、身份字段和 capabilities 不得因为“实现不同”而加入忽略清单；如果变化，比较必须失败并进入审阅。

## 4. 当前 scaffold 的使用规则

- 当前 replay result 作为一侧输入；未来 Legacy/Profile 各自产生另一侧 normalized result。
- 当前 replay 没有 capability resolver 结果，默认 capabilities 为空；未来比较必须在两侧都显式提供 capability projection 后再判定。
- `compare_normalized_device_inventory()` 只返回结构和值是否相等，不启动连接、不调用 Collector、不写数据库，也不改变生产运行逻辑。
- 比较通过不等于迁移通过。真正迁移还必须单独证明 profile id/version、命令顺序、raw evidence、partial_success、Repository 写入、current/recent/history 和失败语义一致。
- Golden 仍由人工更新；等价比较不能成为自动覆盖 Golden 的入口。
