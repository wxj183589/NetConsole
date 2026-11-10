# 隔离 catalog SHA 变化归因

## 对比范围

目标 catalog：

`D:\study\NetConsole-Workspace\test-data\NetConsole\mesh-phase11-8-run-001\sites\宁波地铁12号线\files\rail_transit\mr_raw_mesh\catalog.sqlite`

第七轮开始前只读基线：size=110592，mtime_ns=`1794275810287611300`，SHA256=`101ba556dabcd72d0e6e51c42572f8e86ebf63d79b386d0f24d831535e0fc3dd`。

两次真实 Electron 运行结束后的最终只读快照：size=110592，mtime_ns=`1794281585822946600`，SHA256=`127655fa3cc4cf890b4daed0a695f70169eddd9af100c07e885c935e012747af`。

没有恢复 SHA、mtime、WAL/SHM，也没有删除或回写 catalog。

## 表/行/字段差异

| 表 | 开始行数 | 结束行数 | 变化 |
|---|---:|---:|---|
| `mesh_catalog_index_state` | 1 | 1 | singleton=1 的 `updated_at` 从 `2026-11-10 09:56:45.327` 更新为 `2026-11-10 11:33:05.056`；status/counts/last_error 不变 |
| `mesh_session_index` | 1 | 1 | session `80716c07-6bd9-47d8-b76d-ace1e55624d1:1` 全字段保持不变；`source_revision`、统计量、`updated_at=2026-11-09 23:01:46.834` 不变 |
| `mesh_source_fingerprints` | 1 | 1 | content/raw SHA、mr/source id、filename 不变；唯一变化是同一行 `updated_at` 从 `2026-11-10 09:56:45.323` 更新为 `2026-11-10 11:33:05.053` |
| `mesh_source_lifecycle` | 3 | 3 | 行、health、reason、时间和 details 不变 |
| `mesh_source_lifecycle_events` | 3 | 3 | 没有新增事件 |

表名集合、记录数和 schema 版本在运行前后没有新增/删除；目标 `mesh.sqlite`、parsed DB、raw gzip 内容 SHA/size 也保持不变：

- `mesh.sqlite`：249856 bytes，SHA `7d45597929601c48848ba65471f0270eaca5489cd6cd662b2af74d45cdd3a191`。
- parsed DB：156786688 bytes，SHA `2630d9cf03cd5ac3146e11d449db5964dd8e7dd97666136d56eb09aa40b77271`。
- raw gzip：2892510 bytes，SHA `f53990d5448f297ea8cbc6901d87132fcf3f616c61149feaa4e875829a3b0fc7`。

## 已证实原因

真实 Electron 使用 `--isolated-test-data`，TEST runtime 的 `MeshAnalysisQueryService._schedule_catalog_backfill()` 会调用 `MeshCatalogIndexService.rebuild_now(site_id)`。`_rebuild()` 的正常流程依次写入：

1. `mesh_catalog_index_state.status=discovering/enriching/ready` 及当前时间 `updated_at`；
2. 已存在来源的 `mesh_source_fingerprints` upsert，repository 为冲突行生成当前 `updated_at`；
3. 因 `source_revision` 未变化，`mesh_session_index` 不重算、不更新。

因此分类为：

`EXPECTED_RUNTIME_WRITE`

这是隔离 TEST 运行的目录索引状态刷新，不是外部并发写、原始采样写入或 schema migration。catalog 读路径在 TEST 模式仍会刷新 metadata；若未来要求“所有查询绝对只读”，应另开范围修正这一运行策略，本轮不扩大架构。
