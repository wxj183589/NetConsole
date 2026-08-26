# Real Site Switch Test

日期：2026-08-26
数据根：`D:\NetConsoleData-dev`
代码基线：`538db1c3`
生产保护：`PRODUCTION_DATA_TOUCHED=NO`

## 真实局点服务路径

| 局点 | 首次 metadata/snapshot | 再次进入 Current snapshot hit | 行数 | 结果 |
| --- | ---: | ---: | ---: | --- |
| 杭州地铁10号线 `hzl10` | 458.3ms | 3.6ms | 868 | PASS（服务端） |
| 宁波地铁12号线 | 931.8ms | 3.7ms | 1,247 | PASS（服务端） |

两局点首次快照均 `partial_data=false`。8-way page 并发 wall time：hzl10 578ms、宁波12 982ms；无 SQLite lock 和异常。

## warm handoff / backend lifecycle

- 本轮 Current-only 服务路径未观察到 backend restart、migration、schema mismatch。
- 历史基线 Site Switch 为 8.5–14.4s，主要原因为 backend restart；本报告的服务端耗时不能替代 Electron GUI 交替验收。
- 最终提交后的 Electron 首次进入、再次进入、杭州↔宁波切换返回、interactive 和异常恢复矩阵仍为 PARTIAL。

## 结论

服务端 Current snapshot 与 warm handoff 相关数据路径通过；GUI 级最终验收另立任务，不在 DEV 现场打补丁。
