# Task Center 数据所有权矩阵

本矩阵是 `tasks.db` 轻量化、清理和候选库重建的边界。它不授权生产数据操作，也不把历史搬到新的无限增长 TaskHistoryStore。

| 数据 | 当前权威 | Task Center 读取 | 清理服务处理 | 保护条件 |
|---|---|---|---|---|
| `task_snapshots` | `tasks.db` 当前任务状态 | 列表、详情、恢复指针 | 仅显式允许的终态任务删除 | `PENDING/RUNNING/STOPPING`、未知状态、恢复/关联元数据不完整时保护 |
| `task_events` | `tasks.db` 轻量审计轨迹；已归档事件由既有历史存储负责 | 详情日志、进度轨迹 | 与所属 Task 同事务删除；不按 Recent10 猜测 | 活跃任务、Online MR/Ground 关联或不可验证时保护 |
| `task_results` | 结果身份、绑定、hash 和元数据；内容由 Blob authority 提供 | 列表只读元数据，详情/结果读取内容 | 仅随可清理 Task 删除 | 结果引用、Artifact/Package/业务来源引用或 authority 不完整时保护 |
| `task_result_blobs` | `content_sha256` 内容寻址 Blob | 详情/结果优先读取并校验 | 仅回收没有任何 ready `task_results` 引用的孤立 Blob | hash、codec、压缩长度、UTF-8 或 JSON 校验失败时不回退 |
| `task_result_storage_rollout` | `tasks.db` rollout 状态和审计 | 维护/诊断 | 不清理 | schema/状态审计证据 |
| `online_mr_task_sessions` | Online MR 会话映射数据库 | Task Center 详情关联 | 通用 Task 清理不删除 | 任意 `controller_task_id` 映射都保护 |
| Ground current mapping | Ground `index.sqlite` 当前运行/深采/删除操作关联 | 通过关联诊断读取 | 通用 Task 清理不删除 | `task_id/controller_task_id` 命中或 Ground DB 不可读 |
| Artifact manifest/output | 受管 Artifact manifest 和输出文件 | 详情、打开、下载 | 不删除文件、manifest 或 Package | `artifact_id/ref/path`、result path 或 manifest 归属命中 |
| TaskHistoryStore sealed archive | 既有历史归档 authority | 详情/日志兼容回读 | 本轮不删除、不迁移 | 归档不属于 Task Center current-row 清理权限 |
| site package / backup / raw evidence | 各业务模块自身 authority | 只读取引用 | 不删除 | resource key、路径或业务引用命中 |

## 结论

- `tasks.db` 不做物理拆分；不新增 `TaskHistoryStore` 来伪造回收。
- 新结果使用 `task_results` 的唯一结果身份和 `task_result_blobs` 的共享压缩内容；`canonical_json` 在兼容阶段仍保留，旧读者可继续读取，Blob-ready 读者必须先读 Blob 并失败闭合。
- Task Center 列表查询不选择 `task_results.canonical_json`，也不把完整结果放进列表 DTO；详情、结果打开和 replay 才允许 materialize 结果内容。
- 删除顺序是 `task_events` → `task_results` → `task_snapshots`，由 `TaskCleanupService` 在同一事务中执行；不依赖外键级联的副作用。
- 当前 UI 的“清理历史”仍是可逆 soft-dismiss；真正的物理清理由 `preview_cleanup(task_ids)` 产生决定后，再由 `cleanup_tasks(task_ids)` 显式执行。
