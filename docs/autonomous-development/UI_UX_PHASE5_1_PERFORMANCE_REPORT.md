# Phase 5.1 性能验收

同一 HZL10 隔离归档、同一 10 分钟窗口，优化前后各五次完整查询。结果均为 2,022 条，顺序与摘要相同。

| 查询 | 优化前 | 优化后 |
| --- | ---: | ---: |
| P50 | 1,359.20 ms | 208.27 ms |
| P95（最近秩） | 1,487.27 ms | 258.69 ms |

详情回查计划从 `SEARCH USING idx_ground_events_timeline(site_id=?)` 改为 `SEARCH USING INTEGER PRIMARY KEY (rowid=?)`，保留局点筛选。无新增索引或数据库迁移。样本只代表该窗口与主机条件。其他业务的完整 SQL 审计，以及并发只读设备任务、TCP/UDP 和 Electron 合计 30 分钟的长稳验收未完成。
