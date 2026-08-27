# FIT-AP LLDP Canonical State Specification

## Scope

本规范只覆盖 FIT-AP LLDP 当前关系与最近变化历史。它不改变 AP Identity、LLDP parser、交换机命令或轨旁 AP 业务投影规则；迁移与写入路径复用现有归一化函数和 AP UUID。

## Resource identity

```text
LLDP_RESOURCE_KEY = ap_uuid
```

`ap_uuid` 是现有 `ap_entities` / FIT-AP AP Identity 链路维护的稳定资源标识。`ac_device_uuid` 不是资源主键，AP MAC 也不是本任务新建的第二套主键。迁移遇到缺失 `ap_uuid` 的 LLDP 记录时，记录为 `UNKNOWN_RESOURCE_IDENTITY`，不得按 AP 名称、模糊 MAC 或单次采集文本猜测归属。

AP MAC 继续使用现有 `normalize_mac` / `normalize_mac_key` 归一化结果作为身份证据和查询索引；它不替代 `ap_uuid`。

## Canonical state

Canonicalization 复用 `netconsole.services.fit_ap_link_info.normalize_lldp_payload()` 与 `normalize_interface_key()`，不重新实现 AP Identity。状态比较字段为：

### STATE_FIELDS

- `local_interface_normalized`
- `neighbor_mac_normalized`（邻居 chassis/MAC identity）
- `neighbor_interface_normalized`
- `neighbor_name`（邻居设备/系统名的规范文本）
- `match_status`（包含 `conflict`、`matched`、`partial`、`unknown` 等现有状态）

`conflict_flag` 由 `match_status == conflict` 投影，并与状态一起比较。状态为空的记录仍分类保存并进入迁移报告，不静默丢弃。

### IDENTITY_FIELDS

- `resource_key` / `ap_uuid`
- `ap_mac_normalized`（身份审计字段，不是替代主键）
- `ac_device_uuid`（来源归属字段）

### METADATA_FIELDS

- `source`
- `lldp_confidence`
- `session_id`
- `collect_run_uuid`
- `raw_log_path`
- `source_revision`
- AP 名称、显示 MAC、邻居显示文本等展示/溯源字段

### NON_CHANGE_FIELDS

- `collected_at`
- `last_seen_at`
- `updated_at`
- `created_at`
- `event_id`、数据库自增 `id`
- `snapshot_id`、导出时间及 profiling 字段

来源变化、采集批次变化和时间变化本身不产生 LLDP history；只有 `STATE_FIELDS` 的 canonical 值发生变化才产生真实变化记录。`source` 和 confidence 在 current 中持续更新，但不会因为来源刷新单独制造历史。

## History semantics

- 首次可确认状态写入 `fit_ap_lldp_current`，不计为一次真实变化，也不单独占用 10 条变化配额。
- 后续 canonical 状态变化写入 `fit_ap_lldp_history`，按 `changed_at DESC, id DESC` 排序。
- 每个 `resource_key` 提交事务后最多保留最近 10 条真实变化；第 11 条写入后立即删除该资源最老变化。
- 连续相同状态只更新 current 的 `last_seen_at` / 来源元数据，不新增 history。
- 过期变化不转存 archive、HistoryStore、备份或隐藏 legacy 表。
- `unknown` / `partial` / `conflict` 是可见业务状态，不等同于 decoder 损坏；只有 payload 无法解码、资源身份无法证明或 schema 不支持时，才进入迁移阻断分类。

## Parity boundary

迁移前后比较 current business projection 时排除时间、生成 ID、profiling 和 source-only metadata；比较字段至少覆盖 AP UUID/MAC、local interface、neighbor MAC/name/interface、match/conflict、站点/交换机/端口投影。
