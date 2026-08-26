# Real Trackside Export Test

日期：2026-08-26

数据根：`D:\NetConsoleData-dev`；测试局点：宁波 12 号线；验收起点 HEAD：`e8b826b9b6d3e799fc2bd71afe07ece07b4b2769`。

## 当前 bounded treatment 只读导出补充

直接调用正式 `export_trackside_ap_business_prepare_and_render`，输入仅为 `D:\NetConsoleData-dev\sites\宁波地铁12号线\db\devices.db`，输出写入 `D:\study\diagnostic\NetConsole\real-acceptance`：

- row_count：1,247；persisted treatment sheet：101 行。
- total：28,140.38ms；snapshot build：25,289ms；render：1,895ms。
- output：141,151 bytes；`content_sha256=42a168ecfdb0174384ee1932142da6486afe51d7f108b84bacdbf53e71d59275d`。
- abnormal：55；unresolved：302；ambiguous：0；partial：false。

相对历史约 77.4s 有改善，但 snapshot/enrichment 仍为 25.29s 热点，不能宣称达到目标。

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

**PARTIAL**：正式任务、progress、Artifact 和文件完整性通过；当前直接导出约 28.14s，历史正式任务仍约 74.8s，snapshot build 仍为主要热点。DEV Artifact/诊断输出保留在 DEV 或诊断根，未复制到生产目录。
