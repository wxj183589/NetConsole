# NetConsole v1.5.16 长期运行稳定性

状态：`PARTIAL`

## 已修复的确定性故障

- Quick Ping API 不再把内部关闭确认字段传入严格 DTO。
- Backend 关闭阶段缺少 `task_snapshots` 表时安全降级并保留诊断日志。
- AC/Mesh-Link 关系图退役后，同步移除了其 ResizeObserver、全屏监听、指针监听和定时器，减少不可达组件的资源生命周期。
- MR 监控继续使用有界事件窗口，不以无限累积前端事件替代分页/历史查询。

## 已执行回归

- Quick Ping DTO 边界。
- Backend 正常关闭缺表路径。
- Heartbeat 常驻选择和调度。
- Renderer 211 files / 1544 tests、生产构建，以及 Python 5620 passed / 2 skipped 的完整回归（最终证据见测试报告）。

## 尚未完成

- 未完成任务要求的 8 小时连续运行。
- 未在现场数据量和同等硬件上重新测量 MR Monitoring、Ping Targets、Base Data AP 的最大响应时间。
- 未取得现场 Renderer RSS、句柄、线程、图表实例和 WebSocket 趋势，因此不能宣称 `exit_code=-36861` 已被完全根治。

正式发布前应执行 8 小时脚本化页面切换、Heartbeat/Syslog/AC/Quick Ping 负载和停止重启测试，并记录初始、峰值、末值与增长斜率。
