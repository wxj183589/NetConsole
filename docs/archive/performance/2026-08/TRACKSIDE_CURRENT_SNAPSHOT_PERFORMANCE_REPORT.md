# Trackside Current Snapshot Performance Report

数据根：`D:\NetConsoleData-dev`；生产保护：`PRODUCTION_DATA_TOUCHED=NO`。
main commit：`afa35c06`

## 真实 DEV

| 局点 | 首次 snapshot | 第二次 cache hit | 行数 | export snapshot | XLSX render |
| --- | ---: | ---: | ---: | ---: | ---: |
| 杭州10号线 `hzl10` | 458.3ms | 3.6ms | 868 | 777.8ms | 2,454.4ms |
| 宁波12号线 | 931.8ms | 3.7ms | 1,247 | 1,150.0ms | 4,387.6ms |

两局点 `partial_data=false`，XLSX 文件存在且可读；导出快照 868/1,247 行。旧基线为 Site Switch 8.5–14.4s backend restart、Trackside snapshot/export 72.4/约77.4s；本次服务端路径未观察到 restart 或全量历史扫描。

## 并发

8-way page 与 4-way export snapshot 在两局点均无异常、无 SQLite lock、行数一致。页面 wall time：hzl10 578ms、宁波12号线 982ms；导出 snapshot wall time：hzl10 1,456ms、宁波12号线 1,898ms。

## 边界

这是 Python service/Export Process 证据，不等于最终 Electron GUI 首次进入、滚动 FPS、long task 或 heap snapshot 验收。GUI 与完整 Task Center 文件操作仍为 PARTIAL。
