# 局点管理

局点 Registry 位于当前数据根的 `config/site_registry.json`，是局点列表的唯一事实源。每个记录有稳定 `site_id`、中文 `display_name`、相对路径、创建/更新时间和备注；显示名称不作为数据库主键。

首次启动或 Registry 缺少历史记录时，系统只扫描受控的 `sites/<目录>/db/devices.db`，以无覆盖、幂等方式补登记既有局点。符合稳定 ID 规则的目录沿用目录名；中文或其他历史目录生成 `legacy-<稳定哈希>` 作为内部 `site_id`，原目录名保留为相对路径和 Backend 的实际存储名称，`site_meta.json` 中的 `display_name` 优先用于显示。没有主数据库、路径越界、符号链接或损坏 Registry 的目录不会被自动登记，也不会被删除、重命名或初始化。

Electron 重启传递稳定 `site_id`，Backend 启动时先通过 Registry 解析到实际目录名；所有 Repository、任务和历史数据继续使用原局点目录。这样局点 ID 与 Windows/中文目录名可以安全分离。

新建流程为：校验 ID/名称、创建 staging、初始化必要数据库和默认设备组、写 `site_meta.json`、执行 SQLite `quick_check`、原子发布、注册 Registry。失败清理 staging，不改变当前局点。

`site_meta.json` 同时保存跨电脑同步使用的不可变 `site_uuid` 与 revision。局点显示名称可以修改，不能作为同步匹配键。历史 `legacy-*` 局点保持只读审计优先：未产生审计记录前不能导出现场采集包或采集回传包；审计后才补齐同步标识。完整迁移/备份不依赖该限制。

切换先调用只读 preflight，验证目标存在、不是当前局点，并扫描所有已登记局点的 `PENDING/STARTING/RUNNING/STOPPING` 快照；预检与正式激活都会通过统一 Job Center reconcile 核对本地 PID 与当前 `TaskRuntime` 宿主。`COMPLETED/FAILED/CANCELLED` 历史任务不阻塞；死 PID 或重启后无内存宿主的零 PID 残留任务保留历史并转为 `FAILED` 后也不阻塞。reconcile 后仍可能继续执行的真实活动任务才阻止切换，API 返回任务 ID、类型、名称、状态和阻塞原因，设置页可直接打开对应任务中心。

预检通过后，当前 Renderer 发送 `before-site-switch`，保存可回滚工作区快照并移除 Dashboard、系统设置之外的局点业务标签；MESH 在该阶段中止详情/轨旁请求并释放 ECharts 与轨旁 series cache。激活接口更新现有应用配置并返回 `restart_required=true`；Electron 停止旧 Backend 后、启动新 Backend 前收敛所有工作区窗口的持久化快照。新 Backend 只有在 health ready 且 `/api/v1/sites/active` 与目标局点一致后才被接受，随后清除旧 Renderer 恢复状态并刷新所有 Renderer；新进程重新加载 Feature Gate、导航和当前局点。任一步失败时 Electron 恢复原 Backend 和其他窗口快照，发起窗口恢复本地快照并保持可操作。托盘“快速切换局点”只向 Renderer 发送目标 `site_id` 意图，Renderer 回到设置页共享这条流程；Electron Main 从 Backend `/api/v1/sites/active` 和 `/api/v1/sites` 重新读取 `display_name` 与清单来更新托盘，不接收 Renderer 提供的名称或清单。该流程只清理内存状态、标签和 query，不删除、移动或改写旧局点数据库、raw、报告与 Artifact。

## Legacy 与 Demo 审计

局点回收前必须先运行只读审计。审计统计目录与文件大小、逐文件 SHA-256、SQLite `quick_check` 和表行数，并核对 Registry、当前局点、最近局点及 Electron bootstrap 引用；它只生成 manifest，不把“目录很小”或“名称像旧数据”直接解释为可删除授权。系统设置中的“审计”进入 Task Center，维护命令为：

```powershell
.\.venv\Scripts\python.exe -m scripts.maintenance.audit_sites
.\.venv\Scripts\python.exe -m scripts.maintenance.audit_sites --site-id demo
```

默认 manifest 写入 `<data_root>/migrations/site-audits/`；也可通过 `--output` 指定报告文件。报告中的 `active_site`、`managed_demo`、`legacy_demo`、`empty_shell`、`legacy_alias`、`legacy_valid` 和 `normal_site` 是审计分类，不是删除指令。存在业务表记录、raw、parsed、报告/Artifact、当前局点或 bootstrap 引用时必须保留并人工复核。

## 二阶段安全回收

只有审计确认无独有业务数据且不属于当前局点、bootstrap 当前引用的局点，才允许进入二阶段回收：

1. `prepare` 只接受最近一次正式审计 manifest，生成一次性 token、文件 manifest、引用清单、阻断原因和审计 manifest 哈希，不在同步请求中重新扫描目录，也不移动目录。
2. 用户确认后，`apply` 逐文件复核大小与 SHA-256；任一文件变化即拒绝执行，要求重新审计。
3. 通过复核后，原目录只移动到 `<data_root>/archive/site-recycle/<site_id>-<token>/site/`，同时注销精确 Registry 记录并清理 `recent_sites` 引用，不做永久删除。

回收目录保留 Registry、应用配置备份和 `tombstone.json`。执行中任一步失败会恢复原目录、Registry 和应用配置；成功后的 tombstone 可在 30 天内通过 `POST /api/v1/sites/recycle/{cleanup_token}/restore` 进入 Task Center 恢复，恢复后 token 失效。当前没有“永久清空回收区”或任意路径恢复入口，不得手工删除或移动受控回收目录。

## 受控 Demo

Demo 不是长期业务数据容器。受控重建在 `<data_root>/temp/demo-seed/` staging 中使用当前 SQLite Schema、Repository 和 MESH parser 生成少量脱敏示例，写入 `managed_demo=true` 和 seed 版本，且不预置 Task Center 历史。发布前总大小必须小于 `50 MB`；超过上限即拒绝发布。

旧 Demo 默认先审计。只有已标记的受控 Demo 或命中已知旧 Demo 事实集时才允许直接替换；疑似包含用户数据时默认拒绝，必须先完成独立备份与明确确认。重建时旧 Demo 移入 `<data_root>/archive/demo-recycle/` 并保留 manifest/tombstone 与恢复材料，staging 成功发布后才更新 Registry；失败必须恢复旧 Demo 和配置状态。

局点审计、回收和 Demo 重建只允许在 `persistent` Desktop 会话中调用，且执行写操作前检查全局活动任务。`isolated_test` 只用于临时 UI/API 仿真，相关写 API 返回只读错误，不得读取、修改或借用正式数据根、Registry 与 bootstrap。
