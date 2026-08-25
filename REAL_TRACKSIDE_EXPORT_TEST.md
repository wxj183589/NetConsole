# Real Trackside Export Test

日期：2026-08-26

数据根：`D:\NetConsoleData-dev`；测试局点：宁波 12 号线；最终代码：`02fde6e9c9487b7d8edee2a0ff556f56c0f3d847`。

## 真实导出过程

通过正式的 `web_export_trackside_ap_business` Export Process 创建任务并观察进度：

- Job 创建：成功。
- progress：经历 snapshot preparing、snapshot build finished、history complete、行数进度、workbook save、publish。
- row_count：1,247。
- snapshot build：约 69.7s。
- export render：约 2.3s。
- 总耗时：约 74.8s。
- 任务状态：COMPLETED；Artifact：AVAILABLE；XLSX 约 165,905 bytes。
- 文件核验：递归找到的最新 DEV Artifact 有 10 个 sheet，包含 `_netconsole_meta`，无 `.tmp` 残留，文件位于 DEV 输出根内。

## Snapshot 观察

本次正式导出实际触发了完整 snapshot build，属于 miss/full-build 场景；本轮没有单独构造并重复执行 snapshot hit、筛选刷新和 UI 再次打开序列，因此 hit 时间不能宣称已验收。直接只读快照读取的补充实测为杭州 10 号线约 1.31s、宁波 12 号线约 8.73s；导出路径仍受宁波 12 号线历史解码影响。

## 结论

**PARTIAL**：任务、progress、Artifact 和文件完整性通过，但总耗时仍接近历史 77.4s，snapshot build 约 69.7s，未达到消除全量 build 的目标。DEV Artifact 保留在 DEV 根，未复制到生产目录。
