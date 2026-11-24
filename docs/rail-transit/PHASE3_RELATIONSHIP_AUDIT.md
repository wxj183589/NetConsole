# Phase 3.0 工程关系能力审计

审计基线：Phase 2.5 产品 `4031f88d`，实际实施分支从远端 `codex-A/device-management-phase2` 建立。

## 实际代码矩阵

| 能力 | Schema | Query/Repository | Application/API 写入 | 历史/审计 | Phase 3 动作 |
| --- | --- | --- | --- | --- | --- |
| 设备与车站/节点 | `rail_infra_device_link`、兼容 `devices.station_id` | `RailInfrastructureRepository.read`、`RailTransitBaseDataQueryService.infrastructure` | 无统一关系 API；旧站点绑定写入会修改设备字段 | 无关系事件历史 | 新增 `device_node` 事务写入、解除和历史 |
| 设备与区间服务范围 | 旧表仅有 `section_uid` 可选列，不能表达多区间 | 只读返回可选 section 引用 | 无 | 无 | 新增 `rail_infra_device_section`，允许一设备多区间 |
| AC 服务站点 | `rail_infra_ac_service` | `RailInfrastructureRepository.read` 映射 `ac_service_stations` | 无统一写入 API | 无 | 新增 `ac_service` 写入/解除/历史；不触碰 FIT-AP Current |
| 列车-MR | `rail_infra_train_mr`，CT/CW 生效唯一索引 | Query 投影当前 MR；Repository 有单独 `end_train_mr_assignment` | 旧解除方法绕过 Application Service | 无 | 新增 `train_mr` create/terminate/replace 和审计；保留设备/会话 |
| 车站-建设项目 | `rail_infra_node_project` | Infrastructure Query 显示多项目 | 无统一写入 API | 无 | 新增 `node_project` 写入/解除/历史 |
| 关系历史 | 无 | 无 | 无 | 无 | 新增统一 `rail_infra_relation_history` + audit |
| Revision/冲突 | `schema_metadata.base_data_revision` 及已有基础资料触发器 | BaseData repository revision | 既有 BaseData Service 有 guard/revision | 仅导入审计 | 关系写入复用 guard，新增关系表 revision triggers |
| 缓存同步 | Query 每次读取数据库；运行态按各自事实源 | 没有关系缓存写回 | 无 | 无 | 关系写入只改工程关系和 revision，不改 Ground/MESH/Current/历史原始证据 |
| 删除预检 | 外键 `ON DELETE RESTRICT` | 站点已有删除预检 | 关系写入前拒绝缺失引用 | 关系历史保留 | 关系解除与资产删除分离；删除继续由现有预检负责 |

## 关键边界

- 基础设施表已经存在，Phase 3 不重复创建节点、项目、AC 服务和列车-MR 事实表。
- 设备资产仍由设备管理维护；关系入口位于 `/api/rail-transit/relationships`，不写 `devices.station_id` 代替区间关系。
- AC 工程服务关系与 `ac_device_uuid` 隔离的 FIT-AP Current 是两套事实，不在关系写入中刷新或合并 Current。
- MR 解除只结束 `rail_infra_train_mr` 生效关系，不删除设备、任务、原始日志、MESH 历史、Online MR 会话或报告。
- 运行观测、LLDP、AP Identity 和 Ground/MESH 历史不会被关系维护自动改写。

## 当前缺口与本阶段实现

Phase 2 只读投影没有正式写入口、统一审计和多区间关系表。本分支补充关系 Application Service、服务端 revision/权限/唯一性校验、事务历史、关系审计、当前/历史查询 API 和专项测试；UI 入口在契约和服务端验证稳定后再接入现有三栏工作台。
