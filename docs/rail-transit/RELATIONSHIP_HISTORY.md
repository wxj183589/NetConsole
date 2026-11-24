# 工程关系历史与审计

`rail_infra_relation_history` 按事件保存类型、不透明关系 ID、源/目标稳定 ID、前后快照、业务有效期、原因、actor、录入时间和 revision。`rail_infra_relation_audit` 以幂等键保存经 DTO 约束的请求、哈希和响应；一次批量请求可对应多个历史事件。`rail_infra_relation_state` 只保存当前生命周期元数据；正式事实表继续承担关系基数和外键。

## 时间语义

- effective_from：真实业务生效时间；省略为本次事务时间，允许过去时间补录。
- effective_to：解除/更换的业务结束时间；区间左闭右开。
- created_at / changed_at / updated_at：录入与修正时间，和业务时间分开。
- update：在指定业务时间变更属性；前一属性版本在该时间结束。同一生效起点的后续录入视为资料修正，历史事件仍保留原快照。
- replace：旧 MR 产生 terminate 事件，新 MR 产生 replace 事件，两事件在同事务，切换时刻无重叠。
- 再次关联同一复合关系 ID：保留上一有效期，新的 effective_from 形成新生命周期，不覆盖历史。

`GET relationships?at_time=...` 依据业务有效期重建当时关系；事件接口回答谁在什么录入时间修正了什么。当前未提供“在某录入时刻所知道的信息”的双时态查询，也未提供未来调度。Phase 1 MR 的历史有效期继续从原事实行读取；Phase 1 其他关系没有历史事件，不虚构其建立时间。

事件保存当次可用源/目标名称快照；稳定 ID 是身份依据。项目/车站更名不改变关系 ID。旧版无名称快照时保留稳定 ID，显示端可查现名，不能冒充历史名称。

## 历史业务证据

关系操作只写 Site 工程表，不写任务库、Ground 归档、MESH 原始日志/分析库、Online MR 会话、报告、FIT-AP Current 或 AP Identity。当前工程映射按 revision 更新，历史会话按原设备/会话身份独立读取；关系查询失败也不阻断历史会话读取。

关系历史只在本次事务完成前回填同事务最终 revision，提交后不改写已有事件。解除不是物理删除；存在关系历史时，数据库触发器保护相关资产与工程对象。

## 迁移

工程 Schema 从 1 升为 2，新增 device_section、relation_history、relation_audit、relation_state 四表，复用其余九表。正式入口为 Database.initialize 的 default 初始化/维护流程；既有库在 BEGIN IMMEDIATE 内增量升级并执行 foreign_key_check/integrity_check，异常整体回滚。production_safe 和普通 GET 不自动升级工程 Schema；缺失新表的关系 API 返回 RELATION_MIGRATION_REQUIRED。Phase 1 只读基础设施投影仍可读取既有九表。

专项测试覆盖新库、Phase 1 升级、重复执行、数据量不变、故障注入回滚、完整性、并发、预览回滚、历史时点、MR 更换和删除保护。本次只升级合成测试库，没有重建或修改真实开发/生产根。
