# 局点数据包格式

NetConsole 使用 ZIP 容器传递局点数据。`.ncsite` 与 `.ncresult` 均在写入前完成 manifest、SHA-256、路径、符号链接、解压大小和 SQLite 完整性校验；校验或预检阶段不会写业务目录。

## 包类型

| 类型 | 扩展名 | 用途 | 导入语义 |
| --- | --- | --- | --- |
| `full_migration` | `.ncsite` | 用户自己的电脑之间换机、完整备份、灾难恢复 | 无需密码，直接恢复完整局点和包内设备凭据 |
| `sanitized_share` | `.ncsite` | 问题分析、交给其他人或公开交流 | 恢复非秘密数据，相关设备标记为需要重新录入凭据 |
| `field_collection` | `.ncsite` | 主电脑下发现场采集资料 | 建立同一 `site_uuid` 的现场基准 |
| `collection_return` | `.ncresult` | 现场采集后回传增量 | 对同一 `site_uuid` 预检后增量合并 |

当前格式版本为 4。旧版 `format_version=1/2` 的 `.ncsite` 继续兼容读取，但只按无凭据旧包处理；它们不能因类型名称为 `full_migration` 而恢复已被旧流程清除的凭据。曾短暂生成的实验性 `format_version=3` 加密包不属于当前兼容输入；需要从仍持有原局点数据的来源端重新导出 v4 包。

## 通用 manifest

版本 4 的 `manifest.json` 至少包含：

```text
format / format_version / package_id / package_type
site_id / site_uuid / site_name / site_revision / base_revision
created_at / source_platform / contains_credentials / credential_reentry_count
databases / artifacts / checksums
```

新生成的 `full_migration` 与 `sanitized_share` v4 包还携带可选扩展 `site_scope / relation_summary`；`field_collection`、`collection_return` 继续使用各自的同步 manifest 合同。

`full_migration` 还明确记录 `encrypted=false`。包中不包含加密参数、`payload.enc`、迁移密码或凭据冲突策略。

`site_id` 是 Registry 的稳定内部标识；`site_uuid` 是跨电脑判断“是否同一局点”的不可变标识。显示名称可修改，不能参与匹配。新局点会创建 `site_uuid`；Legacy 局点必须先完成只读审计，才允许建立同步标识和导出现场/回传包。

`site_scope.source_directory_name` 记录来源端实际物理局点目录名。`relation_summary.device_groups` 记录关系 schema、来源 scope、分组数、已分组设备数、孤儿引用数以及分组定义/成员关系摘要。真实分组定义和 `device -> group` 关系仍只存于 `devices.db`，manifest 只用于导入前后的无损校验，不建立第二份业务事实。存在扩展字段时会校验 schema、字段类型、来源物理 scope 和摘要；未知 schema 会停止导入。旧 v1/v2/v4 包缺少这些新增字段时继续兼容：导入只在 staging 数据库中可唯一确定一个分组 scope 且没有孤儿引用时重绑定；多 scope 或关系损坏会停止发布。

## 内容与安全边界

完整迁移包是普通 ZIP，直接包含 `manifest.json`、`checksums.json`、`README.txt` 和完整 `site/` 快照。SQLite 通过 Backup API 生成一致副本，每个文件都有 SHA-256；导入先完成路径、符号链接、解压大小、checksum、manifest 和 SQLite 完整性校验，全部成功后才原子发布。任何校验失败都不会发布半个局点。

恢复为不同局点标识或替换 Legacy 中文物理目录时，导入在 staging 中把 `device_groups.site_id` 重绑定为目标物理目录名；分组 ID、名称、排序、空组以及 `devices.group_id` 全部保持不变。重绑定前后会校验分组数量、成员数量、孤儿引用和两类摘要，失败时不发布目标局点。

