# NetConsole 详情页 History UI 审计

审计日期：2026-08-27
审计范围：`apps/desktop_renderer`、`apps/desktop_electron`、API Router、DTO、Application/Query Service、Repository；`apps/web` 当前不存在。

## 结论

工程态设备详情统一采用 `Current + Recent <= 10`：

- Current 直接展示当前快照，不因打开详情页而读取明细 Recent。
- Recent 只有计数大于 0 时显示“最近变化 (N)”并允许点击加载；N=0 显示“最近变化：暂无”，不打开空弹窗。
- Recent 查询只读取新的 bounded history 表，按 `changed_at DESC, id DESC` 返回最新记录；详情 Renderer 固定请求 10 条。
- Recent 计数接口失败显示“加载最近变化失败”，不伪装为“暂无”。返回或展示的 N>10 会输出 `[RECENT_CHANGE_UI_INVARIANT]` 开发告警。
- 旧 `/history/...` URL 继续保留为兼容入口，但服务端将 page size 上限收窄到 10；新的 Renderer 不再使用“历史”作为工程态详情动作名称。

## 工程态详情审计矩阵

状态含义：`CONFIRMED` 为代码与测试同时确认；`SUPPORTED` 为代码路径确认、未做真实设备 GUI 验收；`UNVERIFIED` 为当前环境无法确认。

| 页面 | 当前入口 | 数据类型 | API | 是否可能 Recent=0 | 建议 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| [`AcManagementView.vue`](../../../../apps/desktop_renderer/src/views/ac-management/AcManagementView.vue) | FIT-AP 详情的 Mesh Radio Current 区块 | Radio | `/api/ac-management/aps/{ap_id}`；点击 `/history/radio` | 是 | 详情响应一次返回计数；0 显示“最近变化：暂无”，>0 显示数量并点击加载，错误显示失败态 | `CONFIRMED` |
| [`AcManagementView.vue`](../../../../apps/desktop_renderer/src/views/ac-management/AcManagementView.vue) | FIT-AP 详情的 LLDP/端口 Current 区块 | LLDP | `/api/ac-management/aps/{ap_id}`；点击 `/history/lldp` | 是 | 保持 Current 直接展示；Recent 仅按需加载，最多 10 条 | `CONFIRMED` |
| [`AcManagementView.vue`](../../../../apps/desktop_renderer/src/views/ac-management/AcManagementView.vue) | FIT-AP 详情的光衰 Current 区块 | Optical | `/api/ac-management/aps/{ap_id}`；点击 `/history/optical` | 是 | 保持当前 Tx/Rx 与判定；无变化不打开空抽屉 | `CONFIRMED` |
| [`DeviceDetailPanel.vue`](../../../../apps/desktop_renderer/src/components/device-detail/DeviceDetailPanel.vue) | 设备详情接口 Current 表 | Interface | `/interfaces`；计数 `/recent-change-counts`；点击兼容 `/history?kind=interface` | 是 | 计数 O(1) 汇总；0 为正常空态，>0 点击加载 Recent10 | `CONFIRMED` |
| [`DeviceDetailPanel.vue`](../../../../apps/desktop_renderer/src/components/device-detail/DeviceDetailPanel.vue) | 设备详情光模块 Current 表 | Optical | `/transceivers`；计数 `/recent-change-counts`；点击兼容 `/history?kind=optical` | 是 | 继续保留光衰诊断价值；错误与空态分开 | `CONFIRMED` |
| [`DeviceDetailPanel.vue`](../../../../apps/desktop_renderer/src/components/device-detail/DeviceDetailPanel.vue) | 设备详情 LLDP Current 表 | LLDP | `/lldp`；计数 `/recent-change-counts`；点击兼容 `/history?kind=lldp` | 是 | Current 不受 Recent 请求影响；Recent 按 changed_at DESC 展示 | `CONFIRMED` |

## 主列表、Treatment 与其他页面

