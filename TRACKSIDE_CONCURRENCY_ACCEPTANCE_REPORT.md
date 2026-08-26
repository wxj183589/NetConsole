# Trackside Concurrency Acceptance Report

日期：2026-08-26
数据根：`D:\NetConsoleData-dev`
main commit：`afa35c06`
生产保护：`PRODUCTION_DATA_TOUCHED=NO`

## 结果

只读 DEV 数据库执行 8-way page 与 4-way export snapshot 并发：

| 局点 | page wall | export snapshot wall | rows | 结果 |
| --- | ---: | ---: | ---: | --- |
| 杭州地铁10号线 | 578.0ms | 1,456.0ms | 868 | PASS |
| 宁波地铁12号线 | 981.7ms | 1,898.0ms | 1,247 | PASS |

所有 worker 返回行数一致，无异常、无 SQLite lock、无 partial data。XLSX 并发输出均生成；未写入生产根。该证据覆盖 service/process 并发，不覆盖最终 GUI 滚动或 WPS 打开。
