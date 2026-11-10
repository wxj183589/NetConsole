# ECharts / Listener 生命周期验收

## 诊断边界

新增 `meshLifecycleDiagnostics.ts` 只在 `import.meta.env.DEV` 或 test mode 启用，记录已有 `MeshMetricChart` 生命周期位置；没有 monkey-patch 全局浏览器事件 API，也不记录凭据或完整业务日志。`MeshMetricChart` 每个组件只创建一个 ECharts 实例，卸载时先解绑事件、dispose，再清理原生 listener、ResizeObserver 和诊断 entry。

## 真实 Electron 快照

目标 session 为 `80716c07-6bd9-47d8-b76d-ace1e55624d1:1`，隔离数据根为 `mesh-phase11-8-run-001`。

| 阶段 | component | active ECharts | init 累计 | dispose 累计 | canvas | wheel | dataZoom | tooltip | ResizeObserver | native listener | mount | unmount | inflight MESH |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 主链路加载并滚动到全部 13 图表 | 13 | 13 | 13 | 0 | 13 | 13 | 13 | 13 | 13 | 52 | 13 | 0 | 0 |
| 离开工作台后 | 0 | 0 | 26 | 26 | 0 | 0 | 0 | 0 | 0 | 0 | 26 | 26 | 0 |
| 返回后立即（lazy viewport） | 5 | 5 | 31 | 26 | 5 | 5 | 5 | 5 | 5 | 20 | 31 | 26 | 0 |
| 返回后滚动到全部图表 | 13 | 13 | 39 | 26 | 13 | 13 | 13 | 13 | 13 | 52 | 39 | 26 | 0 |

第二次离开/返回循环的累计值可能因 lazy chart 分批挂载而变化，但离开快照的活动计数全部回到 0；返回后的活动数与可见/已加载图表数一致，没有旧实例继续保留。

## 判定

- 初始完整工作台：13 个实例对应 13 个 Canvas；wheel、dataZoom、tooltip、ResizeObserver 均一一对应。
- 离开工作台：13 个实例全部 dispose，Canvas 和 52 个原生 listener 全部归零，`inflight MESH requests=0`。
- 返回/重复进入：lazy viewport 先创建可见的 5 个，再滚动加载到 13 个；没有累计 listener 漂移。
- 真实操作包含连续滚轮、页面滚动、tooltip、Shift/Ctrl/Esc、详情、AP/Radio 和页面返回；页面错误和 console error 均为 0。

`ECHARTS_LIFECYCLE=PASS_FOR_OBSERVED_RUNTIME`。这不是用 Heap 曲线替代资源计数；Heap/30 分钟长稳仍沿用第六轮证据并单独保留限制。