| 入口 | 发现 | 处理结论 | 状态 |
| --- | --- | --- | --- |
| `TracksideApBusinessView.vue` 主列表 | 主列表读取当前业务快照、当前光衰与当前 Treatment；未发现 Recent/N+1 读取 | 保持主列表只展示 Current；不增加 Recent 计数列或逐行请求 | `SUPPORTED` |
| Trackside AP Optical Treatment | 未发现独立的“Treatment History”详情入口；`ap_optical_treatment` 是当前治疗/状态 ledger，相关历史增强用于业务推导和导出 | 不新增伪造的 History 菜单，不改 Treatment ledger 语义 | `CONFIRMED` |
| `TracksideApPlanningTab.vue` | “待关联历史规划”是基础资料兼容/清理场景，不是运行态 Recent | 保留原文案和功能 | `CONFIRMED` |
| `TrafficTestView.vue`、`WirelessScanPanel.vue` | 历史任务/扫描结果属于执行记录或查询结果 | 保留长期历史语义 | `CONFIRMED` |
| `VehicleMrOnlineView.vue`、`OnlineMrAnalysisView.vue` | 列车经过历史、MR 主链路切换历史属于真实 MR 事件/分析证据 | 保留长期历史语义 | `CONFIRMED` |
| `GroundUnattendedView.vue` | 历史归档、运行历史、Syslog 属于无人值守运行记录 | 保留长期历史语义 | `CONFIRMED` |
| Task Center、配置快照、数据库备份/迁移 | 属于任务审计、配置 Artifact 或数据库运维记录 | 不纳入 Current + Recent10 收口 | `CONFIRMED` |
| `apps/desktop_electron` | 仅发现运行时/打包说明，无独立详情 History UI | 无需修改 | `SUPPORTED` |
| `apps/web` | 目录不存在 | 无活动 Web UI 可审计或修改 | `CONFIRMED` |

## API / DTO / 数据读取边界

- FIT-AP 详情 DTO 增加 `recent_change_counts`；通用设备增加 `DeviceRecentChangeCount(s)DTO` 与 `/recent-change-counts`。
- FIT-AP Recent 读取 `fit_ap_radio_history`、`fit_ap_lldp_history`、`optical_history`；通用设备 Recent 读取 `device_interfaces_history`、`device_optical_modules_history`、`device_lldp_neighbors_history`。
- 新的详情 Recent 代码不读取 `HistoryStore`，也不对工程态 bounded 表做 legacy fallback。Repository 中仍存在的 `HistoryStore` 用于任务、运行记录、迁移或其他长期历史，不属于本次工程态详情 Recent 入口。
- 详情初始加载只有一次计数请求；主 Trackside 列表不调用计数接口，Current 列表没有逐行 Recent/N+1。
- `total` 仍可用于诊断历史表违反 `<=10` 不变量；UI 不再以分页方式扩展工程态 Recent。正常数据应始终 `total <= 10`。

## Renderer 验证覆盖

- FIT-AP Radio、LLDP、Optical：源契约测试覆盖计数驱动的 0/1/10 文案、点击入口、错误态和 `>10` 告警。
- 通用设备 Interface、Optical、LLDP：挂载测试覆盖 Recent=0、1、10；0 不调用明细 API，1/10 只按点击调用 10 条；计数 API 错误不显示“暂无”。
- 性能 Gate：没有可靠的改动前基线（`FIT_AP_DETAIL_BEFORE_MS=UNAVAILABLE`）；隔离 fixture 当前详情接口测得 `FIT_AP_DETAIL_AFTER_MS_MEDIAN=21.961`、`FIT_AP_DETAIL_AFTER_MS_P95=40.213`，测量未使用真实业务数据。
- 真实设备、安装包 GUI、跨机器设备采集验收不在本次自动化验证范围内。

## 本轮最终报告字段

```text
HISTORY_UI_AUDIT=COMPLETE
ENGINEERING_HISTORY_UI_RENAMED=PASS
EMPTY_HISTORY_ENTRY_REMOVED=PASS
RECENT_ZERO_SEMANTICS=PASS
RECENT_MAX_10=PASS
TREATMENT_HISTORY_ENTRY=REMOVED (未发现独立入口)
FIT_AP_LIST_RECENT_N_PLUS_ONE=0
LEGACY_HISTORY_FALLBACK_FOR_UI=0
LEGACY_HISTORYSTORE_RECREATED=NO
GUI_REAL_ACCEPTANCE=UNVERIFIED
NEW_TEST_FAILURES=0
FIT_AP_DETAIL_BEFORE_MS=UNAVAILABLE
FIT_AP_DETAIL_AFTER_MS_MEDIAN=21.961
FIT_AP_DETAIL_AFTER_MS_P95=40.213
```

`NEW_TEST_FAILURES=0` 仅指本轮新增/直接相关定向测试；工作区原有的两个完整 API 回归失败仍见最终交付报告，未归因于本轮 Recent UI 改动。

## 2026-08-27 真实 Electron GUI 终验与 DEV 数据复核

本节是对上文 `GUI_REAL_ACCEPTANCE=UNVERIFIED` 的更新。被测进程为源码 Electron + Vite + 受管 DEV Backend，未操作已安装生产实例。

