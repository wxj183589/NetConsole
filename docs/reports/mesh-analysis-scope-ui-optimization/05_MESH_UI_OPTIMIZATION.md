# Mesh UI 优化

摘要卡片统一最小高度并压缩为单行统计栏，范围复选框靠近统计卡片，默认显示“已排除/已纳入”。图表信息条改为链路概况、信号质量、事件与窗口三组，技术诊断折叠展示，减少横向拥挤并保留 Payload、Overlay、首末时间等证据。主链路 Tooltip 支持双击固定/解锁，轨旁 Tooltip 复用同一交互并按 AP 名称、对端射频口、RSSI 和负载分组。

图表初始视口使用有效主链 RSSI 样本首尾加动态缓冲；完整会话时间域仍作为 Navigator 边界。新增“有效数据”和“全时段”操作，保留用户缩放、时间锁定、缓存恢复、共享视口和 generation/Abort 保护。三张合成组件截图在 1920x1080、1920x1080@125% DPR、2560x1440 通过，无横向溢出和控制台 ECharts 错误。

截图：当前 Codex 输出目录中的 `mesh-phase9-1920x1080-100.png`、`mesh-phase9-1920x1080-125.png`、`mesh-phase9-2560x1440-100.png`。这属于浏览器合成夹具证据，不等同 Windows 原生 DPI/Electron 人工验收；用户参考截图本轮不可见。

状态：`UI_STATUS=PASS_WITH_LIMITATIONS`，`CHART_STATUS=PASS_WITH_LIMITATIONS`。
