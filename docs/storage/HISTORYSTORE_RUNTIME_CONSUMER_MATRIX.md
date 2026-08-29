# Legacy HistoryStore Runtime Consumer Matrix

状态：`FULLY_RETIRED_FROM_RUNTIME`（2026-08-29）

本矩阵是本次退役的运行时边界。`HistoryStore`、`TaskHistoryStore` 和旧
`*_history` 表仍可被显式维护工具读取，用于候选迁移、回滚证据或既有维护流程；它们不再是 Backend、Repository、查询服务、导出或启动生命周期的运行时事实源。

## 四类待退役历史

| kind | 退役前 writer | 退役前 reader / fallback | 退役后 runtime writer | 退役后 runtime reader | 新模型 |
| --- | --- | --- | --- | --- | --- |
| `fit_ap_resource` | `AcRepository._append_resource_history`、HistoryStore drain | AC 资源历史、身份补全和 Trackside AP 快照从 HistoryStore/outbox 合并 | `AcRepository.replace_fit_ap_resources` | AC 资源历史与身份补全只读本地 bounded projection | `ac_fit_ap_resources` + `fit_ap_resource_recent`，每个 `ac_device_uuid + ap_uuid` 最近 10 条有效变化 |
| `device_fact` | `DeviceFactRepository` 写入 HistoryStore/outbox | `list_fact_history` 读取 HistoryStore 与旧表 | `DeviceFactRepository.upsert_device_fact` | `list_fact_history` 只读本地 bounded projection | `device_facts` + `device_fact_recent`，每个 `device_uuid` 最近 10 条有效变化 |
| `fit_ap_unauthenticated` | `AcRepository.replace_fit_ap_unauthenticated` 追加 legacy/history | 未认证历史列表与资源 enrichment 从旧表/HistoryStore 读取 | `AcRepository.replace_fit_ap_unauthenticated` | 未认证历史和 enrichment 只读本地 bounded projection | `ac_fit_ap_unauthenticated` + `fit_ap_unauthenticated_recent`，按 AC 与稳定推断身份保留最近 10 条 |
| `station_online_summary` | `AcRepository.save_station_online_summary_history` | 站点在线率历史列表、分页/count 和相关导出从旧表/HistoryStore 读取 | `AcRepository.save_station_online_summary_history` | 站点 Current/Recent 查询只读本地 bounded projection | `station_online_summary_current` + `station_online_summary_recent`，每站最近 10 条有效变化 |

## 退役前后共享入口

| 入口 | 退役前 | 退役后 |
| --- | --- | --- |
| Backend startup / lifespan | 创建 `HistoryStore`、启动 drain、运行时排空 outbox | 不创建、不 drain；health 仅报告 `history_status=retired` |
| `devices.db` current write | current + `history_outbox` / HistoryStore 事件 | current + 同一事务中的 Current/Recent10 projection；候选迁移删除旧 outbox/state |
| AC / Device history query | legacy table、outbox、HistoryStore shard 合并 | 只读本地 Current/Recent10；超出窗口不回溯旧源 |
| Task Center event/result | `TaskHistoryStore` archived event/result fallback | 只读 `tasks.db` current authority；缺失时 fail closed |
| Trackside AP / export | 可能经 Repository 间接使用旧历史 fallback | 经 Repository 使用新模型；不直接访问 `db/history` |
| 新站点初始化 | 生命周期可能实例化 HistoryStore | `PathResolver` 只创建 `db`；`db/history` 不创建 |

## 明确保留的 maintenance-only 读取者

以下入口不属于运行时消费者，不能被 Backend startup、普通采集、查询或导出调用：

- `scripts/maintenance/retire_legacy_history_store.py`：候选库迁移、来源 manifest 校验、Production 授权退役和回滚备份。
- `src/netconsole/services/history_legacy_migration.py`、`src/netconsole/repositories/history_legacy_migration_repository.py`：既有 COPY/verify 维护审计。
- `src/netconsole/repositories/history_store.py`、`src/netconsole/services/history_store.py`：维护工具和隔离测试使用的旧实现；无运行时 owner。
- `src/netconsole/services/site_retention.py` 的 `TaskHistoryStore`：任务保留/归档维护路径，不是任务查询 fallback；当前任务结果 authority 缺失时查询直接失败关闭。

维护入口不享有生产自动删除权限。只有本次显式退役脚本、精确 Production 根和授权 token 同时成立时，才允许删除已核验的注册站点 `db/history` 目录；`tasks.db`、Task Result Blob、MESH、Online MR、Ground、Artifact 和未注册站点不在删除范围。

## 验收断言

- 运行时代码不存在四类 legacy HistoryStore writer、reader 或 fallback。
- `history_outbox`/`history_state` 不再由新运行时写入；候选迁移只按精确表名删除这两个旧内部表，其他 bounded `*_history` 表不受影响。
- 9 个注册站点的 `db/history` 均不存在，`catalog.db` 和月分片数量均为 0。
- 新建站点并执行初始化、Current 写入和查询后，仍不存在 `db/history`。
- Current 事实不因物理退役丢失；每个资源的 Recent10 上限为 10，未变化 heartbeat 不产生新记录。