```text
GUI_REAL_ACCEPTANCE=PASS
ELECTRON_SOURCE_PID=31324
BACKEND_PID=31020 (child=31504)
VITE=http://127.0.0.1:5173
ACTIVE_SITE=宁波地铁12号线
WINDOW_VISIBLE=YES
WINDOW_RESPONSIVE=YES
DATA_ROOT=D:\NetConsoleData-dev
PRODUCTION_DATA_TOUCHED=NO
```

### GUI evidence

- AP A `30f5-277a-1ac0`：Radio Recent=0，Current 区显示“最近变化：暂无”，没有打开空弹窗；Radio 1/2 Current 均独立显示。
- AP B `30f5-277a-1680`：Radio Recent=4、LLDP Recent=7；点击后实际弹窗行数与底部总数一致。
- AP C `30f5-277a-25a0`：重启源码 Electron 后 Radio/LLDP 均显示 Recent=10；Radio 弹窗实际 10 行。
- LLDP Recent 保留 source、local interface、neighbor、neighbor interface、neighbor MAC/device 等字段；光衰在 FIT-AP 详情保持 AP-side/SWITCH-side Current 台账，不新增伪造的 History/Treatment 入口。
- 设备详情 Interface/Optical/LLDP 以 Current 为首屏，Recent 仅点击后加载；实际 Interface Recent 弹窗显示 2 行，AP-side/SWITCH-side 光衰字段可见。
- FIT-AP 列表没有逐行 Recent/N+1 请求；详情初始 `/aps/{id}` 只带批量计数，`/history/...` 只在点击后出现；Trackside rows 请求 1 次且 Trackside History/Recent 请求为 0。

截图目录：`D:\study\diagnostic\NetConsole\recent-change-ui-20260827`；关键证据为 `17-zero-detail.png`、`11-radio-recent.png`、`12-lldp-recent.png`、`23-c-detail-capped.png`、`24-c-radio-recent-10.png`、`29-device-detail-open.png`、`32-interface-recent-dialog.png`、`03-task-closed.png`。

### API / storage evidence

```text
API_200_EMPTY_SEMANTICS=PASS (Recent=0 仍是正常空态)
API_500_ERROR_SEMANTICS=PASS (错误态测试显示“加载最近变化失败”，不伪装为“暂无”)
FIT_AP_LIST_RECENT_N_PLUS_ONE=0
FIT_AP_DETAIL_RECENT_BEFORE_CLICK=0 (history endpoint)
TRACKSIDE_RECENT_REQUESTS=0
LEGACY_HISTORYSTORE_RECREATED=NO
DB_HISTORY_BEFORE_STOP=0 files / 0 bytes
DB_HISTORY_AFTER_STOP=0 files / 0 bytes
```

终验期间 API 路由均为 200（任务提交除外）；日志尾部 `status=5xx`、`DATABASE_LOCK`、`SQLITE_BUSY`、timeout 标记为 0。DEV 只读复核为 11 Site/34 活动数据库，`quick_check=PASS`；按 `ap_identity+radio_id`、`ap_identity+side` 或设备对象槽位计算，Radio/LLDP/Optical/Interface 六类 Recent 最大值均为 10。`ap_optical_treatment` 为 330 行、重复组 0。`db\history` 下仅发现一个旧 migration 目录占位路径，没有数据库文件；非本任务范围的 `HistoryStore` owner 和 legacy resource/unauthenticated 表保留。

AP 候选的直接 DEV 数据与 UI 有效 Recent 对齐：A Radio 0；B Radio 4/LLDP 7；C Radio 原始聚合 16 但按 Radio 槽位每槽不超过 10，UI/API 返回有效窗口 10，C LLDP 10。B/C Optical 的 AP/SWITCH 各侧均保留 Current/Recent 数据；FIT-AP 光衰页面按既定 Current-only 语义展示。

### Code closure

本轮新增的最小修复是让 FIT-AP 和通用设备 Recent 计数及明细总数在 API 层统一封顶 10，防止旧数据聚合计数把 UI 显示成可继续翻页的永久 History。相关定向 Python、Renderer、Electron 测试通过；Renderer `vue-tsc`/build、Electron typecheck/build main、Ruff、compile 和 Change Impact(`L2`) 通过。

Python 全量为 `4493 passed, 26 failed, 2 skipped`。26 个失败属于既有 architecture/direct-SQL、缺失 `tests/storage/README.md`、AC optical fixture、Ground archive、Site lifecycle 等 baseline；本任务新增的 Recent 相关测试均通过，`NEW_TEST_FAILURES=0`。完整 `local_gate --mode full` 仍按既有 baseline 记为 FAIL，不通过删测或弱化断言掩盖。
