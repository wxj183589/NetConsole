# 现场诊断包使用

1. 打开 NetConsole。
2. 进入“应用日志与安全维护”。
3. 选择采样时长（默认 5 分钟）、日志范围和是否包含 Raw 样本。
4. 点击“导出现场诊断包”，在 Save As 中选择位置。
5. 等待任务完成，将生成的 ZIP 带回分析。

采集过程只读，不会停止 Ground、UDP、Raw Writer、Parser 或 Online MR。RAID/CIM 不可用时仍会生成 ZIP，并在 `manifest.json` 中记录原因。
