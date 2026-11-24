# 工程关系写入契约

## API 边界

- `GET /api/rail-transit/relationships`：读取当前有效工程关系。
- `GET /api/rail-transit/relationships/history`：按关系类型或稳定 ID 读取历史事件。
- `POST /api/rail-transit/relationships`：通过 `RailRelationshipApplicationService` 创建、更新、解除或更换关系。

所有写入必须携带 `base_revision` 和 `explicit_confirmation=true`，并通过现有 `BaseDataWriteGuard`。隔离测试模式、Feature 关闭、真实局点未授权或副本未授权均返回明确 403 错误码。

## 关系类型

| 类型 | source | target | 当前表 | 关系 ID |
| --- | --- | --- | --- | --- |
| `node_project` | `node_uid` | `project_id` | `rail_infra_node_project` | `node_uid:project_id` |
| `device_node` | `node_uid` | `device_uuid` | `rail_infra_device_link` | `node_uid:device_uuid` |
| `device_section` | `device_uuid` | `section_uid` | `rail_infra_device_section` | `device_uuid:section_uid` |
| `ac_service` | `ac_device_uuid` | `node_uid` | `rail_infra_ac_service` | `ac_device_uuid:node_uid` |
| `train_mr` | `train_uid` | `device_uuid` | `rail_infra_train_mr` | `assignment_id` |

`train_mr` 的 `position` 只允许 `CT`/`CW`，数据库现有部分唯一索引保证同一列车端位和同一 MR 的当前有效关系不会重复。`replace` 先结束旧关系再建立新关系，旧设备资产和历史会话保持不变。

## 生命周期和事务

1. 校验局点、权限、Feature、确认标记和 `base_revision`。
2. `BEGIN IMMEDIATE`，再次校验引用与当前关系。
3. 执行当前关系写入；唯一性、外键和 MR 角色冲突失败则整笔回滚。
4. 在同一事务写入 `rail_infra_relation_history` 和 `rail_infra_relation_audit`。
5. 关系表触发器推进 `schema_metadata.base_data_revision`。
6. 提交后返回最新 revision 和关系投影。

重复创建返回 `RELATION_ALREADY_EXISTS`；已解除或不存在关系返回 `RELATION_NOT_FOUND`；revision 变化返回 `BASE_DATA_REVISION_CONFLICT`；唯一性或引用冲突返回 `RELATION_CONFLICT`/`RELATION_REFERENCE_MISSING`。

## 数据安全

关系解除不是资产删除。服务不删除设备、采集任务、原始日志、MESH/Online MR 历史或报告；`ON DELETE RESTRICT` 和现有节点删除预检继续保护引用。工程关系变更不刷新 FIT-AP Current，不把动态 LLDP/AP Identity/Ground 观测提升为永久关系。
