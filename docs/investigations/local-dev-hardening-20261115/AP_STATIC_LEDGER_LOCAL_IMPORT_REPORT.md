# AP 静态台账本地隔离导入报告

状态：`PASS`（隔离 Site 正式导入链路）；现场设备验证：`FIELD_VALIDATION_PENDING`。

## 正式导入证据

- 正式 Service：`RailTransitImportPreviewService` + `RailTransitBaseDataImportService`。
- 写入保护：`BaseDataWriteGuard`，使用测试授权的隔离副本。
- 隔离数据根：`D:\study\NetConsole-Workspace\test-data\NetConsole\local-dev-hardening-import-20261116c`。
- 证据摘要：`D:\study\NetConsole-Workspace\diagnostic\local-dev-hardening-20261115\import-apply-summary.json`。
- 正式 Apply 使用仅含标准台账 sheet 的工作簿；包含审计 sheet 的工作簿只用于审计，不直接 Apply。

## 结果

| 步骤 | 结果 |
| --- | --- |
| 导入预览 | 422 行，422 有效，0 错误，1266 警告 |
| 首次 Apply | `APPLIED`，创建 422，更新 0 |
| 首次落库查询 | 425 条（含 fixture 原有 3 条） |
| 重新打开/查询 | 总数 425，首条静态记录仍存在 |
| 重复 Apply | `APPLIED`，创建 0，更新 0，不变 422 |
| 重复 Apply 后回滚 | `ROLLED_BACK`，仍为 425 |
| 首次 Apply 回滚 | `ROLLED_BACK`，恢复为原有 3 条 |

重复导入没有产生重复 AP；回滚没有删除 fixture 原有记录。查询使用正式 Repository/Query Service，未用直接 INSERT 冒充导入。

## 持久性边界

隔离数据库重新打开后的查询证明静态记录持久化。AC 离线、LLDP 未更新和现场长期运行不在本地无设备环境中宣称通过；这些属于待执行的现场/运行态验证。静态记录本身不依赖一次新的 AC 查询才能显示。
