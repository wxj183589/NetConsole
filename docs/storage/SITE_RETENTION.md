# 局点数据保留与清理

局点数据清理是独立的扫描、复核和执行用例，不复用缓存清理，也不按目录或文件年龄直接递归删除。入口位于“系统设置 -> 局点与数据管理 -> 数据清理”。所有扫描和执行都进入 Job Center；Renderer 只提交局点 ID、服务端扫描令牌和候选 ID，不接收或提交任意物理路径。

扫描和执行统一占用 `site-database-maintenance:<site_id>`。执行时先获取该数据库维护锁，再获取 `site-retention-<site_id>` 领域 storage lock。History migration/cutover 使用同一数据库维护键；future compact 也必须复用，避免同一局点的重 IO/写维护并发。

## 两阶段流程

1. `site_retention_scan` 只读统计局点总占用、当前数据库、原始数据、解析数据、历史备份和其他文件，并分类候选。
2. 扫描报告写入 `<data_root>/runtime/site_retention/<site_id>/<scan_token>.json`，`latest.json` 指向最近结果。报告内只保存局点相对路径。
3. 用户选择后，`site_retention_apply` 使用扫描令牌和候选 ID 执行。Worker 在写入前重新扫描；候选大小、时间、状态或证据变化时以 `SITE_RETENTION_SCAN_STALE` 拒绝。
4. 执行任务不可取消，因为删除、归档替换和 SQLite `VACUUM` 是不可逆的分步写操作。完成后页面重新扫描，不继续展示旧候选。

扫描令牌不是删除授权的替代品。API 仍要求明确确认，执行时再次检查局点路径、活动任务、当前数据库、回滚数据库、WAL、ZIP 和 SQLite 完整性。

## 第一阶段范围

### 历史数据库备份和过时版本

- 扫描 `sites/<site>/files/backups/` 中的 `.db / .sqlite / .sqlite3`，不扫描 `archives/` 中的既有归档。
- 当前 `sites/<site>/db/` 数据库和无人值守 `index.sqlite` 固定为“当前使用”，绝不自动删除。
- 同一已识别数据库类型保留最近两份备份，分别标为“最近回滚”和“最近稳定”。
- 30 至 90 天、当前 schema 明确更高且存在更新回滚副本的备份可压缩到 `files/backups/archives/<database-kind>/`。
- 90 天以上、满足相同证据的备份可删除；内容 SHA-256 完全相同且存在保留副本的已识别备份也可删除。
- 压缩前抽样估算可释放空间；执行结果以归档后的实际文件大小为准。
- 非空 `-wal`、不可读 SQLite、schema 不能比较、没有当前同类数据库或没有更新回滚副本时禁止自动处理。
- 未识别数据库即使与另一文件哈希相同，也固定标为“未知数据库”，只能人工确认。

数据库状态包括：`当前使用`、`最近回滚`、`最近稳定`、`历史迁移版本`、`重复备份` 和 `未知数据库`。当前尚未通过代码引用审计证明的旧模块数据库不会自动标记为“废弃版本”。

### Online MR 原始数据

当前只处理 Online MR 会话中的松散 `raw/`。会话必须同时满足：

- 状态为正常结束；
- finalization 完成且 `data_integrity=complete`；
- 解析数据库存在并通过 SQLite `quick_check`；
- 完整会话 ZIP 存在并通过 CRC；
- ZIP 包含每个 raw 文件，且大小和 CRC 与松散文件一致；
- 已结束至少 30 天；
- 没有 `.retain / keep.json / retain.json` 人工保留标记。

执行后只删除已被完整 ZIP 覆盖的松散 `raw/`，会话 ZIP、解析数据库、metadata 和 outputs 保留。Online MR 查询对归档 ZIP 提供透明回退，原始尾部、摘要和日志分块仍可读取。

### 任务历史

普通终态 Task Center 记录按 `site_name + task_type` 保留最近 10 个有效任务。
`TaskRepository.retain_recent_terminal_tasks()` 在事务中删除旧任务的
`task_events`、`task_snapshots` 和无引用的 `task_results`，不会删除 Artifact
文件或业务来源。

- `PENDING/STARTING/RUNNING/STOPPING` 永远保护；非终态记录不会进入候选。
- `online_mr_task_sessions` 映射、Online MR/Ground/MESH 任务类型，以及明确的
  `online_mr:*`、`ground_unattended:*`、`mesh_source:*` 等资源引用永远保护。
- `dry_run=true` 只返回候选与保护计数；实际执行不执行 `VACUUM`、Artifact 删除
  或真实数据根迁移。
- 任务中心软 dismiss (`cleanup_history`) 与物理 bounded retention 是两条独立路径。

隔离 rehearsal plan 使用固定格式、数据库逻辑内容摘要、主文件 SHA、精确
event sequence ranges、snapshot/result 主键列表、各集合 digest 和 expected
counts。apply 在取得 `site-database-maintenance:<site_id>` 后重算逻辑摘要，
只删除 plan 中的主键且要求实际数量完全相等；不执行 checkpoint、VACUUM
或 Artifact 文件删除。活动任务、Online MR mapping、Ground task 和带 Artifact
引用的任务固定受保护。执行器没有 production force 参数。

旧的统一 90 天 task event 方案不再作为可选择候选。生产 apply 只有在用户
批准期限并完成独立维护门禁后，才能原位开放同一 owner 的执行路径。

## 固定保护规则

- 当前数据库、未知数据库、当前活动任务数据、解析失败或证据不完整的 raw、人工保留数据不进入自动候选。
- 执行只接受扫描报告中后端签发的候选 ID；路径必须再次解析到当前局点白名单子树，且拒绝符号链接和路径逃逸。
- 归档先写临时 ZIP并执行 CRC/大小校验，再原子发布；成功后才移除原备份。
- 真实局点开发验收只允许 scan-only，除非用户明确授权执行并已完成备份复核。

## 延后范围

MESH 原始导入、无人值守 active/archive、设备采集历史、FIT AP radio、LLDP、光模块历史和高频快照降采样仍由各领域生命周期拥有，不接入通用局点清理。
