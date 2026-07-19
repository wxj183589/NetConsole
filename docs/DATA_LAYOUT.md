# 数据与路径布局

## 1. 路径原则

当前局点 Registry、全局数据根迁移和 `.ncsite` 包的正式约束见 [存储文档](storage/README.md)。标准持久布局增加 `bootstrap/`、`archive/`、`migrations/` 和受控 `temp/`；`data/config/site_registry.json` 是局点列表唯一事实源。

`src/netconsole/core/paths.py` 的 `PathResolver` 是运行路径事实来源。Windows 源码开发态默认数据根为 `%LOCALAPPDATA%\NetConsole\Development\`，打包态为 `%LOCALAPPDATA%\NetConsole\`；两者都不得写入仓库或安装目录。测试、工具或嵌入场景可通过显式构造参数覆盖，但 Electron Main 会拒绝位于项目/安装目录内的 `NETCONSOLE_DATA_ROOT`。业务代码应调用 PathResolver 方法，不应拼接本机绝对路径。

仓库 `.local/{data,runtime}` 和根 `data/` 仅是 2026-07-18 前的历史开发数据源。`scripts/maintenance/migrate_legacy_runtime_data.py` 默认 dry-run，以 `.local` 为优先事实源，使用无覆盖复制、SHA-256、SQLite Backup API 和 `quick_check` 迁往当前开发数据根；冲突必须保留并在 manifest 中显式记录。`scripts/maintenance/clean_test_artifacts.py` 只允许清理仓库 `.local` 顶层明确的 `pytest-*`/Qt 临时产物，不能触及业务数据、验收数据或未知目录。

运行时写入路径不得落入 `docs/`、`tests/` 或项目源码目录。所有源码、JSON、Markdown 和新导出文本使用 UTF-8；外部 H3C 回显和历史日志读取时允许按明确顺序回退编码。

## 2. 顶层目录

```text
%LOCALAPPDATA%/NetConsole/Development/   # 源码开发态
<data_root>/
├─ data/                         # 持久业务数据
│  ├─ global/                    # 跨局点资源
│  ├─ runtime/                   # 持久运行配置，如网络/路由 profile
│  └─ sites/<site>/              # 局点隔离数据
└─ runtime/                      # 可清理的运行日志、协议和缓存
   ├─ logs/
   ├─ base_data_import_previews/<preview_id>/
   │  ├─ preview_meta.json
   │  ├─ merge_plan.json
   │  └─ issues.json
   └─ cache/
      ├─ background_jobs/
      ├─ export_jobs/
      ├─ thumbnails/
      ├─ chart_cache/
      ├─ preview_cache/
      ├─ tmp/、temp/
      └─ export_tmp/、download_tmp/
```

注意 `<data_root>/data/runtime/` 与 `<data_root>/runtime/` 语义不同：前者可保存持久 profile，后者用于任务协议、缓存、临时文件和应用日志。

## 3. 历史全局资源

```text
.local/data/global/mibs/
├─ global_mib.db
├─ raw_archives/
├─ raw_files/
├─ references/
├─ compiled/
├─ index/
└─ reports/
```

上述目录只描述旧版本可能留下的用户数据。SNMP Center、通用 MIB/OID 平台和版本化 MIB 资源已从活动产品删除；当前版本不创建、不读取、不导入这些目录，也不会在升级或自动清理时破坏性删除它们。需要回收历史数据时必须由用户明确选择并经过独立备份/清理流程。

## 4. 局点目录

```text
.local/data/sites/<site>/
├─ db/                           # 局点数据库
│  ├─ devices.db                 # 设备、AC/FIT-AP 等主应用数据
│  ├─ tasks.db                   # 任务快照、结构化事件与 Online MR Task/Session 映射
│  ├─ agents.db                  # Agent 配置与运行状态（不保存明文凭据）
│  └─ snmp.db                    # 旧版本遗留；当前不创建/读取/自动删除
├─ files/                        # 文件管理业务文件
│  └─ imports/online_mr/         # Agent Online MR ZIP 下载与导入 staging
├─ cache/                        # 可由手工磁盘清理管理的局点缓存
├─ metrics/
├─ backups/
├─ imports/
├─ config_center/
│  ├─ raw/
│  ├─ snapshots/
│  └─ outputs/
├─ file_manager/
│  └─ downloads/
├─ snmp/                         # 旧版本遗留；当前不创建/读取/自动删除
├─ topology/                     # 旧版本遗留；当前不创建/读取/自动删除
├─ network_tools/
│  ├─ toolbox/
│  ├─ outputs/
│  ├─ iperf/
│  │  ├─ raw/server/
│  │  ├─ raw/client/
│  │  ├─ parsed/
│  │  │  └─ iperf_results.sqlite
│  │  └─ outputs/
│  ├─ traffic/
│  │  ├─ parsed/traffic_runs.sqlite
│  │  └─ runs/<traffic_run_id>/
│  │     ├─ events.jsonl
│  │     ├─ summary.json
│  │     ├─ remote_result.json
│  │     └─ raw/
│  └─ wireless_scan/
└─ rail_transit/
```

## 5. 轨道交通目录

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

### 5.1 车内通信点表

在线列车车地通信检测的点表按局点保存于：

```text
files/rail_transit/car_network/parsed/point_table.json
```

该文件由 `TrainCommunicationPointTableService` 读取并计算 revision。点表属于业务配置，不写入仓库；编辑、导入、导出和保存任务沿用现有 Task Center/Artifact 目录。具体字段和校验见 [检测点表模型](rail-transit/train-communication/POINT_TABLE.md)。

MR/Mesh 目录型 `mesh.sqlite` 可能只承担目录/入口职责；单文件明细数据库以 `source_files.parsed_db_path` 为准。页面、图表和报告按源文件查询时必须解析到对应明细库。

Online MR 会话结构：

```text
sessions/<session>/
├─ session_meta.json
├─ import_manifest.json          # 仅 Agent ZIP 导入会话存在；保存哈希与相对引用
├─ raw/
│  ├─ init_raw.log
│  ├─ config_collect_raw.log
│  ├─ terminal_monitor_raw.log
│  ├─ mesh_link_raw.log
│  ├─ ap_radio_statistics_raw.log
│  ├─ channel_busy_raw.log
│  ├─ switch_history_latest.log
│  ├─ wireless_status_raw.log
│  ├─ interface_rate_raw.log
│  ├─ collector_output_raw.log
│  ├─ fping_v5_raw.log
│  ├─ fping_v5_samples.jsonl
│  ├─ fping_v5_final_summary.json
│  └─ iperf_client_raw.log
├─ parsed/
│  └─ online_diagnosis.sqlite
├─ view/
├─ logs/
│  └─ collector.log
└─ outputs/
   └─ <session>.zip              # LOCAL 正式包或已校验导入的 Agent 源包
