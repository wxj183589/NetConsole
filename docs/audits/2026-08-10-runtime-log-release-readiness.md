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
- 源码层迁移正反测试已通过；提交 `845ba19ddb01bcf6507fa59a8ed1b35e7b68a51d` 的干净冻结包已完成旧库迁移与设备列表 HTTP 200 smoke，确认该兼容迁移在 frozen runtime 中生效。

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
| Release system（补齐兼容性 Profile 后） | 66 passed |
| LocalProcessAdapter 与 Job Center 定向回归 | 37 passed；竞态用例连续 10 次通过 |
| Packaged soak 夹具回归 | 2 分钟通过；最终样本与 `completed_duration=true` 正常写出 |
| 最终完整 pytest（单次运行） | 3852 passed, 2 skipped, 0 failed, 32 warnings；677.39s |

当前代码组合第一次完整 pytest 得到 `3851 passed, 2 skipped, 1 failed`。唯一失败为 `tests/test_local_process_adapter.py::test_local_process_adapter_completes_and_reads_both_pipes`：测试在持久化状态变为 `COMPLETED` 后立即断言 Adapter 状态已移除，命中了完成回调与状态清理之间的正常异步窗口。生产语义实验会破坏协议致命错误收口，已撤销；最终只将测试改为等待既有的 `not adapter.is_running(job_id)` 契约。定向回归和连续 10 次重复均通过，随后同一代码组合的单次完整 pytest 达到上表的 0 failed 基线。

## 发布构建与安装器

- 提交 `a7d112e94d565dc6f993d7cc4e34ab49d877d58a` 的目录包曾通过当时的 package smoke，但后续 2 小时 soak 发现它缺少 `device_compatibility_profiles.json`，设备兼容性 API 首次加载返回 503，并记录两次 `DEVICE_COMPATIBILITY_RESOURCE_FAILED`。Backend、Renderer 和日志链路在 soak 中持续存活，但该旧制品不再作为发布候选。
- 根因是运行端读取 `netconsole/assets/device_compatibility_profiles.json`，而 clean build 白名单只包含命令 Profile。提交 `845ba19ddb01bcf6507fa59a8ed1b35e7b68a51d` 已将现有兼容性 Profile 加入 PyInstaller 明确白名单、`CleanBuildLock` 和构建输入，并扩展 package smoke：资源必须存在，schema 必须为 `2026.07.device-compatibility-profiles.v1`，profiles 必须非空，`profile_id` 必须非空且无重复。新 smoke 对旧包会准确失败。
- 基于 `845ba19d...` 严格按 Web/Electron build、`package.mjs`、electron-builder 顺序重建的 `win-unpacked` 完整通过 package smoke：frozen `log_policy.json`、时区和兼容性 Profile、旧设备数据库迁移/list HTTP 200、Ground 状态 HTTP 200、Worker 中文协议、MESH 幂等性、重复文件名、Qt 残留、NOTICE/SBOM 均已验证；backend/frontend/self-check commit 全部为 `845ba19d...`，`PACKAGED_DIRTY=false`。随后执行 1 分钟启动回归，未再出现 `DEVICE_COMPATIBILITY_RESOURCE_FAILED`。
- 新 Full NSIS 制品 `NetConsole-1.4.8-845ba19d-x64-setup.exe` 已生成，大小 155,947,391 bytes，SHA-256 为 `6193b1d308d476a64e66c2bdb49de859e5311d5b26ff36481de2084e8dadef10`，build id 为 `netconsole-1.4.8-845ba19d-20260809T233802Z`。verifier 已确认 NSIS-3 Unicode、安装器嵌入 manifest、版本资源、Backend/Frontend commit、`PACKAGED_DIRTY=false` 和哈希一致。
- 安装器绑定运行时代码提交 `845ba19d...`；后续分支提交 `8e13c5979c63da5e08e27ce0e9667849295911e4` 只修正 LocalProcessAdapter 测试的异步等待契约，不改变安装包运行时代码。二者必须分开追踪，不能把该安装器写成绑定分支后续 HEAD。
- 真实安装、首次启动与卸载仍为 `PENDING`：本会话不是管理员，安装器是 per-machine 且数据根只能在交互页选择，不能安全静默覆盖 HKLM 指针。未尝试 UAC 绕过，也未接触正式 `D:\NetConsoleData`。

## 2 小时 Packaged Soak

- 对提交 `a7d112e94d565dc6f993d7cc4e34ab49d877d58a` 的 `win-unpacked/NetConsole.exe` 执行 7,203.549 秒 soak；测试根为 `D:\NetConsoleTestData\packaged-log-soak-20260810-052300`，每 5 分钟采样，共 25 个样本。Electron 主进程和 3 个子进程、1 个 Python Backend 在全部样本中存活，runner stderr 为 0。
- 剔除启动尚未完成的 0 秒样本，以 5 分钟样本至 120 分钟样本计算：`electron.log` 从 2,659 bytes 增至 2,723 bytes，约 33.377 bytes/hour；`app.log` 从 2,798 bytes 增至 3,333 bytes，约 279.007 bytes/hour。新增内容是每小时 tray/自动清理状态，不是 traceback 或 payload 风暴。
- Electron 合计 RSS 的起始/峰值/结束值为 374.578/394.242/391.133 MiB，线性回归斜率为 +8.396 MiB/hour；Python RSS 为 194.566/204.863/204.863 MiB，斜率为 +4.797 MiB/hour。2 小时内没有高速或失控增长，但两条斜率仍为正，不能据此宣称长期无增长；8 小时 soak 仍为 `PENDING`。
- `LOG_BACKPRESSURE` 和 `LOG_BACKPRESSURE_RECOVERED` 事件均为 0。当前 queue metrics 只存在 Electron Main 内存中，没有跨进程只读接口，因此 `queuedBytes/peakQueuedBytes/dropped*` 不能直接采样；本审计不把不可见 counters 伪报为 0。现有实现只要发生任一等级 drop 就会启动 incident 并写 backpressure/recovered 控制事件，本次没有观察到该间接证据。
- soak 结束前的最后一个样本仍确认全部进程存活；随后测试夹具主动终止隔离进程树。`ELECTRON_UTILITY_PROCESS_GONE exit_code=-1` 发生在该夹具收口之后，不属于运行窗口内崩溃。
- 针对新候选 `845ba19d...` 的第一次长时尝试在约 3,602 秒处记录 `ELECTRON_TRAY_EXPLICIT_QUIT` 并正常退出；随后发现夹具在单进程最终采样时的数组解包缺陷，不能将该次提前结束判为 soak 通过。夹具已修复并用 2 分钟隔离回归确认正常收口；按本次用户指示跳过新候选完整 2 小时 soak，不将其写成通过。

## 剩余风险

- 现有故障注入已覆盖 Python EBUSY/PermissionError、1,000 次 rotation backoff、多进程写入及历史清理的单文件占用跳过；这不能替代真实 NTFS 锁、杀毒竞争、物理磁盘耗尽和长时间内存趋势。
- 7,203 秒 soak 针对后来因兼容性资源缺失而淘汰的 `a7d112e9...` 目录包；资源修复没有改动日志写入链路，但不能据此把旧制品 soak 等同为新候选的正式验收。
- 新候选完整 2 小时/8 小时 soak 已按用户指示跳过；真实 NSIS 安装/首次启动/卸载、直接 dropped counters 以及 WebSocket/task service 主动业务负载仍未完成。本次合并属于用户明确要求下的发布记录收口，不代表这些门禁已通过。
