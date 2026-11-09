# R2.2 实施报告

日期：2026-11-10。Agent：codex-A。分支 `codex-A/global-dataroot-disk-policy`。Syslog 基线 `b3ccb1bd193f7477387c878dde7b747aa0b2f172`；保留后续并行 MESH 提交及既有 DataRoot/SiteStorage dirty 文件。本轮不 Push、不 Merge、不切换分支。

## 已实施

| 范围 | 主要文件 | 结果 |
| --- | --- | --- |
| 常驻资源所有者 | `src/netconsole/services/ground_unattended/heartbeat_supervisor.py`、`supervisor.py` | 提取原状态/持久化逻辑，独立线程管理唯一 Fleet；Ground 只补充位置 |
| Backend 生命周期 | `src/netconsole/backend/api/main.py` | lifespan 启停与 Site rebind 释放 |
| 独立配置/迁移 | `src/netconsole/repositories/ground_unattended_repository.py`、`src/netconsole/models/api/ground_unattended.py` | additive 配置表、旧事实一次性迁移、汇总计数恢复 |
| Fleet 容错 | `src/netconsole/services/ground_unattended/fleet_ping.py` | 失败分片退避、意外流结束识别、目标增量恢复 |
| 当前查询 | `application_service.py`、`monitoring.py`、`raw_query.py`（同一 services 包） | 常驻流查询、旧 Run 兼容、AC enrichment 失败保留库存 |
| API | `src/netconsole/backend/api/ground_unattended_router.py` | 独立 config/runtime、服务层调用与权限复用 |
| 页面与设置 | `apps/desktop_renderer/src/views/rail-transit/HeartbeatPage.vue`、`HeartbeatSettings.vue`、`useGroundUnattended.ts`、`SettingsPage.vue` | 与 Run 选择/状态脱钩、独立配置与运行状态 |
| 契约与文本 | Renderer `src/api/groundUnattended.ts`、`src/types/groundUnattended.ts`、`src/i18n/groundUnattended.ts` | DTO 与中文 i18n 同步 |
| 回归 | `tests/test_ground_unattended_heartbeat_resident.py`、既有 Ground 测试及 Renderer 页面测试 | 生命周期、热更新、恢复、库存、故障、400 MR 并发 |

Ground Settings 原 Fleet 控件移入独立 HeartbeatSettings；旧 Profile 参数保留兼容首次采用，之后不驱动常驻监控。界面操作通过独立配置启停；停止 Ground Run 不能替代 Heartbeat 停用。

Syslog Task ID、设备 FIFO、重复检查、ALREADY_CONFIGURED、CONFIG_CONFLICT、取消隔离及 ownership 安全边界保持既有实现；本轮回归覆盖这些消费者，没有新增 Syslog 写设备行为。

## 数据与验证边界

仅使用 Workspace 内明确隔离测试根、合成库存及 loopback fping，未读取/修改 Production、真实开发数据或现场设备。未复制完整 Site 或真实数据根。新增 Schema 与迁移仅在隔离数据库验证；真实历史库升级仍待验收。

真实 Electron、短时实际 fping 与合成回调分别记录，不能相互替代。证据与余项见 [测试](R2_2_TEST_REPORT.md)、[性能](R2_2_PERFORMANCE_REPORT.md)、[GUI](R2_2_GUI_ACCEPTANCE.md)、[剩余问题](R2_2_REMAINING_ISSUES.md)。产品与 DevStatus 分开本地提交；本报告的实际 Commit 由 Git 历史及 DevStatus 交接记录确定。
