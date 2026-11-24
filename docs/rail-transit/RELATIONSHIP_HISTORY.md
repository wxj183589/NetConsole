# 工程关系历史与审计

`rail_infra_relation_history` 保存每次工程关系 create/update/terminate/replace 的前后快照、稳定关系 ID、source/target、生效/结束时间、原因、操作者、录入时间和 revision。`rail_infra_relation_audit` 记录局点、操作类型和完整请求 payload，便于审计请求与关系事件对应。

业务生效时间（`effective_from/effective_to`）与录入时间（`changed_at`）分开保存。补录历史关系不会迁移旧设备的采集会话、MESH 日志、Heartbeat、Syslog、快 Ping 或分析报告。

历史查询按关系类型、source/target 或稳定关系 ID 返回降序事件；当前查询只读取仍有效的关系。名称变化依赖现有节点名称历史和稳定 `node_uid`，关系事件不复制或覆盖设备资产名称。
