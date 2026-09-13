# NetConsole Follow-up 收口验收

日期：2026-09-13

本次只覆盖 Ground 局点上下文和 `tasks.db` 启动初始化物理重写根因。Production Retention、Operational GC、Production GC、rollback owner、ProductionMaintenanceCapability、HistoryStore 和数据库物理压缩均不在本次范围内。

## 代码与范围

BASE_HEAD=`1ffb948b6f8a9804c06fed53b06b6cd7540c54e5`

FINAL_HEAD=`458aa4d6`（代码实现冻结提交；本验收文档为其后的记录提交）

GROUND_ROOT_CAUSE=Backend 在 `create_app` 时把 Ground Repository/Supervisor/ApplicationService 绑定到初始局点，站点切换的 runtime rebind 未替换这组对象；同时被缓存的 Ground Renderer 页面没有在全局局点事件后清理旧状态并重新加载。

GROUND_CODE_CHANGED=YES

修复内容：

- Backend 增加按目标局点构造完整 Ground runtime 的组合根，切换时启动目标 runtime、关闭旧 runtime，并同步 application state。
- Ground 页面监听当前和兼容局点切换事件；切换时使旧请求序列失效、清除 site-scoped state、重新加载当前局点数据，缓存页面重新激活时再次确认上下文。
- `TaskRepository` 仅修复启动兼容检查的幂等性：只有触发器语义确实不同或兼容字段需要更新时才写入。

GROUND_SITE_10_TO_12=PASS

GROUND_SITE_12_TO_10=PASS

GROUND_RESTART=PASS

验证覆盖真实 Electron 启动、Settings 正常切换路径、Ground 页面打开、双向切换和重载；未启动真实设备采集。

## SQLite 重写审计

SQLITE_DB_PATH=`D:\NetConsoleData\sites\宁波地铁12号线\db\tasks.db`

SQLITE_SIZE_BEFORE=160104448

SQLITE_SIZE_AFTER=160104448

SQLITE_SHA_BEFORE=`0fc185b20778acb95519b832bd30f239f7bae174d6effa92a90ff4b3a1debf3f`

SQLITE_SHA_AFTER=`0fc185b20778acb95519b832bd30f239f7bae174d6effa92a90ff4b3a1debf3f`

SQLITE_MTIME_CHANGED=NO

SQLITE_JOURNAL_MODE=WAL

SQLITE_AUTO_VACUUM=0

WAL_PRESENT_BEFORE=YES（0 bytes）

WAL_PRESENT_AFTER=YES（0 bytes）

WAL_CHECKPOINT_OBSERVED=YES（在隔离副本中观察到；本次 Production 只读核对未主动执行 checkpoint）

COPY_REPLACE_PATH_FOUND=NOT_FOUND_IN_GUI_STARTUP_OR_SITE_SWITCH

STARTUP_MAINTENANCE_REWRITE_FOUND=NO_FOR_TASKS_DB（运行日志中的启动维护仅命中 `devices.db`）

根因不是普通 SQLite 打开或 WAL 初始化本身。隔离复现显示：普通连接和建表脚本不改变主文件，而旧版 `_ensure_schema_compat` 每次无条件 `DROP TRIGGER`/`CREATE TRIGGER`，写入 WAL 后在连接关闭/检查点时把物理变化落到主文件。修复后对触发器 SQL 做语义归一化比较（兼容 `IF NOT EXISTS` 和末尾分号差异），并将元数据更新改为条件更新；正确现状不会重复写入。

SQLITE_REWRITE_CLASSIFICATION=PRODUCT_CODE_UNCONDITIONAL_TRIGGER_RECREATE_VIA_NORMAL_WAL_CHECKPOINT_FIXED

LOGICAL_DATA_CHANGED=NO

目标 Production `tasks.db` 前后保持：`page_count=39088`、`freelist_count=29983`、`schema_version=84`、`data_version=2`、`quick_check=ok`、`foreign_key_check=[]`；主要任务表计数也保持：`task_snapshots=4232`、`task_events=16573`、`task_results=3858`、`task_result_blobs=2833`、`task_retention_tombstones=0`。

## 验证结果

QUICK_CHECK=PASS

FOREIGN_KEY_CHECK=PASS

TARGETED_TESTS=Python 62 passed；Renderer Ground 50 passed；TaskRepository 初始化回归 2 passed；Architecture 12/12 PASS

PYTHON_FULL_GATE=4868 passed, 2 skipped

RENDERER=1301 passed（181 files）

ELECTRON=298 passed（37 files）

ARCHITECTURE=12/12 PASS

FULL_GATE=PASS

NEW_FAILURES=0

## 明确边界

TASK_EVENT_RETENTION_RERUN=NO

PRODUCTION_GC_EXECUTED=NO

VACUUM_EXECUTED=NO

没有执行 Production Retention cleanup、DELETE、GC、VACUUM、VACUUM INTO、compact、candidate replace、backup restore、HistoryStore 改造或真实设备采集。

本次变更不改变 Task Event Retention eligibility、Operational Cleanup、任务模型、Task Center、Production gate 或 Production maintenance 流程。GUI smoke 按正常切换路径临时更新当前局点指针并恢复到宁波10号线；目标 Production `tasks.db` 仅作前后核对，未发生逻辑业务数据变化。

## 风险

- 真实设备、真实网络采集、长时间运行和正式安装包人工验收仍需按各自门禁单独进行。
- Electron 自动化直接驱动路由时仍可观察到既有的 `workspace route is not allowed` 持久化告警；本次 Ground 页面和 API 均正常，该告警不属于本次变更，未扩大范围处理。

CODE_CHANGE_REQUIRED=YES（Ground 上下文修复和 SQLite 初始化幂等性修复）

CODE_STATUS=READY_FOR_RELEASE

FOLLOW_UP_STATUS=COMPLETE
