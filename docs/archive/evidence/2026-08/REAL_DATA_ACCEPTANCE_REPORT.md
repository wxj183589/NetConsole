# NetConsole Engineering Current/Recent10 Real Data Acceptance Report

日期：2026-08-26
Branch：`main`
验收基线：`538db1c3`
最终 main commit：`afa35c06`
data_root：`D:\NetConsoleData-dev`
生产保护：`PRODUCTION_DATA_TOUCHED=NO`

## 环境

- 11 个 DEV site directory，9 个 `devices.db` 迁移目标。
- 9/9 `PRAGMA quick_check=ok`、authority marker 为 `retired`。
- Legacy HistoryStore 748,883,968 bytes / 1,319,693 事件行已退役为 0。
- 未修改生产数据、业务模型、AP Identity、LLDP 规则；未执行正式目录迁移。

## 性能前后

| 功能 | 优化前 | 当前 DEV 实测 | 结果 |
| --- | --- | --- | --- |
| Site Switch | 8.5–14.4s，backend restart | hzl10 首次 458.3ms、宁波12 首次 931.8ms；Current snapshot hit 3.6/3.7ms | PARTIAL：未在最终 commit 后重跑完整 GUI 交替 |
| FIT-AP | 静态审计 N+1 风险 | 宁波12 resource 992；Radio Current 1,984；批量路径定向测试通过 | PARTIAL：最终 GUI 翻页矩阵未重跑 |
| Trackside snapshot | 72.4s | hzl10 458.3ms、宁波12 931.8ms；868/1,247 行；hit 3.6/3.7ms | PASS（DEV service） |
| Trackside export | 约77.4s | snapshot 777.8ms/1,150.0ms；XLSX render 2,454.4ms/4,387.6ms | PASS（DEV service/process） |
| MESH table | 11.59s，heap 3.22GB | 宁波6号线真实 87,402 links；1,000 行 2,757.6ms | PARTIAL：GUI heap/long-task 未采集 |
| MESH chart/timeline | 既有 profiling 热点 | anchor timeline 776.4ms；chart 无有效 segment | PARTIAL：缺 GUI chart/报告文件矩阵 |

## 问题列表

### PASS

- Radio、Interface、Device LLDP、Device Optical、AP LLDP、AP Optical 均满足 Current + Recent 最大 10 条有效变化。
- 同状态写入不新增 Recent；AP Optical Treatment `(site_id, ap_identity)` 重复键为 0。
- Trackside 页面/导出使用 Current/active snapshot，不再扫描 Legacy HistoryStore；真实两局点快照、并发和 XLSX 文件均完整。
- 迁移 candidate-first、Current parity、idempotence、quick_check 和 no-fallback 门禁通过。

### PARTIAL

- Electron 完整 GUI Site Switch 首次/再次/返回、异常恢复需在最终提交后重新验收。
- MESH GUI 1,000 行滚动、long task、heap、图表和报告导出未完成。
- Task Center、设备导出、MESH 报告的全量 UI 文件恢复矩阵未重跑。

### FAIL

- 真实 DEV 业务路径本轮未发现新 FAIL。
- Python 全量 pytest 仍受既有 architecture/storage guard、fixture/历史基线失败影响，不能写成全量 PASS；详见末轮测试记录。

## 下一步建议

1. 单独建立 Trackside GUI/Export Process 最终验收任务。
2. 单独建立 MESH renderer heap/long-task/scroll/report-export 验收任务。
3. 对 `device_facts_history`、`ac_fit_ap_resource_history`、未认证历史和站点在线摘要等 own history 另行做产品语义决策；未知类型继续保护，不现场删除。
