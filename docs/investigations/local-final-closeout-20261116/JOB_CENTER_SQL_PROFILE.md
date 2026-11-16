# Job Center SQL 深度剖析

状态：PASS（定向本地剖析）

使用隔离合成数据库验证 80 个任务、1440 条事件，覆盖全部生命周期状态及列表、详情、日志、汇总读取。优化点是详情/日志读取优先使用 Task Authority Index，避免对每个请求再执行一次 `_task_exists` 点查询；没有改变旧 fixture 在缺少索引时的站点回退语义。

| 场景 | before wall p50/p95(ms) | after wall p50/p95(ms) | before SQL p50 | after SQL p50 |
| --- | ---: | ---: | ---: | ---: |
| detail | 1.891 / 2.073 | 1.430 / 1.544 | 23 | 19 |
| logs | 1.497 / 1.698 | 1.066 / 1.314 | 10 | 6 |
| list_all | 6.073 / 6.903 | 6.022 / 7.671 | 18 | 18 |
| summary | 5.325 / 5.527 | 5.338 / 5.662 | 18 | 18 |

详情和日志 SQL 数量及耗时下降；列表、汇总查询未增加 SQL 次数。执行计划保持使用任务快照可见索引、任务主键唯一索引和事件序号索引；列表的临时排序行为仍存在，未在本轮扩大范围重构。

测试脚本：`scripts/dev/job_center_sql_profile_20261116.py`

安全边界：数据库为任务专属合成 fixture，`PRODUCTION_DATA_MODIFIED=0`，`DATABASES_REMOVED=0/0`，`MAINTENANCE_AUTHORIZED=NO`。
