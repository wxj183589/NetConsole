# Excel 字段与导出链

日期：2026-11-08
分支：`codex-A/mesh-analysis-performance-optimization`
对照基线：`37b0df95a3208d0d03380e76ccfe5419af1422f1`

默认 `business`，可选 `diagnostic`；综合报告与独立链路明细均支持。原始日志/原始链路导出完整契约不变。UI 使用既有导出动作和统一用户文件协调器，取消路径选择不创建任务；Worker 生成内部 Artifact，继续原临时文件/原子替换/取消清理。

业务建链表保留序号、Radio、AP名称/MAC、站点/区间、开始/结束、持续时间、样本数、平均/最低/P10 MR RSSI、平均 TxBusy/RxBusy；额外保留未识别 Peer 证据列。业务链路表保留序号、时间、Radio、状态、AP名称/MAC、站点/区间、Peer Radio、MR RSSI、TxBusy/RxBusy、LinkCnt、建链时间/持续时间及未识别 Peer 证据。

从业务默认视图移出重复 Radio MAC、身份匹配规则/来源、对端重复指标、noise/signal/rate/CPU/memory/Retry/Error 等技术列，以及宽建链诊断/乒乓内部字段；完整诊断模式保留旧宽列。只有物理 MAC 明确时才在业务表抑制重复 Peer 证据值，未识别保留原 Peer，不能用名称替代设备身份。

综合报告切换表压缩为时间、Radio、切出/切入AP及证据、前后RSSI、类型/结果和乒乓标记。原质量分析与其它专题表保留。新增“AP 信号质量”“单链路风险”完整统计表、参数追溯（P10/阈值/置信样本/版本/模式）。百分比保存为数值+0.00%，中文表头、冻结、筛选、受控列宽和状态样式保留。

独立明细通过 Repository 游标和 batch_size=2000 写 XlsxWriter constant_memory；统计使用只读明确列游标。综合报告继续 openpyxl write_only，但输入 quality/report/建链/风险集合仍物化，不能称整个导出为流式或内存恒定。

性能对照口径及原始结果见02。自动验证为 openpyxl/ZIP/工作表/计数/样式/取消等结构测试；没有实际启动 Excel/WPS GUI 验收，不将结构可读等同于现场 GUI 通过。

百万条完整诊断明细的基线实测触发 XlsxWriter `FileSizeError`：单个工作表 XML 超过 ZIP32 限制。当前明细和原始链路 Writer 均启用 `use_zip64`，保留 constant_memory 与原始列。新增业务/诊断两种模式的 ZIP64 回归，降低测试 ZIP64 阈值后验证 ZIP 成员版本和 openpyxl 行数。基线百万条失败作为失败记录，不推算其文件大小或完成时间。
