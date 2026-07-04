# 数据目录规范

NetConsole 是本地桌面工具，数据默认保存在应用根或指定数据根下。所有业务路径应通过 `PathResolver` 获取。

## 顶层目录

当前实现：

```text
<data_root>/
  data/
    config/
      app.json
      settings.json
    sites/
      <site_name>/
        site_meta.json
        db/
        files/
        cache/
    runtime/
      network_profiles.json
      route_profiles.json
  runtime/
    logs/
    cache/
```

说明：

- `data_root` 默认等于应用根；发布或测试可传入不同数据根。
- `data/sites` 是用户工作区目录。
- `demo` 局点必须存在；缺失时会初始化。
- 局点目录名当前使用用户输入的局点名称，允许中文，但禁止路径分隔符和非法字符。
- 每个局点的数据互相隔离，设备、报表、采集记录不能跨局点混用。
- 当前局点由 `data/config/app.json` 记录，并在 UI 顶部显示。

## 局点元数据

当前实现使用：

```text
data/sites/<site_name>/site_meta.json
```

字段包括：

- `display_name`
- `line_name`
- `system_type`
- `network_domain`
- `remark`
- `schema_version`
- `created_at`
- `updated_at`

## 局点数据库

主数据库：

```text
data/sites/<site_name>/db/devices.db
```

任务数据库预留：

```text
data/sites/<site_name>/db/tasks.db
```

数据库结构以当前 `netconsole/core/database.py` 和 repository 为准。新增正式表结构时应补测试和文档；不要用临时旧字段猜测逻辑代替结构调整。

## 文件类数据

当前 `files/` 下主要分区：

```text
files/
  backups/
  imports/
  config_center/
    raw_logs/
    snapshots/
    outputs/
  file_manager/
    downloads/
  rail_transit/
    mr_raw_mesh/
    online_mr/
    trackside_ap/
    car_network_diagnostic/
  network_tools/
    toolbox/
    iperf/
    wireless_scan/
```

## 原始数据和解析结果

必须区分：

- 原始采集日志。
- 解析后的 SQLite / JSON / 缓存。
- 报表输出。
- 备份文件。

示例：

- MR 原始 MESH 日志：`rail_transit/mr_raw_mesh/<mr>/raw/`
- MR 解析库：`rail_transit/mr_raw_mesh/<mr>/mesh.sqlite`
- MR 报表输出：`rail_transit/mr_raw_mesh/<mr>/outputs/`
- 车载 MR 在线采集：`rail_transit/online_mr/<mr>/sessions/<session_id>/`
- 轨旁 AP 采集：`rail_transit/trackside_ap/raw/`
- 轨旁 AP 解析和输出：`rail_transit/trackside_ap/parsed/`、`outputs/`
- iPerf 日志：`network_tools/iperf/raw/server/`、`raw/client/`
- iPerf 解析库：`network_tools/iperf/parsed/iperf_results.sqlite`
- 无线扫描：`network_tools/wireless_scan/raw/`、`parsed/`、`outputs/`

## 约定与待统一事项

- 早期文档中可能出现 `raw/parsed/reports/backups` 的简化结构；当前实现以 `PathResolver` 为准。
- 如果未来统一目录命名，应先更新 `PathResolver`、迁移策略和测试，再更新本文档。
- 文档任务不得直接改目录逻辑。
