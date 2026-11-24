# Phase 3.6 删除安全审计结论

状态 PARTIAL：已知资产删除漏洞已封闭，外部历史证据完整性仍 NOT_VERIFIED，资产删除禁止。

主要问题：旧设备管理 token 仅保护 scope/TTL，没有外部历史引用校验；DeviceRepository 单删/批删可直接调用（legacy Job 已有调用）。即使没有工程关系，设备仍可能被任务、AP Identity、Ground、MESH、Online MR、导出文件引用。

修复：物理删除 token 和执行均固定拒绝；Repository 两方法同样拒绝。新增只读 preflight 复用 Site 工程事实和 revision，扫描已知精确列/有界会话元数据；未知源、异常、超时、版本冲突明确阻断。无 Schema/迁移、无真实资产删除。

证据与使用见 [删除契约](ASSET_DELETION_SAFETY.md)、[引用矩阵](EXTERNAL_REFERENCE_AUDIT.md)、[生命周期](ASSET_LIFECYCLE.md) 及 [定向回归](PHASE3_7_REGRESSION.md)。用户明确指定的三份 AUDIT 输出路径仅作精确文档门禁例外，未放宽目录规则。

工程解除保留设备和其他关系；MR 更换保留旧会话；AC 服务解除保留 Current；排除当前调试保留报告。若外部历史许可仍未验证，即便所有定向通过也不能宣称资产可安全删除。

PRODUCTION_DATA_MODIFIED=0
DEV_REAL_DATA_MODIFIED=0
REAL_DEVICE_MODIFIED=0
DATABASES_REMOVED=0
MAINTENANCE_AUTHORIZED=NO