```

阶段 5C-6 至 5C-6B 的轨道交通基础资料不新增数据库：AP 点位、站点/区间派生字段和设备资料继续读取 `devices.db`。上传文件解析临时目录在请求结束前清理；安全合并计划保存到 `.local/runtime/base_data_import_previews/<preview_id>/`，包含 `preview_meta.json`、`merge_plan.json` 和 `issues.json`，不保存上传原文件或绝对路径，也不写 `tasks.db`。过期计划可清理，但不得影响已执行审计。`base_data_import/` 只在 Feature、环境开关和副本/真实范围授权全部通过且真正执行写入时创建。备份使用 SQLite Backup API，审计只保存相对引用、哈希和安全字段。

手工备注保存为会话根目录下 UTF-8 的 `manual_notes.jsonl` 和 `manual_notes.txt`。只有存在运行中目标会话时才持久化；无目标时仅进入当前 UI 日志。

当前标准 Online MR 会话目录没有 `reports/` 或 `packages/`；正式包位于 `outputs/`。`raw/` 和 metadata 是采集事实源，`parsed/online_diagnosis.sqlite` 是报告、历史图表和跨源时间轴的现行查询产物，虽然可由完整 raw 重建，但不能在未确认 raw 完整、重建能力和消费者的情况下当作普通缓存无条件删除。阶段 5B-1 的 `OnlineMrQueryService` 只通过白名单相对引用读取这些内容，不接受任意文件路径，也不创建、迁移或修复数据库 schema。

阶段 5B-7 的 Agent ZIP importer 在当前局点 `files/imports/online_mr/.<import_id>.tmp/` 校验和解压，成功后原子移动到正式 Session；失败时只清理本次 staging，不删除用户源 ZIP 或已有 Session。同一 Session 的重复导入以 `import_manifest.json` 中的源 ZIP SHA-256 判断幂等，哈希不同则冲突且不覆盖。

阶段 5B-8 的 HTTP Client 流式下载到 `files/imports/online_mr/downloads/agent_download_<package_id>_<timestamp>.zip.part`，完成后原子改名为 `.zip`。下载中断、取消或超限会删除 `.part`；成功导入或幂等确认后默认清理下载 ZIP，校验失败或冲突时保留 ZIP 供排查。远端 Agent 包不删除。

阶段 5B-3 的 `online_mr_task_sessions` schema v2 与任务快照/事件共用所属局点的 `tasks.db`。映射只保存 Controller Task、Session、局点、设备、MR、执行端、业务阶段、开始/结束时间、实际分钟时长、停止原因、强停标记和稳定错误摘要；会话创建前允许 `session_id` 为空，收到结构化会话事件后幂等补齐。连接密码、设备命令、完整运行配置、raw、样本和服务端绝对路径不得写入该映射。旧 schema 通过幂等 `ALTER TABLE` 补列，不重建或删除旧行。遗留会话核对只更新映射与 `session_meta.json` 状态，不删除或重建会话事实文件。

## 6. 数据稳定性边界

- 设备管理、FIT AP 资源和其他主应用数据库默认要求兼容，schema 调整需要单独迁移方案和回滚。
- `devices.db` 当前 schema 版本为 `2026.07.18.history_query_indexes`；历史明细按设备/AP 身份和 `collected_at, id` 使用复合索引。升级只幂等创建索引，不改变字段或事实含义；性能证据、一次性磁盘成本和回滚见 [E6 数据库调优归档](archive/migrations/electron-only/E6-2026-07-18.md)。
- 轨道交通基础资料 Query Service 只允许 SQLite `mode=ro + query_only` 和显式安全字段；账号、密码、Community、Token 及隧道凭据不得进入公共 DTO 或预览结果。
- 轨道交通基础资料正式写入默认关闭，不新增主表；受控 Service 只允许事务更新既有 `ap_extension_points`，写前备份、操作审计、预览有效期和数据库哈希乐观锁缺一不可。宁波地铁 12 号线真实库在 5C-6B 仍未授权写入。
- `tasks.db` 由 `TaskRepository` 和 Online MR Task/Session Repository 幂等初始化，使用 WAL/busy timeout/foreign keys；任务快照、事件和映射按各自事务提交，不自动删除业务结果或原始日志。
- `agents.db` 由 `AgentRepository` 幂等初始化，使用 WAL/busy timeout/foreign keys；`agent_configs` 与 `agent_runtime_snapshots` 分表，删除入口只归档配置。Token 不落库，只保存不含秘密的 `credential_reference`。
- `.local/data/sites/<site>/files/network_tools/traffic/parsed/traffic_runs.sqlite` 由 `TrafficRunRepository` 幂等初始化，使用 WAL/busy timeout/foreign keys；`traffic_runs` 保存运行索引，`traffic_agent_tasks` 保存 Controller/Agent 任务映射，`traffic_ping_samples` 只保存新的独立高频 Ping 样本。Token、工具路径、输出绝对路径和任意命令不得写入。
- iPerf interval 的唯一事实源仍是 `files/network_tools/iperf/parsed/iperf_results.sqlite`；Traffic 库只用 `local_iperf_run_id` 关联，不复制 interval。Agent 事件重放通过远端事件键幂等写入既有 interval 表。
- 每个 Traffic Run 的 `events.jsonl` 使用 Controller 单调序号并单独保留 `remote_sequence`；事件、摘要和远端结果只保存相对引用，绝对路径与敏感字段在写入前脱敏。原始 Traffic 文件和正式摘要不属于自动清理范围。
- `online_diagnosis.sqlite`、单文件 Mesh parsed SQLite 等会话解析产物原则上可由完整 raw 重建，但当前仍是历史查询、图表和报告的现行数据源；不得无条件清理。schema 调整必须有明确需求，并保留 raw 事实来源、验证可重建性、同步 parser/report 和兼容边界。
- 不允许把完整 AP Identity shadow items/evidence 或敏感原始字段写入新持久层；当前只允许受控聚合 metadata。
- 导出目标位于用户选择路径或业务 `outputs/`；生成时先写 `.tmp`，成功后原子替换。

## 7. 清理策略

自动清理在 Desktop 启动后延时提交既有 `system_maintenance_cleanup` Job，默认保留 3 天。手工清理允许选择 1～365 天并必须先扫描、选择类别和二次确认。两种入口都只处理：

- `.local/runtime/logs/` 中受认可且不是当前 `app.log` 的旧运行日志；
- `.local/runtime/cache/{thumbnails,chart_cache,preview_cache}/` 中的旧页面缓存；
- `.local/runtime/cache/{tmp,temp,export_tmp,download_tmp}/` 与 `.local/runtime/{tmp,temp,export_tmp,download_tmp}/` 中的旧临时文件。

扫描结果不是删除授权：Worker 删除每个文件前会重新验证年龄、普通文件类型、解析后的真实路径和所属类别。`background_jobs`、`export_jobs`、`ac_web_action_plans`、`config_irreversible`、`rail_web_table_previews`、`rail_web_uploads`、`base_data_import_previews` 以及 `.cancel`、`.json.tmp`、`.part` 协议文件均受保护。清理不得触及局点数据库、配置、业务 raw、正式 outputs/报告或备份；失败日志只记录计数，不记录失败绝对路径和系统异常原文。

系统设置中的手工磁盘清理可管理局点 cache/debug logs，但数据库、配置中心、文件管理、轨道交通、网络工具、备份和配置属于受保护分类。任何扩大清理范围的改动都要有预览、确认、路径约束和测试。
