# Real Trackside Export Test

日期：2026-08-26
数据根：`D:\NetConsoleData-dev`
代码基线：`538db1c3`
生产保护：`PRODUCTION_DATA_TOUCHED=NO`

## 真实结果

| 局点 | snapshot rows | snapshot build | XLSX render | 文件 | 结果 |
| --- | ---: | ---: | ---: | ---: | --- |
| 杭州地铁10号线 | 868 | 777.8ms | 2,454.4ms | 182,084 bytes | PASS |
| 宁波地铁12号线 | 1,247 | 1,150.0ms | 4,387.6ms | 296,604 bytes | PASS |

两次导出均 `partial_data=false`，生成文件存在且可读。导出快照读取 Current/active snapshot，数据库读取阶段结束后才进入 XLSX render；未读取 Legacy HistoryStore、AP 光衰历史或设备光模块全量历史。

## 对比与边界

- 历史基线：snapshot 72.4s、export 约77.4s。
- 当前 DEV service/process 路径未接近旧耗时，也未观察到全量 build。
- 本结果不等于最终 Electron GUI 保存路径、WPS 打开、取消/重试和 Task Center 全矩阵验收；这些保持 PARTIAL。