完整迁移包保留设备用户名、SSH/Telnet 密码、SNMP community 和隧道凭据。导入新局点或替换已有局点都直接使用包内数据库及其凭据，不提供 `credential_policy`，也不会因来源电脑不同设置 `needs_reentry`。它不要求或接收迁移密码，也不生成加密载荷；导出页和导入预检会明确警告“完整迁移包包含设备用户名和密码”。该包不提供机密性，必须只保存到可信位置。

脱敏分享包、现场采集包和采集回传包均不包含秘密。现场采集包仅下发 `site_meta.json`、清洗后的 `db/devices.db`、配置中心资料和车内通信点表，不下发任务历史、大量原始日志或历史报告。导入现场包后，本机在 `sync/baselines/<baseline_id>/` 保存不可变基准。

采集回传包包含：

- 基准 ID 与基准 revision；
- 基准/当前的清洗后 `devices.db` 副本；
- 现场 `tasks.db` 副本（存在时）；
- 基准以后新增或变更的非数据库文件、其 SHA-256、来源电脑和可识别任务 ID；
- 基准中已消失文件的删除请求。

所有包都排除 SSH 主机密钥确认、本机 Agent 地址、窗口布局、运行队列、缓存、锁、`.part`、WAL/SHM 和本机运行日志。除 `full_migration` 外，其他包还必须清空 `devices` 表中的密码、SSH/Telnet 密码、SNMP community 和隧道密码。清洗前确有凭据或旧包可确认已配置认证方式的设备会获得非秘密 `needs_reentry` 标记；manifest 的 `credential_reentry_count` 只记录受影响设备数。

导入 `sanitized_share` 或旧无凭据 `.ncsite` 后，设备列表显示“需重新录入”，API 返回 `credential_status / credential_source / credential_error_code`。连接测试在创建 Job 前返回 `CREDENTIAL_REENTRY_REQUIRED`，不会使用空密码尝试认证。设备编辑时密码留空保留原值，输入新密码会替换并在凭据完整后清除重录标记，只有显式“清除已保存值”才删除秘密；普通 DTO 只返回配置状态，不回传旧明文。Electron 本机编辑页可在用户点击眼睛后，通过 Desktop/`127.0.0.1`/短期会话保护接口按字段读取，关闭编辑器即清理本次显示值。完整迁移包导入后若真实凭据完整则保持 `available / local_database`。

## 回传预检与合并

回传包必须匹配本机一个 `site_uuid`。预检显示新增/重复文件、任务、可自动更新记录、冲突、删除请求、无效数据和预计空间；实际写入前创建 `files/backups/sync-import-<id>/` 恢复快照。

- 原始文件按 SHA-256 去重；同路径不同内容不覆盖，转存为 `files/sync-imports/<日期>/<来源电脑>/<导入ID>/...`。
- `tasks.db` 按 `task_id`、`event_id` 合并；完整成功优先于部分完成、失败、已取消和运行中，同等级仅在回传结果更完整时更新。
- `task_results`、ref-only snapshot/event 和 `online_mr_task_sessions` 在同一事务中
  合并并校验引用。Online MR mapping 的 `site_id` 可匹配目标 Registry stable
  ID，或目标 `SiteRecord` 明确提供的显示名/物理目录名 alias；任意其他局点值
  继续 fail closed，不能从回传数据自行扩展 alias。
- `devices`、`collect_runs`、`device_facts`、FIT-AP/AP 实体及其带 UUID 的快照/历史记录按稳定 UUID 三方合并。双方修改同一字段且值不同，会要求选择本地值、回传值或手工值。
- 未提供稳定 UUID 的旧基础资料或派生表不会被按本地自增 ID 猜测合并；预检会计入“未支持记录”，导入时保留本机数据，不会静默覆盖。
- 删除请求默认只展示和记录，不自动删除设备、AP、列车、原始文件、报告或历史数据。

回传合并在数据库事务中执行；文件先复制到受控位置。任何失败都会恢复数据库快照并删除本次新增文件。
