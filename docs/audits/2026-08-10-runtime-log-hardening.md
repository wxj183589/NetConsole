# 运行日志故障韧性 Hardening 审计（2026-08-10）

## 结论

本阶段不改变既有日志目录和总体架构，只补齐日志系统自身发生慢盘、磁盘写失败、文件锁定、突发写入和数据库增量演进时的有界性与恢复能力。Electron 日志继续异步写入，但队列不再无限增长；Python 日志写失败不会逐次格式化 traceback 或向 stderr 制造反馈环；rotation 与 fallback 均有退避、限流和容量上限。

策略事实源仍为 `src/netconsole/resources/log_policy.json`。源码、wheel/package 与 PyInstaller frozen backend 都通过包内相同资源读取，不增加静默硬编码 fallback。

## 故障边界

- Electron queue：soft limit 4 MB，hard limit 8 MB。soft limit 后优先丢弃 DEBUG/INFO；高等级事件可淘汰已排队的低等级事件，hard limit 仍不足时才统计 WARNING/ERROR 丢弃。背压期间最多每 60 秒一条 `LOG_BACKPRESSURE`，恢复后只写一次 `LOG_BACKPRESSURE_RECOVERED`。
- Electron flush：默认最多等待 5 秒，尽量排空队列，但退出流程不会永久等待失效磁盘。
- rotation：失败后按 30、60、120、300 秒退避；退避期间继续追加 active log，不逐条重试 rename。成功后清除 incident 并记录恢复。
- fallback：同 fingerprint 60 秒限流，最大 2 MB，超限后 best-effort 重建；fallback 自身写失败才使用同样受限的 stderr。
- Python logger：fingerprint 包含异常类型、errno/winerror、日志路径和归一化消息。首次输出完整受控诊断，10 秒窗口内抑制重复，最多每 60 秒摘要一次，成功写入后输出一次 `LOG_WRITE_RECOVERED`。
- 日志字段上限：普通 detail 16 KB、结构化 context 32 KB、受控诊断 traceback 256 KB。Backend stderr 转发仍单独受严格限制；raw/artifact 继续 `truncate=false`。

## Housekeeper

保护白名单未放宽。active electron/app、升级审计、活动诊断、最近 5 分钟 WPS、unknown、symlink、raw、artifact、数据库和采集结果不会为了达到 250 MB 目标而删除。

每次扫描显式统计 `total_before_bytes`、`total_after_bytes`、`target_bytes`、`protected_bytes`、`unknown_bytes`、`candidate_bytes` 和 `deleted_bytes`。当总量原先超过 300 MB，删除全部允许候选后仍高于 250 MB，每次 run 最多记录一条 `LOG_HOUSEKEEPING_TARGET_NOT_REACHED`。

故障注入使用测试临时根构造 200 MB active protected、150 MB unknown 和 100 MB rotated removable 稀疏文件。结果只删除 100 MB removable，350 MB protected/unknown 的路径和内容均保留，`target_not_reached=true`。

runtime cleanup 默认保留期已与 backend log 解耦：日志、cache、temporary 分别读取独立策略字段。当前三者均为 7 天；用户在手工清理界面显式选择天数时仍统一覆盖所选项目，保持既有交互。

## Schema Drift 审计

统一 helper `project_row_for_model(row, Model)` 只保留 Pydantic 模型已知字段，随后仍执行 strict `model_validate`。它只解决 additive extra columns，不吞缺失必填字段或已知字段类型错误。

