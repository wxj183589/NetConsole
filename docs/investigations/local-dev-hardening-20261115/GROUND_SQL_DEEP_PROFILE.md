# Ground SQL 深度画像

状态：`PARTIAL`。

本轮在独立 synthetic fixture 上完成了 Ground Repository 的 60 次迭代画像；没有打开生产或真实开发数据。最终证据：`D:\study\NetConsole-Workspace\diagnostic\local-dev-hardening-20261115\sql-profile-final\metrics.json`。

## 当前结果

| 模块 | P50 SQL | P95 SQL | P95 wall ms | P95 SQL ms |
| --- | ---: | ---: | ---: | ---: |
| Inventory | 5 | 5 | 3.689 | 1.604 |
| Heartbeat inventory state | 4 | 4 | 2.449 | 1.586 |
| Heartbeat snapshots | 4 | 4 | 2.809 | 1.441 |
| Quick Ping runs | 6 | 6 | 2.309 | 1.131 |
| Quick Ping query | 7 | 7 | 2.586 | 1.457 |
| Quick Ping events | 4 | 4 | 2.593 | 1.488 |
| Raw files | 4 | 4 | 2.197 | 1.321 |

Quick Ping 列表/查询已由每个 run 的两次子查询改为同一读快照中的批量 stats/runtime 查询；在本次 20 行画像中 SQL 调用从 44/45 降至 6/7，未改变统计字段或事件时间。

## 未完成边界

本画像脚本尚未把 Syslog 突发写事务、解析队列和 Job Center 列表单独纳入同一张 SQL 计数表；这些部分通过 HTTP/任务状态回归覆盖，但 SQL 深度指标应在后续专项中补齐。因此不能把本报告写成 Ground 全域性能 PASS，也没有通过删除业务数据降低 SQL 数量。
