# 运行日志发布就绪审计（2026-08-10）

## 范围与结论

本轮只完成运行日志专题的 hardening 收尾，不重构既有日志目录、Electron 异步写入链路或 Python logger 架构。策略唯一事实源仍为 `src/netconsole/resources/log_policy.json`；Electron 与 Python 都从该资源读取容量、保留期和 rotation retry 配置。

本审计覆盖 Python rotation、运行日志管理页面、历史日志清理边界、冻结数据库迁移和最新 Python 基线。所有测试数据均位于 `D:\NetConsoleTestData\<run-id>` 或 pytest 临时目录；未读取、删除或修改现场 `D:\NetConsoleData` 与其中的历史 Electron 日志。

## Python Rotation

- rotation 失败状态记录连续失败次数、首次/最近失败时间和下次 retry 时间；退避序列为 30、60、120、300 秒。
- 在退避窗口内继续写 active `app.log`，不重复执行 rename；rotation 诊断只写受限 stderr，避免递归写回 app.log。
- 后续 rotation 成功时仅输出一次 `APP_LOG_ROTATION_RECOVERED`。
- 故障注入覆盖 EBUSY 下 1,000 次写入调用，验证 backoff 生效、app.log 保持可写和恢复后可正常 rolling。
- 三进程并发写入测试验证总行数完整、rolling 文件名称不冲突，写入路径按次打开以避免 stale handle。

## 日志管理与清理边界

- `GET /api/system-maintenance/logs/summary` 统一返回日志目录、总量、protected/unknown/candidate 字节和文件数、容量上限、目标水位及保留期；Renderer 不自行扫描文件系统。
- 系统维护页展示运行日志容量并提供“打开日志目录”和“清理历史日志”。清理请求走既有 Job Center、`AppAutoCleanupService` 与 `LogHousekeeper` 白名单，前端不执行 glob、unlink 或 delete。
- `manual_history_cleanup` 与自动 cleanup 语义分离：前者可清理尚未超过 retention 的已轮转 `electron-*.log`、`app-*.log` 和明确安全的历史 WPS/诊断文件；自动清理仍遵从 retention 与容量水位。
- 永久保护 active `electron.log`、`app.log`、`database_upgrade_audit.jsonl`、`startup_error.log`、`faulthandler.log`、unknown、symlink、raw/artifact、数据库和采集结果。数据库升级审计不会计入可清理日志。
- 文件占用导致的单文件删除失败只记录并跳过，不使整个清理任务失败。

## Frozen Migration

冻结 smoke fixture 模拟的是历史 schema：`ac_fit_ap_resources` 表存在但为空，且缺少身份字段。根因不是日志策略，而是 schema trigger 在完整建表前需要 `ac_device_uuid` 与 `ap_uuid`。

- 空旧表：启动前受控 drop/recreate 当前 schema，随后按正常 schema 脚本完成迁移。
- 非空旧表：抛出 `DatabaseSchemaMismatchError`，保持原表和记录，拒绝无损性无法证明的迁移。
- 源码层迁移正反测试已通过；冻结 package smoke 的结果在本轮干净发布构建后补充。

## 验证记录

| 验证 | 结果 |
| --- | --- |
| 定向 Python 日志、Housekeeper、系统维护与 Online MR 回归 | 62 passed, 1 warning |
| Python EBUSY rotation 与多进程写入 | passed |
| Frozen 旧库迁移正反单测与静态迁移 guard | 3 passed |
| 改动范围 Ruff | passed |
| Python `compileall` | passed |
| 架构 guard | 9/9 passed |
| Web 日志页面定向测试 | 11 passed |
| Web production build | passed |
| Electron typecheck | passed |
| Electron test | 253 passed (32 files) |
| 完整 pytest（合并最新 main 后按六段运行） | 3852 passed, 2 skipped, 0 failed |

全量 pytest 初次以单命令运行时受 10 分钟终端上限终止，未返回测试结论；随后按文件首字母和测试子目录完整重跑，以上汇总为最终有效基线。

## 发布构建与安装器

- 提交 `a7d112e94d565dc6f993d7cc4e34ab49d877d58a` 推送到 `github/codex/log-release-readiness` 后，PyInstaller release、Web production build、依赖闭包（71 distributions）、源工具 smoke 和受管 Backend packaged smoke 均通过。
- `win-unpacked` package smoke 通过：frozen `log_policy.json`、时区资源、旧设备数据库迁移/list HTTP 200、Ground 状态 HTTP 200、Worker 中文协议、MESH 幂等性、重复文件名、Qt 残留、NOTICE/SBOM 均已验证；backend/frontend/self-check commit 全部为 `a7d112e9...`，`PACKAGED_DIRTY=false`。
- Full NSIS 制品 `NetConsole-1.4.8-a7d112e9-x64-setup.exe` 已生成，大小 155,945,538 bytes，SHA-256 为 `dcaf6c04bbba38f3cdcf299596f199cb3b68ff1515fd1a5dc4004156aa129e45`。verifier 已确认 NSIS-3 Unicode、安装器嵌入 manifest、数据根脚本 SHA-256、版本资源、Backend/Frontend commit 和二次哈希读取一致。
- `build-edition-installer.mjs full` 在当前 isolated worktree 因 `node_modules` junction 被 pnpm 判为需重装、且无 TTY 拒绝删除 junction 而停止。为保护共享依赖，未设置 CI 强制删除；随后复用同一已通过的 `package:prepare` 输出，用项目的 electron-builder、package smoke 与 `build_installer --verify` 完成上述实际 Full NSIS 构建和制品验证。
- 真实安装、首次启动与卸载仍为 `PENDING`：本会话不是管理员，安装器是 per-machine 且数据根只能在交互页选择，不能安全静默覆盖 HKLM 指针。未尝试 UAC 绕过，也未接触正式 `D:\NetConsoleData`。

## Soak 状态与剩余风险

- 2 小时/8 小时 soak 为 `PENDING`，未伪造 bytes/hour、RSS 起止/峰值、`queuedBytes` 或 dropped counters。
- 现有故障注入已覆盖 Python EBUSY/PermissionError、1,000 次 rotation backoff、多进程写入及历史清理的单文件占用跳过；这不能替代真实 NTFS 锁、杀毒竞争、物理磁盘耗尽和长时间内存趋势。
- 真实 soak 应在隔离 `D:\NetConsoleTestData\<run-id>` 运行已签名目录包或安装包，每 5–10 分钟记录 Electron/Python RSS、CPU、`electron.log`/`app.log` 增量、runtime/logs 总量、queue/dropped 指标和 backend/WebSocket/task service 存活状态。正常结束前不得将这些项目改为通过。
