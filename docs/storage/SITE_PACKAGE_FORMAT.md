# 局点数据包格式

NetConsole 使用 ZIP 容器传递局点数据。`.ncsite` 与 `.ncresult` 均在写入前完成 manifest、SHA-256、路径、符号链接、解压大小和 SQLite 完整性校验；校验或预检阶段不会写业务目录。

## 包类型

| 类型 | 扩展名 | 用途 | 导入语义 |
| --- | --- | --- | --- |
| `full_migration` | `.ncsite` | 换机、完整备份、灾难恢复 | 恢复为新局点或先备份再替换 |
| `field_collection` | `.ncsite` | 主电脑下发现场采集资料 | 建立同一 `site_uuid` 的现场基准 |
| `collection_return` | `.ncresult` | 现场采集后回传增量 | 对同一 `site_uuid` 预检后增量合并 |

旧版 `format_version=1` 的 `.ncsite` 继续按完整迁移包读取；它没有跨电脑合并所需的基准和 UUID，不能作为采集回传包。

## 通用 manifest

版本 2 的 `manifest.json` 至少包含：

```text
format / format_version / package_id / package_type
site_id / site_uuid / site_name / site_revision / base_revision
created_at / source_machine_id / database_schema_version
checksums / contains_credentials=false
credential_reentry_count
```

`site_id` 是 Registry 的稳定内部标识；`site_uuid` 是跨电脑判断“是否同一局点”的不可变标识。显示名称可修改，不能参与匹配。新局点会创建 `site_uuid`；Legacy 局点必须先完成只读审计，才允许建立同步标识和导出现场/回传包。

## 内容与安全边界

完整迁移包包含经过清洗的 `site/` 快照。现场采集包仅下发 `site_meta.json`、清洗后的 `db/devices.db`、配置中心资料和车内通信点表，不下发任务历史、大量原始日志或历史报告。导入现场包后，本机在 `sync/baselines/<baseline_id>/` 保存不可变基准。

采集回传包包含：

- 基准 ID 与基准 revision；
- 基准/当前的清洗后 `devices.db` 副本；
- 现场 `tasks.db` 副本（存在时）；
- 基准以后新增或变更的非数据库文件、其 SHA-256、来源电脑和可识别任务 ID；
- 基准中已消失文件的删除请求。

包从不包含 Token、密码、设备凭据、SSH 主机密钥确认、本机 Agent 地址、窗口布局、运行队列、缓存、锁、`.part`、WAL/SHM 或本机运行日志。`devices` 表中的密码、SSH/Telnet 密码、SNMP community 和隧道密码始终清空。清洗前确有凭据或旧包可确认已配置认证方式的设备会在包内获得非秘密 `needs_reentry` 标记；manifest 的 `credential_reentry_count` 只记录受影响设备数。

导入普通 `.ncsite` 后，设备列表显示“需重新录入”，API 返回 `credential_status / credential_source / credential_error_code`。连接测试在创建 Job 前返回 `CREDENTIAL_REENTRY_REQUIRED`，不会使用空密码尝试认证；重新保存当前电脑的凭据后状态恢复为 `available / local_database`。本流程不引入凭据加密，不改变当前电脑现有凭据存储，也不提供独立凭据迁移包。

## 回传预检与合并

回传包必须匹配本机一个 `site_uuid`。预检显示新增/重复文件、任务、可自动更新记录、冲突、删除请求、无效数据和预计空间；实际写入前创建 `files/backups/sync-import-<id>/` 恢复快照。

- 原始文件按 SHA-256 去重；同路径不同内容不覆盖，转存为 `files/sync-imports/<日期>/<来源电脑>/<导入ID>/...`。
- `tasks.db` 按 `task_id`、`event_id` 合并；完整成功优先于部分完成、失败、已取消和运行中，同等级仅在回传结果更完整时更新。
- `devices`、`collect_runs`、`device_facts`、FIT-AP/AP 实体及其带 UUID 的快照/历史记录按稳定 UUID 三方合并。双方修改同一字段且值不同，会要求选择本地值、回传值或手工值。
- 未提供稳定 UUID 的旧基础资料或派生表不会被按本地自增 ID 猜测合并；预检会计入“未支持记录”，导入时保留本机数据，不会静默覆盖。
- 删除请求默认只展示和记录，不自动删除设备、AP、列车、原始文件、报告或历史数据。

回传合并在数据库事务中执行；文件先复制到受控位置。任何失败都会恢复数据库快照并删除本次新增文件。
