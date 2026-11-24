# 资产删除安全契约

## 入口与返回

POST `/api/device-management/devices/deletion-preflight`，沿用 module.devices（Router）和 capability.devices.write（动作）及既有桌面会话校验，不新增 Feature。输入 device_uuid、base_revision、source、request_id（均有长度约束）。当前 Site 来自已有 Service，不允许客户端跨局点指定路径。

DeviceManagementWebService → AssetDeletionPreflightService → AssetReferenceRepository（只读 SQLite/元数据）及既有 RailRelationshipRepository（revision/current/history）。返回脱敏设备身份、当前 work_scope_status、当前/历史工程关系数、external_reference_checks、historical_evidence_check、blockers、status、revision、checked_at、expires_at、request_id/source、separate_authorization_required。

`can_delete=false` 恒定；`result_reusable_for_deletion=false`。重复 request_id 重新检查，不复用缓存，不生成 token。expires_at 只表示检查摘要参考期限（30s），没有任何执行接口接受这个结果；过期或伪造结果均不能打开删除。

## 状态

| 状态 | 条件 |
| --- | --- |
| BLOCKED_BY_ACTIVE_RELATION | 存在当前工程关系 |
| BLOCKED_BY_HISTORY_REFERENCE | 存在工程历史 |
| BLOCKED_BY_EXTERNAL_REFERENCE | 精确身份列/会话元数据发现已知外部引用 |
| BLOCKED_BY_UNVERIFIED_SOURCE | 未证明完整历史覆盖，即便所有有限查询无命中 |
| BLOCKED_BY_REVISION_CONFLICT | 请求 revision 过旧或扫描前后 revision 变化 |
| PREFLIGHT_FAILED | 资产缺失、基础检查异常、迁移缺失或预算耗尽 |

不返回 READY_FOR_SEPARATE_AUTHORIZATION，因为档案/报告/MAC/SN/旧名称和 JSON 引用仍未穷尽。VERIFIED 仅指明示查询范围已执行，不能解释为该领域所有历史不存在；已发现的证据也不能被未知项掩盖。整体完整性始终 NOT_VERIFIED。

## 失败关闭

Site 身份与数据库路径先检查项目数据根包含关系和 Reparse Point；SQLite 以 mode=ro 连接，缺失源不创建文件。扫描 Site/tasks/Ground/MESH 索引的精确 device_uuid/ac_device_uuid/mr_device_uuid/mr_device_id/device_id/source_uid/target_uid 列；仅返回表名、匹配数，不返回凭据/原始 payload。整数 device_id 可能是旧外键候选而非 UUID，宁可阻断，不自动推断身份。

Online MR 元数据限深度 3、500 文件、单文件 64KiB；不读取 raw/zip/报告内容，不跟随链接。默认外部扫描协作预算 250ms，SQLite progress handler + 100ms busy timeout；不是操作系统硬实时超时保证，文件系统 IO 可延迟，但迟到结果仍不能用于删除。初始身份/revision 读取不属于外部扫描预算；预算耗尽或源异常标 NOT_VERIFIED/PREFLIGHT_FAILED。

base_data_revision 用于资产/工程事实，不是所有运行库的统一版本；跨库检查不是全局原子快照。因此 preflight 只是诊断，不是可重放的授权。并发变更拒绝，外部索引、压缩归档或不可读源都不能被视为空。

## 执行保护

- issue_delete_token 与 delete_devices 固定抛出 ASSET_DELETION_NOT_AUTHORIZED，HTTP 409，旧/伪造/过期 token 均无效。
- DeviceRepository.delete 与非空 delete_many_by_uuid 同样拒绝；legacy device_crud Job 也无法通过 Repository 绕过。
- 没有新增 Schema、数据库触发器或数据迁移。原工程 FK/history triggers 继续生效；禁止靠直接 SQL 或外部维护工具绕过。
- 本轮不修改 Renderer；旧删除按钮会收到服务端明确拒绝，没有虚假成功。

完整删除能力需要未来独立保留政策、外部证据索引与显式授权任务；本次不会开放。
