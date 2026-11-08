# Phase 9 最终报告

本阶段完成 Mesh 业务范围治理、完整原始链路字段导出、单链路排除和页面信息层次/初始视口优化。业务 Excel 删除重复的 `Peer Radio MAC`、匹配规则、身份来源；保留原始 Peer MAC、`PEER Radio`、来源文件和行号，并在业务/诊断两种模式保留全部 L/P RSSI、Noise、Rate、CPU、Memory、Busy、TxDesFreeCnt、Tx/Rx、Retry/Err、GARP、MulJoin 原始数值。诊断模式保留完整身份字段。

车辆段和停车场默认排除，正式站点类型优先，未知归属保持 UNKNOWN。过滤在备链判定和风险分段前执行，统一影响 AP/风险统计和派生工作表，原始日志与解析数据完整保留。主链路图以 ACTIVE 数据为主，轨旁图保留逐采样 ACTIVE/STANDBY 角色；Tooltip 支持双击固定、再次双击或 Esc 解锁，固定后不随指针、缩放或时间轴拖动改写；普通和备链浮窗去除重复 MAC/本端 Radio，切换事件只显示 AP 名称与 RSSI，并显示可确认的对端射频口。图表首次打开定位有效样本范围，同时保留完整 Navigator、缩放、锁定和全时段恢复。

| 状态项 | 结果 |
|---|---|
| IMPLEMENTATION_STATUS | PASS |
| EXCEL_FIELD_STATUS | PARTIAL（原始 ZIP 不可见） |
| DEPOT_FILTER_STATUS | PASS |
| PARKING_FILTER_STATUS | PASS |
| SINGLE_LINK_STATUS | PASS |
| RAW_DATA_INTEGRITY_STATUS | PASS（无真实数据写入） |
| UI_STATUS | PASS_WITH_LIMITATIONS |
| CHART_STATUS | PASS_WITH_LIMITATIONS |
| PERFORMANCE_STATUS | PARTIAL |
| FULL_GATE_STATUS | PASS |
| GIT_STATUS | PASS（本地提交，未 Push/Merge/Release） |
| RAW_MESH_FIELD_PRESERVATION_STATUS | PASS（Parser/SQLite/API 已有字段；业务/诊断 XLSX 合成一致性通过） |
| ACTIVE_ONLY_STATUS | PASS（主链路路径按 ACTIVE 事实返回；STANDBY 仅作为上下文） |
| SINGLE_AP_HISTORY_STATUS | PASS_WITH_LIMITATIONS（现有 Peer 连续访问/轨旁序列支持历史主备角色；未做真实样本验收） |
| AP_ROLE_TRANSITION_STATUS | PASS（按每条采样 LinkState 建序列并保留切换事件） |
| COUNTER_BASELINE_STATUS | PARTIAL（原始累计计数保留；本轮未新增跨角色增量算法） |
| ACTIVE_SWITCH_STATUS | PASS（合成切换事件和图表节点定向回归） |
| COMPACT_KPI_STATUS | PASS（统计区改为紧凑栏，点击行为保留） |
| UI_RESPONSIVE_STATUS | PASS_WITH_LIMITATIONS（Renderer/typecheck；真实 Windows 125% 与 GUI 仍待） |
| TOOLTIP_PIN_STATUS | PASS（主链路与轨旁 Tooltip 双击固定/解锁、Esc 清理） |
| TOOLTIP_FIELD_SIMPLIFICATION_STATUS | PASS（主链路/备链去除重复 MAC/本端 Radio，切换事件仅保留 AP 名称与 RSSI） |
| PEER_RADIO_PORT_STATUS | PASS（radio1/radio2 显示 1/2，无法解析显示 —） |
| TOOLTIP_LAYOUT_STATUS | PASS_WITH_LIMITATIONS（容器边界/内部滚动已实现，未做真实窗口截图验收） |
| TOOLTIP_REGRESSION_STATUS | PASS（本轮定向 Tooltip/挂载/trackside 回归 3 files / 49 tests passed；`vue-tsc -b` passed） |

产品分支：`codex-A/mesh-analysis-scope-ui-optimization`；实现提交：`225e05d2`，Tooltip 回退修订：`2a6ea78e`。DevStatus 单独提交，两个仓库均不推送。

限制：用户要求的原始 Excel ZIP 在本轮附件目录不可见，不能声称真实样本字段或三视口人工截图已独立复核；Windows 原生 DPI、Excel/WPS GUI、真实局点与设备仍待外部验收。累计计数器跨主备角色的增量基线算法仍沿用既有实现，本轮只确认原始累计字段不丢失。`FULL_GATE_STATUS=PASS` 仅引用 2026-11-08 的既有本地 Gate 证据，本轮按要求未重复全量 Gate。
