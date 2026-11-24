# Phase 3.0 工程关系能力审计

审计基线：Phase 2.5 产品 `4031f88d`，实际实施分支从远端 `codex-A/device-management-phase2` 建立。

## 实际代码矩阵

| 能力 | Schema | Query/Repository | Application/API 写入 | 历史/审计 | Phase 3 动作 |
| --- | --- | --- | --- | --- | --- |
| 设备与车站/节点 | `rail_infra_device_link`、兼容 `devices.station_id` | `RailInfrastructureRepository.read`、`RailTransitBaseDataQueryService.infrastructure` | 无统一关系 API；旧站点绑定写入会修改设备字段 | 无关系事件历史 | 新增 `device_node` 事务写入、解除和历史 |
| 设备与区间服务范围 | 旧表仅有 `section_uid` 可选列，不能表达多区间 | 只读返回可选 section 引用 | 无 | 无 | 新增 `rail_infra_device_section`，允许一设备多区间 |
| AC 服务站点 | `rail_infra_ac_service` | `RailInfrastructureRepository.read` 映射 `ac_service_stations` | 无统一写入 API | 无 | 新增 `ac_service` 写入/解除/历史；不触碰 FIT-AP Current |
| 列车-MR | `rail_infra_train_mr`，CT/CW 生效唯一索引 | 基础设施树投影当前 MR，但基础资料/Ground 仍依赖旧 reconciliation；Repository 有单独 `end_train_mr_assignment` | 旧解除方法绕过 Application Service | 无 | 新增 `train_mr` create/terminate/replace 和审计；保留设备/会话 |
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

## Change Impact / Consumer Audit

风险 L4（工程 Schema 迁移），共享契约为 Site 稳定身份、基础资料 revision、基础设施/设备详情 DTO、当前 MR 与历史会话边界。SQL 仅进入 Repository/Core，Application Service 不直接 SQL；新增四表登记 storage registry，专项测试的 SQL 只登记 TEST_ONLY。用户指定本审计路径，因此 docs guard 仅增加该精确路径，不放宽全局文档规则。

| 消费者 | 写入/读取/缓存/展示/导出影响 | 验证 |
| --- | --- | --- |
| 基础设施与设备详情 | 读取主要安装节点、多区间服务、项目和逐 AC 服务；设备详情保持只读 | infrastructure、device_detail_web_api、Renderer 交互及 Electron |
| Ground | 当前 MR 由正式 assignment 优先，旧端位兼容不复活；缓存按 revision 更新；不操作运行任务/归档 | 新增 cache/history 集成测试、inventory/heartbeat/quick_ping 回归 |
| AC/FIT-AP/AP Identity | 工程服务与 AC Current 分离；资源查询严格 ac_device_uuid，不按站点合并身份 | 原子 batch、Current 指纹、既有身份/AC/轨旁套件 |
| Trackside 页面/导出 | 工程 revision 变化进入原快照一致性检测；不重建 AP Identity/LLDP/光衰 | 原业务快照/导出/规划 consumer suites |
| Wireless/MESH/Online MR | 更新当前工程映射；历史 session/raw/report 不改写，查询独立 | 历史会话内容指纹、原模块回归与 Full Gate |
| 旧 Schema/权限/初始化 | 1→2 增量事务；GET 只读；Feature+session+guard | 故障注入、重复迁移、API 拒绝、架构 12 项 |

并行状态：Phase 1 `907183a4`、Phase 2 `4031f88d` 与主 checkout 均保留，本任务独立 Worktree。远端 main 已前进到 `12b92a71`；按用户冻结的 Phase 2 基线实施，没有擅自合并不同范围主线修改。最终分支 Gate 使用用户指定 907183a4 比较基线；未来合入 main 后仍需在真实合并提交复跑 consumer suites。

真实设备、生产迁移、现场采集与安装包未纳入本次自动化成功声明。资产删除需要其他业务证据完整预检，关系接口始终不授予删除许可。
