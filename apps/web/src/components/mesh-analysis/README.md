# Mesh 分析组件

本目录承载 Mesh 离线分析的图表组件，负责把已查询的序列数据呈现为 RSSI 等趋势，不在组件内解析原始日志或计算业务结论。

主要入口为 `MeshRssiChart.vue`；数据来自 Mesh API/ViewModel，主题来自统一 ECharts 配置。修改图表字段或语义时运行对应测试并检查空数据和单位。

## 页面与报告口径

- 主链路建链顺序由 `MeshMrRepository.query_active_link_build_order` 生成，页面 API 和正式 Excel 报告不得各自重算区段、短时建链或乒乓结论。
- 链路明细由 `MeshMrRepository.iter_link_details` 读取 compact v3 标量列；`timestamp_tag` 是采样身份的一部分，报告不得合并同毫秒的不同采样块。
- 全部 ACTIVE RSSI 和空口负载复用 `mesh_chart_payload` 的唯一 ACTIVE 路径结果。RSSI 图固定为 MR/Peer 两条序列，空口负载图固定为 MR 侧 TxBusy/RxBusy 两条序列，不按 AP 数量扩增图例，也不伪造 CtlBusy。
- 页面与报告通过 `MeshApLocationSnapshot` 共享 AP 名称、MAC、站点、区间、里程和线路方向解析；Export Job 只携带该快照的受控字符串字段。Excel 工作表保留完整业务数据，嵌入图表使用关键点和极值降采样，空 ACTIVE 不创建空图。
- 正式报告继续由 Export Process 生成：Worker 写临时文件，完成后原子替换目标 Artifact；Renderer 不读取全量链路，也不生成 Excel。
- 图表请求按 Radio/时间窗口使用 generation 防止迟到响应串回旧会话；单 AP 支持单次经过和全部经过时段，后者以 `gap_before` 强制断线。
- 切换事件由 Query Service 预载前后 AP 和建链区段；ECharts markLine 可点击，页面提供回到建链顺序动作。图表数据缺口定位使用渲染序列元数据，不把断点占位行误当业务采样。
- 报告按钮默认沿用来源参数，显式启用临时参数时通过 `MeshReportRequestDTO` 进入 Export Process，不修改来源快照、局点配置或 parsed 数据库。
