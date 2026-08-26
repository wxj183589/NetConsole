# NetConsole Phase2 Real Data Acceptance Report

日期：2026-08-26

## 环境

- 验收起点 HEAD：`e8b826b9b6d3e799fc2bd71afe07ece07b4b2769`；工作区含本轮 bounded current/history 变更。
- branch：`main`
- data_root：`D:\NetConsoleData-dev`
- `D:\NetConsoleData`：未访问、未修改。
- 本轮桌面启动、查询、任务和导出产生的运行数据均留在 DEV 根。

## 性能前后

| 功能 | 优化前 | 当前 | 结果 |
| --- | --- | --- | --- |
| Site Switch | 8.5–14.4s，backend restart | 当前会话 backend health 2.83s、desktop interactive 5.81s；认证 AC API 200；完整 GUI 交替未重跑；历史 warm metadata 362–453ms | PARTIAL |
| FIT-AP | 静态审计疑似 N+1 | 宁波12 resource 992；首次 92.31ms/12 SQL；page 319.60ms/32 SQL；详情 324.55ms/39 SQL；批量明细生效 | PASS |
| Trackside snapshot | 72.4s 导出 snapshot 基线 | 第一次直接快照 936.59ms/1247 行；第二次 cache hit 3.53ms；导出路径仍受 enrichment 影响 | PARTIAL |
| Trackside export | 约 77.4s | 直接导出 28,140.38ms；snapshot 25,289ms；render 1,895ms；正式历史任务约 74.8s | PARTIAL |
| MESH table | 11.59s，heap 3.22GB | 99,299 link 总量；1000 行 page 633.13ms；1000 timeline 517.37ms | PASS（GUI 滚动待补） |
| MESH chart | profiling 约 17.06s | active path 1,056ms、1,000 points、1.06MB；trackside chart 1,607.57ms、3,319 points、2.22MB | PASS（GUI long-task 待补） |

## Job Center 与恢复

宁波 12 号线 Task Center 数据库只读检查成功；导出任务可查询，重建 `TaskApplicationService` 后可恢复最近完成任务和 Artifact 状态。没有发现性能改动破坏 Job、Export Process 或终态恢复。DEV 任务和 Artifact 不清理、不迁移。

## 问题列表

### PASS

- DEV 环境可读，站点和主要数据规模符合真实压力场景。
- FIT-AP 页面批量加载和详情批量明细查询通过，无 N+1 证据。
- MESH 服务端分页、图表 source series budget 和当前真实查询耗时通过。
- Trackside Export Job、progress、XLSX 生成、Artifact 发布和恢复通过。
- 最终 commit 桌面启动通过，当前启动日志无 restart/migration/schema mismatch。
- bounded LLDP/optical migration 后 9 个 DEV active site `quick_check=ok`，旧目标历史表为 0，历史最大深度不超过 10，treatment 重复键为 0。

### PARTIAL

- 最终 commit 尚未完成 GUI 局点交替、返回和异常恢复实测，因此 Site Switch 不能标 PASS。
- Trackside export 仍接近 77.4s，宁波 12 号线 snapshot build 仍约 69.7s。
- Snapshot hit/miss、筛选刷新、设备导出、MESH 报告导出和完整 GUI 文件操作序列未全部完成。
- MESH 真实 GUI 滚动 FPS、long task 和 heap trace 未在本轮重新采集。
- 真实 GUI 的“首次进入/再次进入/返回”点击序列与 Task Center 全部文件操作矩阵仍未完全补齐。
- 宁波 10 号线个别 FIT-AP radio detail 缺失，是数据缺口。

### FAIL

- 产品真实数据操作本轮没有发现新的业务失败。
- 8 并发（轨旁页面 4、轨旁导出 2、FIT-AP 查询 2）全部完成，锁错误 0；并发导出输出完整，详见 `TRACKSIDE_CONCURRENCY_ACCEPTANCE_REPORT.md`。
- 集成 Python 全量门禁仍为 `4486 passed, 2 skipped, 12 failed`：失败集中在已有 architecture/storage README、Ground archive/usability 和 Demo LLDP 历史基线；Phase2 定向测试、Renderer、Electron、typecheck/build 均通过。这些失败未在验收阶段现场修补。

## 下一步建议

1. 单独创建 Trackside snapshot HistoryStore 性能任务，只研究历史分片查询、压缩解码和可证明的批量边界；不得混入本验收提交。
2. 在该任务前后重新执行宁波 12 号线 miss/hit、首次打开、再次打开、筛选、刷新和正式 XLSX 导出。
3. 另补最终 commit 的杭州 10 号线/宁波 12 号线 GUI warm handoff 交替与返回验收。
4. 最后补 MESH GUI 1000 行滚动、long task、heap 及 MESH 报告/设备导出文件完整性验收。

本轮不修改生产数据、不修改业务模型、AP Identity 或 LLDP 规则；发现的问题均以证据记录，不现场打补丁。
