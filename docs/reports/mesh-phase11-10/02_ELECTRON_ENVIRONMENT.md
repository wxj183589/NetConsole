# Electron 验收环境

## 运行边界

- 产品仓库：D:\study\NetConsole-Workspace\NetConsole
- 分支：codex-A/global-dataroot-disk-policy
- 验收启动基线：78cc161e42d9cd50f475fae0f4b636d8b75a8633
- Electron Main PID：42676
- Renderer PID：61540
- Vite：5193
- Backend：8133
- DevTools CDP：9224
- 窗口外框：1920×1080
- 内容区域 / window.innerWidth×innerHeight：1904×1041
- devicePixelRatio：1
- 截图：真实桌面窗口捕获，1920×1080；不是 capturePage 内容区拉伸

## 数据

- Authority：隔离快照 D:\study\NetConsole-Workspace\test-data\NetConsole\mesh-phase11-8-run-001
- 禁止使用：D:\NetConsoleData
- 开发真实数据 D:\NetConsoleData-dev 未被 Electron 写入
- 会话：80716c07-6bd9-47d8-b76d-ace1e55624d1:1
- 列车 / MR：列车01 / 列车01-MR-CW
- 时间域：2026-10-20 09:42:06.657 至 2026-10-20 18:42:06.381
- 原始 gzip：2,892,510 bytes，SHA256 F53990D5448F297EA8CBC6901D87132FCF3F616C61149FEAA4E875829A3B0FC7
- parsed SQLite：156,786,688 bytes，SHA256 2630D9CF03CD5AC3146E11D449DB5964DD8E7DD97666136D56EB09AA40B77271
- mesh SQLite：249,856 bytes，SHA256 7D45597929601C48848BA65471F0270EACA5489CD6CD662B2AF74D45CDD3A191

## 解析数据概况

parsed SQLite 只读核验结果：active_points 44470、active_segments 8091、
diagnosis_events 8087、mesh_links 108700、mesh_peer_mapping 1231、
mesh_peer_resolve_cache 1231、mesh_sessions 9038、parse_issues 2865、
rssi_stats 1184、samples 44470、switch_events 8101。源文件 1 个。

## 运行结论

真实 Electron 进入 MESH 页面，完成导航、图表、分页、列设置、筛选、截图、
报告导出和链路明细导出。之前全范围大表直接交给图表导致的 Renderer crash
已通过“原始数据完整保留、交给 ECharts 的视觉样本有界且保留连续性边界”修复；
本轮修复后的完整指标加载和交互复测未再出现 crash。
