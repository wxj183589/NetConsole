# 工程关系写入契约

## 边界与权限

Renderer → `rail_relationship_router` → `RailRelationshipApplicationService` → `RailRelationshipRepository` → Site SQLite 单事务。

查看沿用 `module.rail_base_data`；创建、修改、解除、更换及预览沿用 `capability.rail_base_data.write`、桌面会话校验和 `BaseDataWriteGuard`。AC 资源还要求 `module.ac`。解除关系不授予资产删除能力。客户端 actor 不可信，Router 固定为 `desktop-session`。无新导航、无退役 Feature 恢复。

持久模式中，真实数据与显式副本分别由原有授权开关控制；`isolated_test` 桌面存储模式继续只读。专项测试在 RuntimeMode.TEST 的合成根、persistent 存储和显式副本双开关下运行。Electron 验收使用同样的合成副本和正式权限链，没有绕过 guard。

## 接口

| 接口 | 行为 |
| --- | --- |
| `GET /api/rail-transit/relationships/catalog` | 正式节点、区间、项目、脱敏设备候选及 revision/写权限；不初始化数据库 |
| `GET /api/rail-transit/relationships` | 按 entity_uid/type 查询当前关系；at_time 为业务时点查询 |
| `GET /api/rail-transit/relationships/history` | 按稳定 ID/type 查询事件；page/page_size，最大 200 |
| `POST /api/rail-transit/relationships/preview` | 在单事务校验完整变更与冲突并回滚；不保存任何关系/审计 |
| `POST /api/rail-transit/relationships` | create/update/terminate/replace；保存时再次完整校验 |
| `POST /api/rail-transit/relationships/projects?preview=true` | 项目创建/更名预览；不保存 |
| `POST /api/rail-transit/relationships/projects` | 稳定 project_id 项目维护、历史及请求幂等 |
| `GET /api/rail-transit/relationships/ac-resources` | 仅选定 ac_device_uuid 的 FIT-AP Current；返回工程服务站点，不推断 AP Identity |
| `GET /api/rail-transit/relationships/delete-preflight` | 当前/历史引用检查；始终拒绝在关系接口删除资产或工程对象 |

写请求携带 site_id、类型/action、稳定 source_uid/target_uid、relationship_id（更新/解除/更换）、values、effective_from/to、reason、base_revision、idempotency_key 和 explicit_confirmation。正式保存必须确认；未知属性和过长输入拒绝，不把凭据或动态观测写入审计。

## 基数

| 类型 | source → target | 当前事实 | 关系 ID / 约束 |
| --- | --- | --- | --- |
| device_node | node_uid → device_uuid | rail_infra_device_link | 不透明 JSON 编码 [type,source,target]；一个主要安装节点，已有 devices.station_id 不覆盖 |
| device_section | device_uuid → section_uid | rail_infra_device_section | 同上；一个设备可服务多个正式区间，独立于安装站点 |
| ac_service | ac_device_uuid → node_uid | rail_infra_ac_service | 同上；AC 可服务多个站点，支持原子批量 target_uids |
| train_mr | train_uid → device_uuid | rail_infra_train_mr | assignment_id；同一列车 CT/CW 端位和同一 MR 当前唯一 |
| node_project | station node_uid → project_id | rail_infra_node_project | 不透明复合 ID；一站多项目、一项目多站；status 为关系元数据 |

ID 不允许按冒号拆解；既有 ID 本身可以包含冒号。设备、节点、区间和项目必须来自正式稳定资料。运行观测、模糊名称、LLDP 和主备拓扑都不能生成永久工程身份。

MR 更换只用于同一列车和同一端位：旧关系有效期结束，新 assignment_id 建立；设备、日志、任务、历史会话和报告不删除、不迁移。没有实现未来调度，未来生效时间拒绝；允许补录过去实际生效时间。修改的生效时间不得早于关系原生效时间。

## 事务、冲突与缓存

1. 校验 Feature、会话、授权、确认；读取同 revision 正式候选。
2. Repository `BEGIN IMMEDIATE`；先检查精确幂等重放，再核对数据库 revision 和候选 revision。
3. 校验类型、引用、主要物理归属、MR 端位/设备及有效期重叠；写当前事实。
4. 同事务保存 state、历史事件和审计；失败全部回滚，AC 批量没有部分成功。
5. 事实/历史触发器推进已有 base_data_revision；同事务返回最新 revision 与关系投影。
6. UI 成功重新读取工作台；失败保留草稿。版本冲突必须由用户显式刷新版本并重新预览，不自动覆盖。

幂等键已成功且请求完全相同时，即使 revision 已变化仍返回原结果，不追加事件；同键不同请求返回 RELATION_CONFLICT。相同当前关系重复创建是无变化成功，不产生重复有效关系或历史事件。非精确重放的旧 revision 返回 409 BASE_DATA_REVISION_CONFLICT；不存在/已结束返回 RELATION_NOT_FOUND；引用/唯一性冲突不覆盖旧数据。Feature 关闭使用现有 404，写授权拒绝 403，字段/时间校验 422。

Ground 的 TrainInventorySyncService 已按 base_data_revision 验证缓存，关系事务自动失效旧映射（不等待 TTL）；历史 Heartbeat、Syslog、快 Ping 和 MESH/Online MR 仍使用原身份。未被工程关系接管的另一列车端位保留旧兼容映射；已解除端位不会被名称推断复活。

## 删除边界

此接口只维护关系，不实现对象删除。delete-preflight 返回有效/历史工程引用；外部任务、报告、AP Identity 和会话检查未完成时明确 NOT_VERIFIED，并始终 can_delete=false。调用方不能把该结果当作资产删除许可。

新增历史保护触发器阻止有关系历史的设备、节点、列车和项目被删除；当前关系保留既有 FK RESTRICT。现有基础资料站点/区间删除路径增加有效/历史工程引用检查。无完整外部证据时失败关闭，绝不级联删除历史。设备管理既有显式删除流程及其权限仍独立，关系解除无删除副作用。
