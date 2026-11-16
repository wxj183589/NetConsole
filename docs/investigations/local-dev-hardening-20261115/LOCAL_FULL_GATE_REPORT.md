# NetConsole 本地完整门禁报告

总体状态：`LOCAL_PARTIAL`

现场状态：`FIELD_VALIDATION_PENDING`

本轮没有打包 Installer/Portable，没有连接现场设备，没有修改 `D:\NetConsoleData` 或 `D:\NetConsoleData-dev`。

## 已完成

- LLDP 权威分类、待确认证据、AC-only 和冲突审计：完成。
- 真实历史 Excel 通过正式导入 Service 在隔离 Site Apply、重启查询、重复导入和回滚：完成。
- Quick Ping 批量 SQL 投影与持久化内部字段 HTTP 过滤：完成。
- Syslog `QUEUED`/共享任务状态不兼容导致的 HTTP 500：修复并通过真实路由回归。
- Python 专项：212 passed、1 skipped；数据库/迁移/基础资料专项：55 passed。
- Python 全量（仓库锁定 `.venv`、当前 worktree `PYTHONPATH`）：5537 passed、2 skipped；完整过程中最早的 2 个架构断言发生在架构配置补录前，补录后架构定向回归 19 passed，原 2 个断言单独回归 2 passed。
- Ruff：PASS；compileall：PASS；架构门禁：12/12 PASS。
- Renderer：1537 passed；Renderer typecheck/build：PASS。
- Electron：314 passed；Electron typecheck、main/preload build：PASS。
- 隔离 Electron smoke：PASS，真实 Electron 进程启动并正常退出。
- `git diff --check`：PASS。

## 部分完成或待补

- Ground SQL 深度画像当前覆盖 Inventory、Heartbeat、Quick Ping、Raw Files；Syslog 写事务/队列和 Job Center SQL 尚未纳入同一深度画像，报告标为 PARTIAL。
- GUI 隔离启动 smoke 通过，但交互式人工页面、窗口尺寸和筛选操作没有完成，不能报告 GUI 全部 PASS。
- 无现场 AC、交换机、MR，因此设备命令、实际 Syslog 配置、长期无人值守和现场网络行为保持 `FIELD_VALIDATION_PENDING`。

## 关键证据

- 分类审计：同目录 `AP_LLDP_CLASSIFICATION_AUDIT.md`。
- 隔离 Apply：同目录 `AP_STATIC_LEDGER_LOCAL_IMPORT_REPORT.md`。
- HTTP 画像：`D:\study\NetConsole-Workspace\diagnostic\local-dev-hardening-20261115\http-api-performance.json`。
- SQL 画像：`D:\study\NetConsole-Workspace\diagnostic\local-dev-hardening-20261115\sql-profile-final\metrics.json`。
