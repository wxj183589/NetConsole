# NetConsole MESH 原始日志分析 Phase 11.9 第六轮最终报告

日期：2026-11-10  
Branch：`codex-A/global-dataroot-disk-policy`  
交付提交：`b6d8b16c`  
真实运行采样提交：`de7ca957d371cd8bc29b60d05f69f4c85d8b2190`（dirty）  
目标会话：`80716c07-6bd9-47d8-b76d-ace1e55624d1:1`

## 最终状态

`PHASE_11_9_SIXTH_ROUND=PARTIAL`。

本轮已经完成真实 Electron 全工作台闭环、14 个字段的页面验证、真实 HTTP/SQL trace、缓存交互、gap-fill 路径、Cold/Warm 性能、30 分钟稳定性、10 张原生截图和 MESH 自动化回归。不能升级为 PASS 的原因是：隔离快照 catalog 被运行时更新、`mtime_ns` 未被记录、gap-fill 当前证据不能严格证明只补 B、ECharts instance/listener 数量不可直接观测，以及 Workspace 检查仍被既有顶层 `docs` 目录阻断。

## 交付内容

### 真实运行

- Electron 主运行 PID `46580`；补充截图运行 PID `52192`。
- Renderer viewport `1904x1041`，原生窗口 `1920x1080`，DPR=1。
- 运行 data root 为隔离快照 `D:\study\NetConsole-Workspace\test-data\NetConsole\mesh-phase11-8-run-001`。
- `D:\NetConsoleData-dev` 未作为运行 data root；Production 未作为破坏性测试目标。
- 主链路监控真实显示 13 个 chart panel、13/13 完成；Tx/Rx 是双序列 panel，详情包含 14 个业务字段。
- AP 情况真实切换到 STANDBY / Radio 1，显示 853 条 AP/射频口/链路角色统计。

### 交互与性能

- 主动作 ledger：35 项。
- 30 分钟稳定性：1803 秒、30 个分钟样本、117 次真实交互。
- warm-1：16.868s，warm-2：16.802s，cold reload：20.440s。
- warm-1/warm-2 SQL 均为 0；cold reload SQL=4。
- stability 样本中页面/console error=0、inflight=0、cancelled trace=0、Canvas=13。

### 数据边界

- 目标会话的 mesh.sqlite、parsed SQLite、raw gzip 前后 SHA/size 未变。
- 隔离快照 `mr_raw_mesh/catalog.sqlite` SHA 发生变化；未恢复该变化。
- 所有 evidence JSON 的 `mtime_ns` 为 null，因此 mtime 结论标记为 UNATTRIBUTED/UNRECORDED。
- 未删除 SHM、未恢复 mtime、未覆盖 Production/Dev Authority。

## Gate 总结

| Gate | 结论 |
|---|---|
| 真实 Electron 全工作台 | PASS（运行事实） |
| 14 字段 + lazy chart | PASS（13 panel + Tx/Rx 双序列） |
| HTTP/SQL trace | PARTIAL（94 HTTP / 9 SQL，13 FAILED records） |
| 缓存动作新 MESH HTTP/SQL=0 | PASS（缓存动作口径） |
| 100+ 真实交互 | PASS（117 stability interactions） |
| Gap-fill 只补 B | PARTIAL |
| Cold/Warm | MEASURED |
| Heap 长稳 | PARTIAL（两类对象不可观测） |
| 数据完整性 | PARTIAL（catalog mutation + mtime missing） |
| MESH regression/build | PASS |
| Workspace layout | PARTIAL（既有 workspace docs） |

## 证据索引

- 运行总证据：`sixth-round/sixth-round-runtime-evidence.json`
- Electron 验收：`sixth-round/ELECTRON_RUNTIME_ACCEPTANCE.md`
- HTTP/SQL：`sixth-round/REAL_HTTP_SQL_TRACE.md`
- 交互：`sixth-round/100_REAL_INTERACTION_RESULTS.md`
- Gap：`sixth-round/GAP_FILL_E2E_REPORT.md`
- 性能：`sixth-round/CACHE_PERFORMANCE_REPORT.md`
- Heap：`sixth-round/HEAP_STABILITY_REPORT.md`
- 回归：`sixth-round/MESH_FULL_REGRESSION.md`
- 数据完整性：`sixth-round/DATA_INTEGRITY_REPORT.md`
- 截图清单：`sixth-round/SCREENSHOT_INVENTORY.md`
- 自动化汇总：`sixth-round/AUTOMATED_TEST_RESULTS.json`
- 未完成项：`sixth-round/REMAINING_ISSUES.md`

## 交付判断

第六轮的“真实 Electron + 全工作台 + 缓存交互 + 长稳”主路径已经有可复核证据，但由于上述数据与可观测性边界，Phase 11.9 overall 不宣称 PASS。下一轮应优先：使用 candidate 记录并隔离 catalog 写入、在 probe 中以 bigint 记录 mtime_ns、输出按 A/B/C 分段的 raw gap query attribution，并增加 ECharts instance/listener 的受控诊断接口。

