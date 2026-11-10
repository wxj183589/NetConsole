# R2.3.3 位置与 UI Available 延迟

## 后端与 Renderer 埋点

位置 DTO/API 继续携带 Event、Receive、Raw Persist、Parse Complete、Position Commit、Position latency，并新增稳定的 `position_api_available_time`。同一位置状态在列表/详情查询中复用同一个 API Available 时间；无有效位置时不伪造时间。Renderer 在数据应用时记录 `uiAvailableAt`，在下一帧 paint-ready 时记录 `uiVisibleAt`，不把 API Available 当作 UI Visible。

相关主要文件：

- `src/netconsole/services/ground_unattended/application_service.py`
- `src/netconsole/models/api/ground_unattended.py`
- `apps/desktop_renderer/src/views/rail-transit/useGroundUnattended.ts`
- `apps/desktop_renderer/src/views/rail-transit/GroundUnattendedView.vue`

## 合成实时链路

最新 50 列车/100 MR 突发的 Receive→Position P95/P99 为 `399/399 ms`；Raw→Parse P95 为 `544 ms`，Parse→Position P95 为 `617 ms`。这些是 loopback 合成负载的阶段指标，不是 UI 可见时间。

## Electron 证据

运行目录：

```text
D:\study\NetConsole-Workspace\test-data\NetConsole\r2_3_3-electron-gui-20261110-1825
```

GUI capture 证据：

```text
D:\study\NetConsole-Workspace\test-data\NetConsole\r2_3_3-electron-gui-20261110-1825\gui-latency\evidence.json
D:\study\NetConsole-Workspace\test-data\NetConsole\r2_3_3-electron-gui-20261110-1825\gui-latency\syslog-mr001-ap-a-before.png
D:\study\NetConsole-Workspace\test-data\NetConsole\r2_3_3-electron-gui-20261110-1825\gui-latency\syslog-mr001-ap-b-after.png
```

真实可见 Electron、候选 Renderer、隔离 Backend 和 loopback UDP 已启动；筛选 `列车001-MR-CT` 成功，Syslog 计数在前后截图中变化，运行正常完成。截图视口没有显示当前 AP 详情行，因而不能把这次证据写成 AP-A→AP-B 的 UI Visible PASS，也没有伪造 UI Visible 延迟数值。

结论：`API_AVAILABLE=PASS_WITH_EVIDENCE_CAVEATS`，`UI_VISIBLE_LATENCY=PARTIAL`，`POSITION_ACCEPTANCE=PASS_WITH_EVIDENCE_CAVEATS`。归档本身缺少 Raw Persist、Parse Complete、Position Commit、UI Available 阶段时间，历史回放不用于线上 P95/P99 延迟结论。
