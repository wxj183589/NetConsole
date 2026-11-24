# Phase 4 定向验收

日期：2026-11-24（Asia/Shanghai）。状态：**PASS，限本页明确的定向测试与模拟 Electron 范围**。

产品分支 `codex-A/rail-business-integration-phase4`，基线 `fddf1912`。实现收口 `95da4e10`；最终非车站空投影冲突修复 `d2d6d698`。截图在 `95da4e10` 重启的源码 Electron 上产生，后续修复仅影响写入冲突错误处理，未改视觉代码。

| 阶段 | 提交 | 内容与证据 |
| --- | --- | --- |
| 4.0 | bd29862b | 消费者源码审计、职责及历史/缓存风险矩阵 |
| 4.1 | 4bed8b93 | 复用既有 DTO、BaseData Query 和关系查询的只读工程上下文 |
| 4.2 | 38b864d8 | Ground 当前端位及 AP 上下文，100MR/50列车和缓存失效 |
| 4.3 | 0a5b4a34 | 轨旁页面与 XLSX 共同冻结投影 |
| 4.4 | 1d11d29f | AC 服务范围与 Wireless 工程版本/筛选 |
| 4.5 | e1c466ff | MESH / Online MR 当前及事件时关系，保护旧身份 |
| 4.6 | 95da4e10、d2d6d698 | 活动心跳监测入口、页面展示、稳定 ID 跳转、缓存与目录兼容修复 |

工程事实仍由基础设施维护，资产/采集、AC Current、Ground 事件与位置、MESH 解析、Online MR 会话继续归各自模块。没有新增 Schema、身份表、迁移或跨库全局事务。旧兼容字段保留，未对历史数据做猜测回填。

当前工程目录改名会刷新当前标签，历史关系读取事件快照。无稳定 UUID / 点位 ID 或事件时间时，历史未确认；失败、过期和冲突单独显示。工程上下文只读失败不清空运行事实，也不启动探测。`relationship_revision` 只代表 Site 工程版本。

页面沿用既有模块 Feature；新上下文和跳转随现有模块权限，目标页面重新查询 ID。无效节点显示不可用；无效 MR 跳转不回退到另一台设备。基础设施、资产、Wireless、Online MR 的跳转传稳定 ID，MESH / 会话分析保留已有 session ID 导航；没有凭设备名称拼造历史会话。

缓存页间跳转使用路由类型与工作区实例组成渲染键，修复不同页面共享缓存键的问题。Electron 白名单补齐已经存在的 Ground 路由。目录合并保留正式 station ID；非车站空 station 投影继续返回原站点冲突，不覆盖已有绑定。

| 定向批次 | 结果 | 原始证据 |
| --- | --- | --- |
| Ground 最终专项 | 67 passed / 48.38s | ground-active-context.log |
| Trackside 初始 / 共用快照收口 | 48 passed / 12.09s；56 passed / 17.04s | trackside.log、snapshot-final.log |
| AC/Wireless 初始 / 工程收口 | 44 passed / 12.24s；11 passed / 11.81s | ac-wireless.log、engineering-final.log |
| MESH / Online MR | 140 passed / 65.09s | mesh-mr.log |
| 关系/设备/安全/页面API | 111 passed / 52.19s | cross-module.log |
| 归档/身份/历史/业务API | 170 passed / 41.90s | consumer-boundaries.log |
| 最终关系及删除安全 | 37 passed / 15.00s | relation-safety-final.log |
| Renderer 主专项 / 最后筛选补测 | 255 passed / 36.23s；13 passed / 6.30s | renderer-final.log、renderer-engineering-final.log |
| 页面缓存专项 | 24 passed / 7.46s | renderer-navigation.log |
| Electron 工作区专项 | 13 passed / 0.346s，typecheck PASS | electron-workspace.log |
| Main contract smoke | 12 passed / 15.19s | main-smoke-final.log |
| Architecture / Ruff / Renderer build | 12/12，0 waived / PASS / PASS | architecture-final.log、ruff.log、renderer-build-final.log |

这些是有重叠的执行批次，不能相加作为唯一用例总数，也不代表 Full Gate。部分运行有既有 Starlette 弃用提示；build 保留既有大 chunk 提示。未关闭、豁免或屏蔽检查。

验收产物根：`D:/study/NetConsole-Workspace/reports/tests/rail-business-integration-phase4/`。包含八份分项报告、原始日志、复现脚本及 18 张真实 Electron 截图，覆盖 1920×1080、2560×1440（CSS viewport，deviceScaleFactor=1）。代表 Ground 抽屉、轨旁抽屉与 MESH 历史截图已人工检查，无页面横向溢出。

真实会话 API 联动在模拟 Site 验证：预览不改变 revision；显式保存后 revision 刷新；旧 expected_revision 返回 stale；AC 正式服务站点筛选可查询；FIT-AP Current 结果保持一致；`can_delete=false`；设备删除确认返回 HTTP 409 / `ASSET_DELETION_NOT_AUTHORIZED`。

安全边界：

```text
PRODUCTION_DATA_MODIFIED=0
DEV_REAL_DATA_MODIFIED=0
DATABASES_REMOVED=0
MAINTENANCE_AUTHORIZED=NO
```

只创建本任务最小模拟 fixture，未复制完整真实 Site、数据库或数据根；未连接真实设备。Phase 3 / 3.6 的 PARTIAL 和资产删除冻结继续保留，本轮不授予物理删除权限。

Full Gate、全量 pytest、全量 Electron、Windows 原生 125% 缩放、真实设备/局点、安装包与现场长稳均为 **NOT RUN**。无法确认的旧历史身份保持兼容读取和未确认状态，未强行迁移。产品与 DevStatus 分支分别推送，最终远端提交由本次交接记录确认，不合并 main。
