# NetConsole 原版｜地面无人值守 V2 心跳检测深度优化 R2

日期：2026-11-07  
分支：`codex-A/ground-unattended-v2-20261107`  
基线：`35e99811`  
PR：#105（本轮未合并）

## 数据差异根因

页面启动时，`useGroundUnattended` 会在没有活动运行时把 `selectedRunId` 设为最近一次运行。心跳 API 收到显式 `run_id` 后按历史运行读取快照；历史运行没有任何心跳状态行时，原实现不会投影当前设备清单，因此返回 0 辆车/0 台 MR。设备管理库存仍然存在，所以同一局点会出现 21/42 与 0/0 两种结果。

这不是 Ping 失败，也不是 API 异常。没有采样不能推导离线，库存和心跳事实必须分开表达。

## 修复内容

- `GroundHeartbeatPageDTO` 增加 `data_state`、`data_state_message`、库存数量和服务端心跳统计。
- `heartbeat()` 对“选定运行确实没有任何心跳快照”的场景保留运行上下文，同时投影当前有效库存，MR/列车均显示 `UNKNOWN`/待检测；已有历史快照仍严格按运行读取。
- 后端聚合累计 Ping、成功、丢包、加权平均 RTT、丢包率和最近采样时间。
- 页面增加 `NO_INVENTORY`、`NOT_STARTED`、`INITIALIZING`、`WAITING_FOR_SAMPLES`、`PAUSED`、`STALE`、`ERROR` 等明确状态，不把空采样转成离线或 0。
- 心跳主页面增加六项核心指标、紧凑心跳统计、车辆视图/AP 列表、CT/CW 信息卡、AP/站点/主备 IP/最近成功/丢包信息和稳定的筛选分页。
- MR 抽屉增强列车/端别/UUID/站点/主备 IP 身份区，提供综合监控、Ping 详情、连接 AP 历史、Mesh/Syslog、事件时间轴五个标签，时间范围扩展至 10 分钟、30 分钟、1 小时、6 小时、24 小时。
- 监控图增加真实 Mesh/Syslog 事件轨；保留 RTT、丢包和 Peer AP 的真实时间戳、空缺段和 `connectNulls=false`，没有数据时不补虚假曲线。没有改变心跳 worker、fping、调度、锁和离线判定阈值。

主要文件：

- `src/netconsole/services/ground_unattended/application_service.py`
- `src/netconsole/models/api/ground_unattended.py`
- `apps/desktop_renderer/src/types/groundUnattended.ts`
- `apps/desktop_renderer/src/views/rail-transit/HeartbeatPage.vue`
- `apps/desktop_renderer/src/components/ground-unattended/MrMonitoringDrawer.vue`
- `apps/desktop_renderer/src/components/ground-unattended/mrMonitoringChartOptions.ts`
- `tests/test_ground_unattended_heartbeat_inventory.py`

## UI 对照与截图

对照输入：

- 目标图：`D:\下载\无人值守，心跳检测1.png`
- 本轮提供的现状图：`C:\Users\18358\AppData\Local\Temp\codex-clipboard-4b1af50b-b90f-4015-9506-25e0fc0c9dc0.png`

源码层对照已覆盖目标结构：六项顶部指标、车辆/AP 视图切换、CT/CW 双卡、整车状态与心跳统计、右侧 MR 抽屉、五个监控标签和多轨时间轴。

本轮没有启动真实 Electron/Backend，也没有生成新的桌面截图。因而 1920×1080、2048×1100、1672×941 的实际窗口截图、原生缩放、外部终端和真实设备互操作仍为 `PENDING`；上面的目标图只作为布局参考，不作为功能证据。

## 测试数据与边界

新增测试只使用 `tmp_path` 隔离 SQLite 和合成库存：覆盖选定无快照运行仍显示库存、未启动待检测、真实 Ping 统计聚合。未读取、复制或写入 `D:\NetConsoleData`、`D:\NetConsoleData-dev`，未连接真实设备。

## 测试结果

- Ground 无人值守全套：`377 passed, 1 skipped`。
- 新增/受影响 Python API、库存、监控回归：`60 passed`；Ruff、`py_compile`、`git diff --check` 通过。
- Renderer 定向 HeartbeatPage/MrMonitoringDrawer/chart：`7 passed`。
- `vue-tsc -b`：通过。
- Renderer `pnpm build`：通过。
- Renderer 全量：`197` 个测试文件通过，`1` 个既有 `CommandReferenceView.test.ts` locale 测试超时；日志伴随未启动的 `127.0.0.1:3000` 连接拒绝，本轮 Ground 定向测试未受影响。
- Change Impact Guard：报告为 L2 当前领域定向套件；动态图规范要求的空缺、时间轴单位和生命周期定向测试通过。共享契约合并到 main 后仍需按最终集成基线复验。

## 未解决问题

- 未完成真实 Electron 桌面截图、多窗口/覆盖式抽屉、Windows DPI 和安装包验证。
- 未连接真实 AC/MR、未验证现场 Syslog/WMESH 时间漂移和 AP Identity 实时归属。
- 全量 Renderer 的既有 locale 外部服务依赖仍会超时，需要在启动对应 3000 端口服务后单独复验。
- 车辆行点击当前打开该车首个可用 MR 的监控抽屉，整车级历史聚合仍沿用现有 Ground 时间轴入口。

## PR 最新状态

PR #105 保持开放；本轮分支未合并。产品提交 `865edd6c` 已推送到 `github/codex-A/ground-unattended-v2-20261107`，DevStatus 提交 `aad8235` 已推送到 DevStatus `main`；未使用 force push。整体状态保持 `PASS_WITH_LIMITATIONS / REAL_DEVICE_PENDING`。

## Change Impact

Risk：L2（Ground 领域 DTO、Application Service、Renderer 页面和动态图；未改共享 API client、数据库 schema、Feature Registry、Electron 生命周期）。  
Contracts：Ground heartbeat page DTO、run-scoped snapshot semantics、MR monitoring chart metric/time contract。  
Consumers：Ground heartbeat page、MR monitoring drawer、Ground monitoring API tests、动态图表单测。  
Regression：Ground 与定向 Renderer PASS；Renderer 全量有一个既有 locale 超时。  
Parallel modifications：当前 worktree 仅本分支，本轮文件没有其他并行修改。  
Post-merge verification：合并 main 后重跑 Ground consumer suite、Renderer 全量/typecheck/build、Change Impact Guard；补真实 Electron 截图和外部设备验收。  
Manual gaps：GUI、设备、安装包、长时运行均未宣称通过。
