# TRACKSIDE AP 数据库哈希一致性报告

- 最终状态：`LOCAL_PASS_DATABASE_VERIFIED`
- 产品 HEAD：`3f110cf85ec289b8b4d986c8dee40fe646de9d44`
- Site：`hzdt-09`
- 数据库：`D:\NetConsoleData-dev\sites\hzdt-09\db\devices.db`

## 哈希证据

| 时点 | 主数据库 SHA-256 | WAL | 说明 |
|---|---|---:|---|
| 上一轮 GUI 前备份报告记录 | `e372ddfad4cd8026f514ca2da70e5cf7c811ae8f81617739533a3aa35389f3ef` | 0 bytes | 491条数据已在 GUI 验收开始前存在 |
| 上一轮 GUI 后报告记录 | `e372ddfad4cd8026f514ca2da70e5cf7c811ae8f81617739533a3aa35389f3ef` | 未见非零 WAL | GUI 结果为491 unchanged |
| 本轮只读复核 | `e372ddfad4cd8026f514ca2da70e5cf7c811ae8f81617739533a3aa35389f3ef` | 0 bytes | `integrity_check=ok` |

SQLite Backup API 备份文件哈希为 `4ebd1f72793826b281372669678fa87b441f48b145a9b8f06dbaabf40a08020e`。备份哈希与源文件哈希不同是正常的：Backup API 生成一致性数据库副本，不保证字节级复制主文件布局。

## 结论

上一轮 GUI 的“导入”是对已经存在的491条记录进行预览和幂等比较，实际结果为：`491 valid`、`491 unchanged`、`0新增`、`0更新`、`0冲突`、`0无效`。因此保存按钮没有产生 AP 数据写事务，重启也只是重新读取同一个数据库。491条 AP 的首次写入发生在本轮 GUI 验收建立哈希基线之前；这解释了主数据库前后 SHA-256 完全一致。

WAL 假设不成立：上一轮备份记录的 WAL 为0 bytes，本轮当前 WAL 仍为0 bytes，且日志中的数据库启动维护明确记录 `checkpoint=False`。没有证据表明写入被隐藏在非零 WAL 中，也没有发现 GUI 使用另一份 AP 数据库。

Backend 日志还记录了同一实际路径和 AP 数量：`TRACKSIDE_AP_PLAN.CONTEXT_LOADED ... site_id=hzdt-09 ... aps=491`，随后 `REPOSITORY_LOADED ... database_path=D:\NetConsoleData-dev\sites\hzdt-09\db\devices.db`。

因此本轮状态不是 `HASH_CONSISTENCY_UNRESOLVED`：哈希一致是“GUI 阶段无变化”的结果，不是“没有491条数据”的证据。

## 风险边界

只读 WAL 访问可能创建或更新 SQLite `-shm` 协调文件。本轮未执行任何业务写入，未执行 checkpoint、VACUUM、迁移或清理；主数据库内容哈希保持一致。
