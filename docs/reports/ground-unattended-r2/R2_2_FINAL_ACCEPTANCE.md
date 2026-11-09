# R2.2 最终验收

日期：2026-11-10。Agent：codex-A。整体 **PARTIAL**。Heartbeat 常驻生命周期已实现，以下 PASS 仅指所列自动化或隔离短时场景；长稳与真实现场未验收。

| 验收项 | 状态 | 证据与边界 |
| --- | --- | --- |
| HEARTBEAT_BACKEND_RESIDENT | PASS | lifespan 无 Run/无 Renderer 启动采样、重复 start 单线程、安全关闭；真实 Electron 无 Run 200 目标 |
| HEARTBEAT_RUN_INDEPENDENCE | PASS | start/pause/resume/stop/window_end/ERROR 定向回归；GUI Ground stop 后继续 200 目标 |
| HEARTBEAT_INVENTORY | PASS | 持久库存、无 AC/凭据/Mesh 仍展示；GUI 60 车辆/120 MR |
| HEARTBEAT_TARGET_REFRESH | PASS | 后台基础资料刷新、增删/IP 变化、冲突去重、配置热更新无 worker 重叠；长时频繁变更待验收 |
| HEARTBEAT_STATE_PERSISTENCE | PASS | 原引擎复用、快照批次写入失败保留并重试、主备独立计数 |
| HEARTBEAT_LOSS_HISTORY | PASS | 未闭合事件恢复、跨 Run 保留、合成 400/800 完整丢包记录 |
| HEARTBEAT_RESTART_RECOVERY | PASS | 定向旧格式/计数/事件恢复；实际正常重启后 120 MR/200 IP、sent 1400→2058；强杀未验收 |
| HEARTBEAT_FAULT_ISOLATION | PARTIAL | AC/Mesh/UDP start/replay/deep/fping/SQLite 注入通过；实际 Parser/Renderer 进程崩溃未验收 |
| HEARTBEAT_RENDERER_INDEPENDENCE | PASS | 页面只读，离页与 reload 后 Backend 持续；组件轮询卸载；Renderer 强杀缺口见上一项 |
| HEARTBEAT_400_TARGETS | PASS（短时正确性） | 400 MR/800 IP 合成回调及真实 fping；容量/长期性能仍 PARTIAL |
| HEARTBEAT_LONG_STABILITY | NOT_RUN | 未运行 8 小时 |
| HEARTBEAT_GUI | PASS（已列场景） | 真实 Electron 四张截图及 API 摘要；频繁切页、设置交互和 DPI 未完整验收 |
| SYSLOG_REGRESSION | PASS（自动化） | Ground 全域 435 passed / 1 skipped，含 R2.1 重复批次、串行操作、取消及 ownership；未执行真实 SSH |
| GROUND_RUN_REGRESSION | PASS（自动化） | Ground 全域 435 passed / 1 skipped；基本实际 Electron Run start/stop 验证通过 |

证据入口：[审计](R2_2_HEARTBEAT_AUDIT.md)、[架构](R2_2_ARCHITECTURE.md)、[实施](R2_2_IMPLEMENTATION_REPORT.md)、[测试](R2_2_TEST_REPORT.md)、[性能](R2_2_PERFORMANCE_REPORT.md)、[GUI](R2_2_GUI_ACCEPTANCE.md)、[剩余问题](R2_2_REMAINING_ISSUES.md)。

## 交付与数据

分支 `codex-A/global-dataroot-disk-policy`，产品与 DevStatus 分开本地提交，不 Push、不 Merge、不切换/删除分支。DataRoot/SiteStorage/AGENTS 既有 dirty 修改及并行 MESH 提交保留；没有将其混入 R2.2 提交。

只使用 Workspace 内隔离合成测试根和 loopback，未读取/修改 `D:\NetConsoleData`、`D:\NetConsoleData-dev`，未操作现场设备或 `D:\study\fping`。Schema 及恢复仅对隔离 fixture 验证。真实设备 NOT_RUN；8 小时 NOT_RUN；发布/安装验收 NOT_RUN。完整集成 Gate 为 FAIL；本轮相关失败已定向修复复验，仍有并行工作及 HEAD 漂移相关失败，详见测试报告，不构成发布或合并通过依据。
