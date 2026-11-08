# Excel 字段审计

本轮默认业务导出保留原始 Peer MAC 和独立的 `PEER Radio`，移除业务表中的 `Peer Radio MAC`、匹配规则和身份来源重复表达。完整诊断模式继续保留这些身份追溯字段，并保留来源文件、行号和诊断列。两种模式均保留原始 Radio/LinkState/PeerMac/EstablishTime/DurationTime/LinkCnt、L/P RSSI、Noise、Rate、CPU、Memory、TxBusy/RxBusy、TxDesFreeCnt、Tx/Rx、Retry/Err、GARP 和 MulJoin；派生 dBm 信号单独列出。

链路明细、主链路明细、AP 信号质量、单链路风险和分析参数工作表均使用现有冻结窗格、筛选、列宽、时间/百分比格式。原始链路行不因统计范围筛选而删除；AP 与风险工作表使用当前业务范围。分析参数记录排除车辆段、排除停车场和“当前筛选范围/完整范围”。

用户提供的 ZIP/Excel 本轮附件目录中不可见，无法对 110,058/2,459 条原始样本独立复核；需求中给出的 MAC 一致性结论仅作为用户证据，不能替代本轮文件级验收。合成 XLSX 结构回归通过。

状态：`RAW_MESH_FIELD_PRESERVATION_STATUS=PASS`；用户原始 ZIP 文件级复核仍为 `EXCEL_FIELD_STATUS=PARTIAL`。
