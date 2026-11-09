# Ground Unattended R2 数据库迁移

`ground_unattended_syslog_config_audits` 采用 additive migration 增加：

- `managed_by_netconsole`
- `created_by_netconsole`
- `managed_target_ip`
- `managed_target_port`
- `ownership_audit_id`
- `ownership_status`
- `revoked_at`

旧行默认 `managed_by_netconsole=0`、`created_by_netconsole=0`、`ownership_status=UNKNOWN`。不删除历史审计、不删除 Raw 文件、不重建车辆库存、不改变任务 ID。迁移测试验证删除字段后的旧表可以由 Repository 重新补齐字段并安全读取。

本阶段未对 Production 或真实开发数据执行迁移。
