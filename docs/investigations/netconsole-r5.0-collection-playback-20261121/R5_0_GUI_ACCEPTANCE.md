# GUI 验收

状态：`PARTIAL`

审计时未发现可用于本任务的 DEV Electron 进程。已安装实例的 `bootstrap.json` 指向 `D:\NetConsoleData`，且 `runtime_mode.json` 为 `production`；按任务硬门禁未在该实例进行任何回放操作，也未修改其配置。

本次没有把完整源码 Backend/Electron 直接启动在 `D:\NetConsoleData-dev` 上；正常启动会产生 runtime/log/lock 等写入，与真实开发数据根零修改目标冲突。因此 1920×1080、2K、窗口 resize、真实 Tooltip、长列表和页面销毁仍需在允许独立运行时输出的受控 DEV 启动方式下验收。诊断阶段另有 SQLite sidecar 偏差，详见真实数据报告。

已完成的自动证据不能替代 GUI：组件测试、类型检查、ECharts option 断言、真实 SQLite/Raw 只读查询。

待验收项：实际暗色主题布局、三轨同步手感、备用轨折叠持久化、事件点击定位、Navigator 连续拖动、窗口尺寸变化与大数据渲染。
