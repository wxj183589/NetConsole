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
├─ runtime/
│  ├─ electron/
│  ├─ logs/
│  ├─ cache/
│  ├─ temp/
│  └─ locks/netconsole-backend.lock
├─ agents/
├─ migrations/
└─ staging/
```

Electron 的 `userData`、`sessionData`、`cache`、`logs`、`crashDumps` 和 `temp` 都在 `runtime/`；Backend 日志位于 `runtime/logs/`。`staging/` 只用于正在进行且可恢复的迁移，完成后应为空。迁移报告、冲突保留文件、备份和中断 staging 回收记录写入 `migrations/`，不是普通缓存。

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

`devices.db`、`tasks.db`、`agents.db` 使用各自进程/线程独立的 SQLite 连接，保持 WAL、busy timeout、foreign keys 和幂等初始化。不可逆 schema 升级必须先备份，并更新 storage manifest；不得以删除或重建真实数据库代替迁移。

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
├─ ground_unattended/
│  ├─ active/<run_date>/
│  │  ├─ fleet_ping/<train>/<mr>/<date>/<hour>_<generation>.ndjson
│  │  │                           # 按 MR/小时顺序追加的 Ping 原始流
│  │  ├─ realtime/syslog/<train>/<mr>/<date>/<hour>_<generation>.ndjson
│  │  │                           # UDP WMESH/IFNET 原始流；保留接收序号、时钟偏差和安全编码原始字节；未识别来源写入 _unidentified
│  │  ├─ ac_snapshots/           # 按小时 AC 快照 JSONL
│  │  ├─ timeline/               # AC/Ping 关联 JSONL
│  │  ├─ scheduler_events.jsonl
│  │  ├─ coverage_summary.csv
│  │  ├─ deep_collection_manifest.json
│  │  ├─ daily_summary.json
│  │  ├─ errors.jsonl
│  │  └─ manifest.json
│  ├─ archives/<run_date>_ground_unattended.zip
│  └─ index.sqlite               # 配置、运行/覆盖/事件、分段索引和汇总；Boot Session 保存设备前后时钟/uptime/时区/误差，Syslog 仅索引/事件/健康指标，不保存高频原始报文
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

## 清理边界

自动和手动清理只能处理已白名单的 `runtime/cache/`、`runtime/temp/` 与受认可的运行日志；不触及局点数据库、配置、raw、会话业务日志、正式 outputs、报告、备份、Agent 包或迁移材料。删除前必须重新确认规范化后的路径位于数据根的允许子树。

磁盘统计与缓存清理的默认运行目录是 `<data_root>/runtime/`，而不是数据根同级目录。系统设置和维护脚本只能报告历史目录；未经完成迁移核验和人工保留期确认，不得自动合并或删除它们。
