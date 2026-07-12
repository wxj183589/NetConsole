# 数据与路径布局

## 1. 路径原则

`src/netconsole/core/paths.py` 的 `PathResolver` 是运行路径事实来源。开发态默认 `PathResolver.data_root` 为仓库 `.local/`，持久业务目录为 `.local/data/`，临时运行目录为 `.local/runtime/`；打包态优先使用 `%LOCALAPPDATA%\NetConsole\`。测试、工具或嵌入场景可通过显式构造参数覆盖。业务代码应调用 PathResolver 方法，不应拼接本机绝对路径。

运行时写入路径不得落入 `docs/`、`tests/` 或项目源码目录。所有源码、JSON、Markdown 和新导出文本使用 UTF-8；外部 H3C/MIB/历史日志读取时允许按明确顺序回退编码。

## 2. 顶层目录

```text
<data_root>/
├─ data/                         # 持久业务数据
│  ├─ global/                    # 跨局点资源
│  ├─ runtime/                   # 持久运行配置，如网络/路由 profile
│  └─ sites/<site>/              # 局点隔离数据
└─ runtime/                      # 可清理的运行日志、协议和缓存
   ├─ logs/
   └─ cache/
      ├─ background_jobs/
      ├─ export_jobs/
      ├─ snmp_query_results/
      └─ snmp_collection_results/
```

注意 `.local/data/runtime/` 与 `.local/runtime/` 语义不同：前者可保存持久 profile，后者用于任务协议、缓存、临时文件和应用日志。

## 3. 全局资源

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

H3C 私有 MIB 不随仓库分发。导入归档、原始 MIB、参考资料、编译索引和产品比较报告分目录保存，避免把用户资源写回 `resources/`。

## 4. 局点目录

```text
.local/data/sites/<site>/
├─ db/                           # 局点数据库
│  ├─ devices.db                 # 设备、AC/FIT-AP 等主应用数据
│  ├─ tasks.db                   # 任务快照与结构化事件历史
│  ├─ agents.db                  # Agent 配置与运行状态（不保存明文凭据）
│  └─ snmp.db                    # SNMP Center 局点数据库（功能冻结，数据保留）
├─ files/                        # 文件管理业务文件
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
├─ snmp/
│  ├─ raw/
│  ├─ exports/
│  └─ traps/
├─ topology/
│  ├─ snapshots/
│  └─ exports/
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
rail_transit/
├─ mr_raw_mesh/
│  ├─ catalog.sqlite
│  └─ <mr>/
│     ├─ raw/
│     ├─ parsed/
│     ├─ outputs/
│     └─ mesh.sqlite
├─ online_mr/<mr>/sessions/<session>/
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

MR/Mesh 目录型 `mesh.sqlite` 可能只承担目录/入口职责；单文件明细数据库以 `source_files.parsed_db_path` 为准。页面、图表和报告按源文件查询时必须解析到对应明细库。

Online MR 会话结构：

```text
sessions/<session>/
├─ session_meta.json
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
   └─ <session>.zip
```

手工备注保存为会话根目录下 UTF-8 的 `manual_notes.jsonl` 和 `manual_notes.txt`。只有存在运行中目标会话时才持久化；无目标时仅进入当前 UI 日志。

## 6. 数据稳定性边界

- 设备管理、FIT AP 资源和其他主应用数据库默认要求兼容，schema 调整需要单独迁移方案和回滚。
- `tasks.db` 由 `TaskRepository` 幂等初始化，使用 WAL/busy timeout；任务快照与单条事件在同一事务提交，不自动删除业务结果或原始日志。
- `agents.db` 由 `AgentRepository` 幂等初始化，使用 WAL/busy timeout/foreign keys；`agent_configs` 与 `agent_runtime_snapshots` 分表，删除入口只归档配置。Token 不落库，只保存不含秘密的 `credential_reference`。
- `.local/data/sites/<site>/files/network_tools/traffic/parsed/traffic_runs.sqlite` 由 `TrafficRunRepository` 幂等初始化，使用 WAL/busy timeout/foreign keys；`traffic_runs` 保存运行索引，`traffic_agent_tasks` 保存 Controller/Agent 任务映射，`traffic_ping_samples` 只保存新的独立高频 Ping 样本。Token、工具路径、输出绝对路径和任意命令不得写入。
- iPerf interval 的唯一事实源仍是 `files/network_tools/iperf/parsed/iperf_results.sqlite`；Traffic 库只用 `local_iperf_run_id` 关联，不复制 interval。Agent 事件重放通过远端事件键幂等写入既有 interval 表。
- 每个 Traffic Run 的 `events.jsonl` 使用 Controller 单调序号并单独保留 `remote_sequence`；事件、摘要和远端结果只保存相对引用，绝对路径与敏感字段在写入前脱敏。原始 Traffic 文件和正式摘要不属于自动清理范围。
- `online_diagnosis.sqlite`、单文件 Mesh parsed SQLite 等会话解析产物可重建，可在明确需求内调整结构，但必须保留 raw 事实来源并同步 parser/report。
- 不允许把完整 AP Identity shadow items/evidence 或敏感原始字段写入新持久层；当前只允许受控聚合 metadata。
- 导出目标位于用户选择路径或业务 `outputs/`；生成时先写 `.tmp`，成功后原子替换。

## 7. 清理策略

自动清理在主窗口启动后延时执行，默认保留 3 天，只处理：

- `.local/runtime/logs/` 中受认可的运行日志；
- `.local/runtime/` 中受认可的 cache/runtime cache、缩略图、图表/预览缓存；
- `.local/tmp/` 及受认可的 `temp`、`export_tmp`、`download_tmp` 临时目录。

自动清理必须验证解析后的真实路径位于允许目录内，只删除文件并清理空目录。它不得删除局点数据库、配置、业务 raw、outputs 或备份。

系统设置中的手工磁盘清理可管理局点 cache/debug logs，但数据库、配置中心、文件管理、轨道交通、网络工具、备份和配置属于受保护分类。任何扩大清理范围的改动都要有预览、确认、路径约束和测试。