| 消费者 | 模型 | 原风险 | 结论 |
| --- | --- | --- | --- |
| `GroundUnattendedRepository.get_profile` | `GroundUnattendedProfileDTO` | `SELECT *` 的新增列触发 `extra_forbidden` | 已改为统一投影；Supervisor 连续 tick 回归覆盖 |
| Ground raw files Application Service | `GroundRawFileDTO` | repository dict 保留未来列 | 已改为统一投影 |
| Ground operation/latest/active | `GroundOperationDTO` | decoded operation dict 保留未来列 | 已改为统一投影 |
| Trackside AP online status | `TracksideApOnlineStatusRowDTO` | 表面为 row DTO 转换 | 输入来自受控 `station_statistics()` 聚合，不是 SQLite `SELECT *`，无需修改 |
| Trackside AP point table | `TracksideApPointTableRowDTO` | 表面为 row DTO 转换 | 输入来自受控 `build_point_table_rows()`，无需修改 |
| Vehicle MR mapping | `VehicleMrTrainMappingDTO` | 表面为 row DTO 转换 | 输入为 dataclass `asdict` 的固定字段集合，无 schema drift |
| Agent HTTP client DTO | 多个 API model | 外部 payload 可能含新增字段 | 既有实现已按 `model_fields` 投影，无需重复修改 |
| Repository `dict(row)` 消费者 | dataclass/普通 dict | SQLite 行字段随 schema 增长 | 不进入 `extra=forbid` Pydantic DTO，不属于本类风险 |

没有全局改成 `extra=ignore`，也没有全局禁止 `SELECT *`。

## Frozen 资源

原 clean-build import graph 只会复制导入到的 Python 模块和显式文件，`("src/netconsole", "netconsole")` 目录项本身不会把 `log_policy.json` 放入 datas，存在 frozen backend 缺失策略资源的真实缺口。

修复后 clean build 将 `src/netconsole/resources/log_policy.json` 显式映射到 `netconsole/resources`，clean-build lock 同步登记 source、destination 和 packaged path。release test 会解析 staging 资源；Electron package smoke 会检查 `resources/backend/_internal/netconsole/resources/log_policy.json` 并核对 20 MB、7 天、4/8 MB 和 raw 不截断。frozen backend 的成功启动与该资源检查共同构成运行时验收。

## 自动化证据

- Electron logger：慢盘 10,000 events、8 KB 测试 hard cap、等级感知丢弃、背压摘要/恢复、EBUSY rotation backoff、fallback 限流限容，19 项通过。
- Python logger/policy：PermissionError、ENOSPC、EBUSY 各 1,000 次，首条/摘要/恢复与敏感字段脱敏，17 项通过。
- Ground schema/suppression：future profile/raw/operation 列、strict 类型/必填校验、Supervisor 连续 tick 和 61 秒 downtime，42 项通过。
- Housekeeper/cleanup/system maintenance：protected/unknown 故障注入和独立 retention，44 项通过。
- raw 完整性复用 `test_mesh_storage_service.py` 的 10 KB、64 KB、256 KB、1 MB SHA-256 回归。

Electron 全量测试 252 项、Web 系统维护/日志相关测试 11 项、Python 本轮定向组合 184 项均通过。合并最新主线后的完整 pytest 为 3729 passed、2 skipped；剩余 6 项是主线新增 Online MR/架构 README/命令审计/图表 token 守卫及既有 BaseData UI Guard，不属于本轮日志改动。

此前 `win-unpacked` 的 package smoke 停在冻结设备数据库迁移：历史 fixture 的空 `ac_fit_ap_resources` 表缺少 `ac_device_uuid` 与 `ap_uuid`，而随后 schema trigger 已依赖这些字段。当前实现只在该表为空时重建为完整 schema；若表内已有记录则明确拒绝迁移，不会静默删除业务数据。源码层正反迁移测试已覆盖；本提交的完整 package smoke 与正式安装包验收仍由发布就绪审计记录，不在本节提前宣称通过。

## 剩余风险

自动化 mock 能确认状态机与限流，但不能完全替代特定杀毒软件、真实 NTFS 锁竞争或物理磁盘耗尽下的行为。正式安装包构建受构建环境、签名和依赖状态约束；长时 soak 需要单独持续运行窗口。unknown 文件仍选择保护并报警，这是防止误删业务证据的有意取舍。
