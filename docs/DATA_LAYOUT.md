# 数据与路径布局

## 路径原则

`src/netconsole/core/paths.py` 的 `PathResolver` 是所有运行路径的唯一事实源。程序安装目录与业务数据根是两个不同概念：安装目录只保存只读发布物，开发、Electron、Python Backend、打包验证和正式安装包则共同使用安装器选择的机器级数据根。当前机器为 `D:\NetConsoleData`；不得根据运行方式切换到 LocalAppData、用户目录、当前目录、仓库或安装目录。

持久根的解析顺序固定为：显式 `NETCONSOLE_DATA_ROOT`、`HKLM\Software\NetConsole\DataRoot`。未配置时停止启动并提示通过安装程序选择目录，绝不猜测或创建 C 盘/用户目录回退。安装器只接受非系统本地固定磁盘，验证可写、原子重命名、SQLite 写锁和至少 10 GB 可用空间；建议至少 100 GB。`config/storage-manifest.json` 同时记录该根、安装标识、创建/最近打开时间、schema 和迁移兼容信息。

自动测试必须显式设置 `RuntimeMode.TEST` 和 `NETCONSOLE_DATA_ROOT=D:\NetConsoleTestData\<run-id>`。测试根不存在、直接指向 `D:\NetConsoleTestData`、或位于该根以外都会失败。测试清理仅限自己的 `run-id`，不得接触 `D:\NetConsoleData`。

根目录不得出现第二个 `data/` 或 `development/` 业务子树。历史仓库 `data/`、`.local/`、LocalAppData 和 `D:\study\NC-data*` 只可由受控迁移脚本读取；正常运行不会读取、创建或删除它们。

## 顶层布局

```text
D:\NetConsoleData
├─ config/
│  ├─ application.json          # 当前局点和应用设置
│  ├─ site_registry.json        # 局点 Registry
│  ├─ bootstrap/                # 受控 bootstrap 材料
│  └─ storage-manifest.json     # schema 与最低版本兼容门
├─ sites/
├─ backups/
│  └─ database_upgrade/          # 统一数据库升级备份中心，默认永久保留
├─ runtime/
│  ├─ electron/
│  ├─ logs/
│  ├─ cache/
│  ├─ temp/
│  ├─ database_upgrade/          # 升级 journal 与跨进程维护锁
│  └─ locks/netconsole-backend.lock
├─ agents/
├─ migrations/
├─ staging/
└─ .trash/                       # 普通局点安全删除时按需创建
```

Electron 的 `userData`、`sessionData`、`cache`、`logs`、`crashDumps` 和 `temp` 都在 `runtime/`；Backend 日志位于 `runtime/logs/`。`staging/` 只用于正在进行且可恢复的迁移，完成后应为空。迁移报告、冲突保留文件、备份和中断 staging 回收记录写入 `migrations/`，不是普通缓存。`.trash/` 只保存普通局点安全删除后移入的完整目录，目标名为 `<site-id>-<UTC timestamp>`；它与空壳 cleanup 的 `migrations/archive/site-recycle/` 各自保留独立语义。

## 数据库升级备份中心

数据库升级框架只通过 `PathResolver.database_upgrade_backups_dir` 写入 `<data_root>/backups/database_upgrade/`。目录按 `scope_type/scope_id/database_kind/backup_id/` 分区，每个可管理备份包含 `database.sqlite`、`manifest.json`、`validation.json` 和 `migration.log`；成功切换时保留的原始 rollback 文件及 MESH `parsed/` 目录也进入同一 `backup_id`，不得留在业务目录中被后续升级覆盖。

升级前必须先暂停相关写入、完成 WAL checkpoint，并用 SQLite Backup API 创建可独立打开的旧库副本。只有大小、SHA-256、`quick_check` 和 `integrity_check` 均通过后才允许构建影子库和原子切换。`runtime/database_upgrade/*.json` 记录 active、shadow、rollback、备份和切换阶段；Backend 启动时只恢复未到终态的 journal，不删除失败影子库或诊断文件。`runtime/database_upgrade/locks/` 只保存短期跨进程锁文件，不是业务备份。

数据库升级备份不属于缓存，默认不按时间、数量或磁盘空间自动删除。用户只能在“系统设置 / 数据库升级与备份”中查看、重新验证、恢复、打开目录或二次确认后删除；恢复前还会为当前活动库创建新的安全备份。历史 `mesh.sqlite.legacy_*`、`mesh.sqlite.schema_archive_*` 和 `mesh.sqlite.rollback_*` 由显式整理任务迁入该中心，并标记为 `VALID_BACKUP / DUPLICATE_BACKUP / ZERO_BYTE_ARCHIVE / INVALID_DATABASE / UNREADABLE_DATABASE`；0 KB 和损坏文件仍保留在 `_invalid/`，不会被自动清理。

