# P7.3-F Authority / Rollback 定向安全补齐

## 目的

本变更从最新 `main` 建立最小独立实现，补齐 PR #78 审计确认的 HTTP
数据库维护、AC extension rollback、rail-transit base-data rollback 的
authority gap。它是 PR #78 的功能替代候选，不合并、修改或关闭 PR #78，
也不恢复 PR #78 的旧 31 文件重构。

## Authority 流程

```text
HTTP submit
  -> canonical site + operation token + immutable descriptor
  -> queued worker materialize
  -> worker revalidate site/profile/backup/audit and SQLite observation
  -> callback immediately before each mutator
  -> existing service/coordinator transaction and journal
```

请求阶段只创建可验证的 authority plan；真正执行前由 worker 重新绑定当前
site、数据库/profile、备份 descriptor 或 rollback audit。每一个备份、校验、
删除、恢复、升级和 derived-data repair 的 mutator 都在调用前再次校验，避免
提交阶段与执行阶段之间的路径、站点、WAL 或 descriptor 变化被绕过。

## 覆盖范围

| Consumer | 覆盖内容 | 状态 |
| --- | --- | --- |
| HTTP database upgrade | single/batch upgrade，worker authority，site/profile binding，pre-mutation revalidation | `COVERED_PENDING_MAIN_MERGE` |
| HTTP database backup | create、validate、restore、delete、batch delete，backup descriptor/path binding | `COVERED_PENDING_MAIN_MERGE` |
| HTTP AC extension rollback | operation-specific rollback token、audit/site/type binding | `COVERED_PENDING_MAIN_MERGE` |
| HTTP rail base-data rollback | operation-specific rollback token、operation/site/type binding | `COVERED_PENDING_MAIN_MERGE` |
| Worker race boundary | submit-time plan 与 worker-time state 不一致时 fail closed | `COVERED_PENDING_MAIN_MERGE` |
| Startup DB initialization/recovery | 自动启动 writer、journal/staging recovery | `OUT_OF_SCOPE_REMAINING` |
| Automatic task-event retention | 自动删除 terminal task events | `OUT_OF_SCOPE_REMAINING` |

## 安全边界

- 生产数据写入仍受现有 `DataRoot` process gate、canonical site scope 和
  operation-specific token 共同约束。
- 备份恢复必须绑定有效 backup manifest、受控路径和当前 site；无效 backup
  可用于只读校验或受控删除，但不能用于恢复。
- AC/base-data rollback 在持有维护锁前拒绝错误 operation token、错误 site
  或错误 audit/operation type。
- 不访问 `D:\NetConsoleData` 或 `D:\NetConsoleData-dev`，不连接真实设备、
  WPS、GUI 安装环境，不执行 release/tag/installer。

## 验证

新增回归覆盖 submit-to-worker 目标变化拒绝、worker 目标篡改拒绝、backup
scope/path 分隔符篡改拒绝、以及 rollback operation token 隔离；Renderer API
测试验证三类 rollback/database token 会随请求传递。完整证据和 PR 编号记录在
Workspace diagnostic report 中。
