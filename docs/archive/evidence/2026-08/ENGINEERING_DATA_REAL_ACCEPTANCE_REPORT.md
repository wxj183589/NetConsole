# Engineering Data Real Acceptance Report

## 环境

- main commit：`afa35c06`
- data_root：`D:\NetConsoleData-dev`
- active migration targets：9；site directories：11
- devices.db：只读验收；9/9 quick_check ok
- Legacy HistoryStore：748,883,968 bytes -> 0
- `PRODUCTION_DATA_TOUCHED=NO`

## 真实结果

| 功能 | 旧基线 | 当前 DEV 实测 | 结果 |
| --- | --- | --- | --- |
| Site Switch | 8.5–14.4s，backend restart | hzl10 458.3ms、宁波12 931.8ms 首次；cache hit 3.6/3.7ms | PARTIAL：GUI 交替未重跑 |
| FIT-AP | 静态审计 N+1 风险 | 宁波12当前资源 992、Radio Current 1,984；定向批量测试通过 | PARTIAL：最终 GUI/翻页未重跑 |
| Trackside snapshot | 72.4s | 868/1,247 行，458–932ms；hit 3.6–3.7ms | PASS（服务端） |
| Trackside export | 约77.4s | XLSX 2.45/4.39s，文件完整 | PASS（DEV service/process） |
| MESH table | 11.59s，heap 3.22GB | 宁波6号线真实 87,402 links，1000 行 2,757.6ms | PARTIAL：GUI heap 未采集 |
| MESH chart/timeline | profiling 约17.06s | 真实 anchor timeline 776.4ms；chart anchor 无有效 segment | PARTIAL |

## 问题列表

### PASS

- 四类 Current/Recent10 与 treatment 唯一性门禁。
- Legacy HistoryStore 退役和 no-reinflation 拦截。
- Trackside page/export 真实 DEV 两局点、并发、XLSX 文件。

### PARTIAL

- Electron GUI warm handoff 交替、返回、异常恢复未在最终提交后重做。
- MESH GUI scroll/FPS/heap/long task 与报告导出未完成。
- Task Center、设备导出和完整文件恢复矩阵未重跑。

### FAIL / 门禁未通过

- 本轮真实 DEV 业务数据未发现新业务失败。
- Python 全量 `pytest -q` 为 `4480 passed, 26 failed, 2 skipped`；失败含既有架构/fixture/历史基线范围，未在验收现场打补丁，不把全量套件写成 PASS。

## 下一步

1. 独立创建 Trackside GUI/Export Process 最终验收任务。
2. 独立创建 MESH GUI heap/long-task/滚动和 report export 验收任务。
3. 对未纳入四类的 own history 做产品语义决策；保持 `UNKNOWN=PROTECT`。