## 局点布局

```text
<data_root>/sites/<site>/
├─ db/
│  ├─ devices.db
│  ├─ tasks.db
│  └─ agents.db
├─ files/
│  ├─ backups/
│  ├─ config_center/
│  ├─ file_manager/
│  ├─ imports/
│  ├─ network_tools/
│  └─ rail_transit/
├─ cache/
├─ sync/
└─ site_meta.json
```

切换局点只改变 `sites/<site>` 的业务上下文，不改变 `data_root`。局点名和稳定 `site_id` 的映射由 `config/site_registry.json` 管理；Repository、任务和历史数据继续使用受控的实际局点目录。不得以显示名称、当前工作目录或源代码位置推导局点路径。

`devices.db`、`tasks.db`、`agents.db` 使用各自进程/线程独立的 SQLite 连接，保持 WAL、busy timeout、foreign keys 和幂等初始化。轨旁 AP 逐站规划的唯一事实表为 `ac_trackside_ap_plan(mode='unified')`；空表表示用户已明确清空，维护页、上线概览、PVID 核验和共享范围查询均直接返回空规划。`rail_ap_vlan_plans / groups / group_members / assignments / allocations` 只作为历史留存，不由当前读取链投影，也不再由数据库初始化根据逐站规划生成。当前逐站保存不删除这些历史表。逐站字段和唯一索引升级在数据库初始化事务内幂等执行，失败整体回滚。不可逆 schema 升级必须先备份，并更新 storage manifest；不得以删除或重建真实数据库代替迁移。

## Agent 与 Electron

独立 Windows Agent 的真实配置、目标、任务、日志和采集包位于 `<data_root>/agents/local/`。Agent 的交付程序与工具仍是只读发布物；它们不成为运行数据根，也不回退到 LocalAppData。详细规则见 [独立 Agent](AGENT.md)。

Electron 多窗口共用一个 Electron Main 和一个受管 Backend。所有窗口、Backend 子进程和 Worker 都传递同一个 `NETCONSOLE_DATA_ROOT`。Backend 排他锁位于 `runtime/locks/netconsole-backend.lock`，因此开发版和正式版不能同时写同一真实根。

## 会话、导入与导出

Online MR、MESH、配置采集和网络工具的 raw、parsed、view、logs、outputs 都在所属局点的 `files/` 子树中。例如 Online MR Session 位于：

```text
<data_root>/sites/<site>/files/rail_transit/online_mr/<mr>/sessions/<session>/
```

`raw/` 与 session metadata 是采集事实源；现有 parsed SQLite 仍可能被历史查询、图表或报告使用，不能因为“可重建”而自动删除。正式导出写入用户明确选择的目录或业务 `outputs/`，先写临时文件，成功后原子替换。

数据根迁移、`.ncsite`、现场采集包和回传包遵守 [局点与数据存储](storage/README.md)。迁移使用 staging、逐文件 SHA-256、SQLite 完整性检查和冲突保留；来源目录在数据库、文件和哈希均核验完成前不得删除。

```text
files/rail_transit/
├─ mr_raw_mesh/
│  ├─ catalog.sqlite
│  └─ <mr>/
│     ├─ raw/
│     ├─ parsed/
│     ├─ outputs/
│     └─ mesh.sqlite
├─ online_mr/<mr>/sessions/<session>/
├─ ac_mesh_link/
│  ├─ snapshots/<session_id>/raw/ # 一次性与常驻采集共用的原始回显和快照目录
│  ├─ failures/<task_id>/         # 快照提交失败时保留的受控现场
│  └─ resident/<run-hash>/<controller-hash>/
│     ├─ control.json             # 间隔、立即轮询和正常停止请求；不含凭据或命令文本
│     └─ status.json              # Task、连接、心跳、计数和最近快照健康状态
├─ ground_unattended/
│  ├─ active/<run_date>/
│  │  ├─ fleet_ping/<train>/<mr>/<date>/<hour>_<generation>.ndjson
│  │  │                           # 按 MR/小时顺序追加的 Ping 原始流；含预热标记和采样时 AP/站点/区间快照
│  │  ├─ realtime/syslog/<train>/<mr>/<date>/<hour>_<generation>.ndjson
│  │  │                           # UDP WMESH/IFNET/CFGMAN 原始流；保留接收序号、时钟偏差和安全编码原始字节；未识别来源写入 _unidentified
│  │  ├─ ac_snapshots/           # 按小时 AC 快照 JSONL
│  │  ├─ timeline/               # AC/Ping 关联 JSONL
│  │  ├─ scheduler_events.jsonl
│  │  ├─ coverage_summary.csv
│  │  ├─ deep_collection_manifest.json
│  │  ├─ daily_summary.json
│  │  ├─ errors.jsonl
│  │  └─ manifest.json
│  ├─ archives/<run_date>_ground_unattended.zip
│  └─ index.sqlite               # additive schema v7：配置、运行/覆盖/事件、Ping 目标激活时间、停止/归档操作、分段索引和汇总；结构化 Syslog 事件、射频接口/MR 状态投影和 CFGMAN-IFNET 关联；原始文件索引按 run/类型/列车/MR/端位/时间预筛；Boot Session 保存设备前后时钟/uptime/时区/误差，高频原始报文仍只在 NDJSON/READY ZIP
├─ base_data_import/             # 仅显式授权的受控基础资料写入产生
│  ├─ backups/<operation>.sqlite # SQLite Backup API 生成的写前备份
│  └─ operations/<operation>.json# 脱敏审计与相对备份引用
├─ trackside_ap/
│  ├─ raw/
│  ├─ parsed/
│  ├─ outputs/
│  └─ sessions/
└─ car_network/
   ├─ raw/
   ├─ parsed/
   └─ outputs/
```

