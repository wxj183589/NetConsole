# TRACKSIDE AP 数据库身份审计

- 最终状态：`LOCAL_PASS_DATABASE_VERIFIED`
- 产品：NetConsole 旧版 v1.5.15
- Branch：`codex-A/trackside-ap-template-station-closure-20261116`
- HEAD：`3f110cf85ec289b8b4d986c8dee40fe646de9d44`
- 核查范围：只读；未重新导入、未保存、未迁移数据库。

## 实际数据链路

| 项目 | 实际值 | 证据 |
|---|---|---|
| Electron 数据根 | `D:\NetConsoleData-dev` | `runtime/logs/electron-20261117-015458-0001.log` 中 `NETCONSOLE_STORAGE_ROOT_SELECTED` |
| Backend 数据根 | `D:\NetConsoleData-dev` | `runtime/logs/app-20261117-015501-0001.log` 中 `DATA_ROOT_CONTEXT` |
| Site | `hzdt-09` / 杭州地铁9号线 | Backend site switch 与报告记录 |
| SQLite 实际路径 | `D:\NetConsoleData-dev\sites\hzdt-09\db\devices.db` | Backend `DATABASE_STARTUP_MAINTENANCE` 与 `TRACKSIDE_AP_PLAN.REPOSITORY_LOADED` |
| 数据库大小 | `17,305,600` bytes | 只读文件属性 |
| 数据库 SHA-256 | `e372ddfad4cd8026f514ca2da70e5cf7c811ae8f81617739533a3aa35389f3ef` | 当前文件哈希 |
| WAL | 存在，0 bytes | 未执行 checkpoint 或清理 |
| SHM | 存在，32,768 bytes | 只读 WAL 访问产生/保留的 SQLite sidecar |

`devices.db` 是轨旁 AP 基础资料的实际数据库。`agents.db`、`tasks.db`、`site_ssh_credentials.sqlite3` 以及其他 Site 下的 SQLite 文件不是本次 AP 基础资料存储目标。AP 业务记录位于 `ap_extension_points`，不是 `devices` 表。

## SQLite 只读核查

连接使用 SQLite URI `mode=ro`，并执行 `PRAGMA query_only=ON`。结果：

- `query_only=1`
- `journal_mode=wal`
- `integrity_check=ok`
- 未执行 INSERT、UPDATE、DELETE、迁移、VACUUM、checkpoint 或 WAL/SHM 删除。

只读 WAL 访问可能物化或更新 `-shm` 协调文件；本次没有业务表写入，主数据库文件内容和哈希未改变。

## AP 统计

`ap_extension_points` 共522行，其中31行是 `belong_type='__base_station__'` 的站点主资料，491行是 AP 业务资料：

| 指标 | 实际查询结果 |
|---|---:|
| AP 总数 | 491 |
| 正线 MAINLINE | 422 |
| 车辆段 DEPOT | 44 |
| 停车场 PARKING_YARD | 25 |
| 非空正式 station_id | 422 |
| 无效非空 station_id | 0 |
| 跨 Site station_id | 0 |
| 重复 AP MAC | 0 |
| 重复 AP 名称 | 0 |
| 交换机非空 | 491 |
| 端口非空 | 491 |

正线 AP 的422个 `station_id` 均能在同一 `site_id=hzdt-09` 的31条站点主资料中找到；车辆段和停车场的69条 AP 保持空 `station_id`，没有伪造正线站点关联。

## 数据安全

```text
PRODUCTION_DATA_MODIFIED=0
DEV_REAL_DATA_CONTENT_MODIFIED=0
AP_RECORDS_MODIFIED=0
STATION_RECORDS_MODIFIED=0
DATABASES_DELETED=0
USER_WORKBOOKS_MODIFIED=0
```

补充：本轮只读 SQLite 访问后保留了 `devices.db-shm` sidecar，未删除或清理它；这不代表业务记录或主数据库内容被修改。

## 21个正式正线站点映射

| 业务站序 | 站名 | 实际 station_id | Site | 状态 |
|---:|---|---|---|---|
| 11 | 观音塘 | `station:5d9bedb16dac` | `hzdt-09` | enabled |
| 12 | 新业路 | `station:40c3b77ed754` | `hzdt-09` | enabled |
| 13 | 钱江路 | `station:a4395faf648f` | `hzdt-09` | enabled |
| 14 | 江河汇 | `station:38f97ace5597` | `hzdt-09` | enabled |
| 15 | 三堡 | `station:4d18471a239d` | `hzdt-09` | enabled |
| 16 | 御道 | `station:7fa96f73fbb0` | `hzdt-09` | enabled |
| 17 | 五堡 | `station:ee42d20bd8a6` | `hzdt-09` | enabled |
| 18 | 六堡 | `station:fa6fb3f0c423` | `hzdt-09` | enabled |
| 19 | 红普南路 | `station:101184a8d75d` | `hzdt-09` | enabled |
| 20 | 九睦路 | `station:faadb3db157c` | `hzdt-09` | enabled |
| 21 | 客运中心 | `station:94c1ddf54c41` | `hzdt-09` | enabled |
| 22 | 乔司南 | `station:a72f109d3ff0` | `hzdt-09` | enabled |
| 23 | 乔司 | `station:2bb2c381a95c` | `hzdt-09` | enabled |
| 24 | 翁梅 | `station:96d66b54464a` | `hzdt-09` | enabled |
| 25 | 临平南高铁站 | `station:dfc0b2d9920e` | `hzdt-09` | enabled |
| 26 | 南苑 | `station:53fa57a1fb11` | `hzdt-09` | enabled |
| 27 | 临平 | `station:1e45fc05f85e` | `hzdt-09` | enabled |
| 28 | 邱山大街 | `station:28f664ece45a` | `hzdt-09` | enabled |
| 29 | 荷禹路 | `station:1a9d419593fb` | `hzdt-09` | enabled |
| 30 | 五洲路 | `station:ee2c319673c5` | `hzdt-09` | enabled |
| 31 | 昌达路 | `station:0f0599c1f124` | `hzdt-09` | enabled |

数据库中另有正式站点主资料的历史/规划节点及通用车辆段、停车场节点；本表要求的21个正线站点均唯一且属于当前 Site。