无人值守 READY ZIP 是封账后的原始事实源之一。查询历史 Ping/Syslog 时，服务优先读取仍存在的
`active/` 普通文件；文件已按归档策略清理时直接流式读取受校验 ZIP 成员，不解压、恢复或覆盖
`active/`。`index.sqlite` 只保存相对路径、时间范围、记录数、大小、哈希和状态；同一运行的
active/archive 并存时返回 `MIXED` 并去重。ZIP 下载只能通过后端按 `archive_id` 解析的 Artifact 端点，
Renderer 和 Electron Bridge 都不接受数据根物理路径。

Syslog 数据分三层：NDJSON/READY ZIP 是不可变原始证据；`ground_unattended_wmesh_events` 兼容保存去重后的
WMESH、IFNET 和 CFGMAN 结构化事件；`ground_unattended_radio_interface_states`、
`ground_unattended_mr_runtime_states` 与 `ground_unattended_radio_correlations` 是可重建投影。
重复 UDP 报文仍保留在原始流，只增加结构化事件的 `duplicate_count`，不会重复切换接口状态或生成综合事件。

活动长 Ping 首次查询按受控时间范围最多返回 3000 个点，完整运行最多返回 10000 个降采样点；增量游标
保存已登记 OPEN 文件的稳定 `file_id` 与下一字节偏移，并绑定 run、列车、MR、目标和预热选项。游标只在
API 调用方内存/Renderer 状态中流转，不写 SQLite、不修改 NDJSON，也不是可提交的物理路径。后续读取从
完整换行结束的位置继续，尚未 flush 完整的一行留到下一次；同一文件中时间较早的晚到记录仍会读取，并由
前端按时间与 sequence 重排。CLOSED/READY 历史数据保持静态有界查询，不通过活动游标修改或恢复原文件。

## 清理边界

自动和手动缓存清理只能处理已白名单的 `runtime/cache/`、`runtime/temp/` 与受认可的运行日志；不触及局点数据库、配置、raw、会话业务日志、正式 outputs、报告、备份、Agent 包、迁移材料或 `.trash/`。普通局点删除只允许把 Registry 中的一级 `sites/<site>/` 普通目录原子移动到 `.trash/`，不递归永久删除；移动和 Registry 更新任一阶段失败都必须回滚。执行前必须重新确认规范化路径位于数据根允许子树，并拒绝符号链接和路径逃逸。

任务中心的“清理”不是磁盘清理。它只在当前局点 `tasks.db` 的任务快照上写入 `dismissed_at / dismissed_by / dismiss_reason`，隐藏已结束的历史记录；任务事件、日志、采集结果、会话文件、正式导出和 Artifact 均保留。真正的物理清理只能由独立数据库维护或文件管理用例按白名单、保留期和路径边界执行。

用户可在 NetConsole 外部删除单个导出、Artifact 目录、局点目录或隔离数据根。系统不把这种外部变化回写成新的任务失败：任务列表存在时动态报告 Artifact `MISSING/INVALID`，`tasks.db` 或局点目录不存在时返回空任务状态，新的空数据根不会从旧根恢复任务。必要顶层目录仍由 `PathResolver` 启动流程按当前根创建；任何协调和下载都只解析当前数据根与当前局点下的受控相对路径，不跟随越界路径或符号链接。恢复同一文件后可再次动态识别为 `AVAILABLE`，无需持久化可用性字段。

磁盘统计与缓存清理的默认运行目录是 `<data_root>/runtime/`，而不是数据根同级目录。系统设置和维护脚本只能报告历史目录；未经完成迁移核验和人工保留期确认，不得自动合并或删除它们。
