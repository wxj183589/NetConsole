# Phase 11.5 业务计算与图表交互交付（2026-11-09）

本轮在 `codex-A/mesh-analysis-scope-ui-optimization`、基线 `dec6b1c344ca433cbbd8007ea52ed92314bdff4a` 上完成 Mesh 业务统计与主链路监控收敛：GARP/MulJoin 拆为独立图表并继续共享一次 counters 查询；本端/对端颜色统一为绿色/橙色；AP 统计按物理 AP、ACTIVE/STANDBY、Radio 分组，提供最近有效 RSSI、低信号数量/比例、阈值持久化和筛选；INFO 级 LinkCnt=0 占位从普通解析异常中排除，底层记录仍保留。AP 请求在离页、切换 Session 和组件销毁时主动取消，旧 generation 结果不会覆盖当前页面。

普通滚轮保持页面自然滚动，Shift+滚轮才以指针时间为锚点缩放，所有主链图表共享时间窗；ECharts `finished` 事件作为绘制完成边界。轨旁 AP 彩虹/冲突感知稳定颜色分配已在现有 `tracksideSeriesColors.ts` 中核验，本轮未重复实现或改写该独立规则。

| 状态项 | 结果 |
|---|---|
| CODE_STATUS | PASS |
| UNIT_TEST_STATUS | PASS（Renderer 核心 4 文件 85/85；全 Renderer 206 文件、1508/1508） |
| PYTHON_TEST_STATUS | PASS（Mesh 回归 197 passed；统计定向 36 passed） |
| RENDERER_STATUS | PASS（`vue-tsc -b`、`pnpm run build`） |
| ELECTRON_UI_STATUS | BLOCKED（启动仍受自动审批策略阻止，未伪造截图） |
| REAL_DATA_STATUS | PASS_WITH_LIMITATIONS（`docs/reports/mesh-phase11-2/real-service-query-validation.json` 只读证据；未启动 runtime） |
| PERFORMANCE_STATUS | PARTIAL（真实窄查询已测；未完成 Electron 端 108700 条长稳/内存对照） |
| MEMORY_STATUS | NOT_TESTED（本轮未做长时间 Electron 内存曲线） |
| ARCHITECTURE_STATUS | PASS（复用既有 Service/Router/DTO/缓存，无 schema 迁移） |
| GIT_STATUS | LOCAL_ONLY（产品与 DevStatus 本地提交，不 Push/Merge/Release） |

数据边界：未修改 `D:\NetConsoleData`、`D:\NetConsoleData-dev` 中的业务数据、数据库 Schema 或设备状态；真实服务证据使用只读 SQLite 连接。构建仅产生可重建的 Renderer `dist/` 输出。剩余人工验收为 Electron 1920×1080 交互、真实大数据长稳、内存曲线和截图。

# Phase 9 最终报告

## 2026-11-09 加载状态与业务界面精简补充

本补充覆盖 MR 原始 MESH 分析页的分阶段加载反馈和普通业务字段审查。页面统一使用 `IDLE/PREPARING/QUERYING/PROCESSING/RENDERING/COMPLETED/ERROR/CANCELLED`，首次加载以短延迟骨架屏预留统计卡、图表和表格高度；主链 RSSI、轨旁 AP 信号、空口负载保持独立状态，并在 ECharts 实际完成绘制后才进入 `COMPLETED`。请求取消时清理 AbortController、generation 和图表状态，旧结果不能覆盖当前选择；缓存和无有效数据沿用明确文案。

普通业务表格移除来源文件/类型、身份来源、匹配规则、原始/规范 Peer MAC、Peer Radio MAC、行号、内部记录 ID、技术诊断预算等字段，统一使用 AP 名称、AP MAC、对端射频口和运维指标。底层接口、解析追溯信息、诊断导出和删除/导入内部操作仍保留。

| 状态项 | 结果 |
|---|---|
| LOADING_STATE_STATUS | PASS |
| DATABASE_QUERY_FEEDBACK_STATUS | PASS_WITH_LIMITATIONS |
| DATA_PROCESSING_FEEDBACK_STATUS | PASS |
| CHART_RENDER_FEEDBACK_STATUS | PASS |
| PER_CHART_LOADING_STATUS | PASS |
| CANCELLATION_STATUS | PASS |
| CACHE_LOADING_STATUS | PASS |
| ERROR_STATE_STATUS | PASS_WITH_LIMITATIONS |
| BUSINESS_UI_FIELD_AUDIT_STATUS | PASS |

验证：Renderer 加载与图表挂载 `2 files / 34 passed`，页面契约 `5 passed`，业务列行为 `1 passed`，`vue-tsc -b` 和 `pnpm run build` 通过，`git diff --check` 通过。完整行为套件仍有既有 RSSI/KeepAlive 异步时序失败，未将其升级为本补充的成功证据；真实数据库慢查询、故障注入、Electron/Windows DPI 和真实数据仍待人工验收。

本阶段完成 Mesh 业务范围治理、完整原始链路字段导出、单链路排除和页面信息层次/初始视口优化。业务 Excel 删除重复的 `Peer Radio MAC`、匹配规则、身份来源；保留原始 Peer MAC、`PEER Radio`、来源文件和行号，并在业务/诊断两种模式保留全部 L/P RSSI、Noise、Rate、CPU、Memory、Busy、TxDesFreeCnt、Tx/Rx、Retry/Err、GARP、MulJoin 原始数值。诊断模式保留完整身份字段。

车辆段和停车场默认排除，正式站点类型优先，未知归属保持 UNKNOWN。过滤在备链判定和风险分段前执行，统一影响 AP/风险统计和派生工作表，原始日志与解析数据完整保留。主链路图以 ACTIVE 数据为主，轨旁图保留逐采样 ACTIVE/STANDBY 角色；Tooltip 支持双击固定、再次双击或 Esc 解锁，固定后不随指针、缩放或时间轴拖动改写；普通和备链浮窗去除重复 MAC/本端 Radio，切换事件只显示 AP 名称与 RSSI，并显示可确认的对端射频口。图表首次打开定位有效样本范围，同时保留完整 Navigator、缩放、锁定和全时段恢复。

| 状态项 | 结果 |
|---|---|
| IMPLEMENTATION_STATUS | PASS |
| EXCEL_FIELD_STATUS | PARTIAL（原始 ZIP 不可见） |
| DEPOT_FILTER_STATUS | PASS |
| PARKING_FILTER_STATUS | PASS |
| SINGLE_LINK_STATUS | PASS |
| RAW_DATA_INTEGRITY_STATUS | PASS（无真实数据写入） |
| UI_STATUS | PASS_WITH_LIMITATIONS |
| CHART_STATUS | PASS_WITH_LIMITATIONS |
| PERFORMANCE_STATUS | PARTIAL |
| FULL_GATE_STATUS | PASS |
| GIT_STATUS | PASS（本地提交，未 Push/Merge/Release） |
| RAW_MESH_FIELD_PRESERVATION_STATUS | PASS（Parser/SQLite/API 已有字段；业务/诊断 XLSX 合成一致性通过） |
| ACTIVE_ONLY_STATUS | PASS（主链路路径按 ACTIVE 事实返回；STANDBY 仅作为上下文） |
| SINGLE_AP_HISTORY_STATUS | PASS_WITH_LIMITATIONS（现有 Peer 连续访问/轨旁序列支持历史主备角色；未做真实样本验收） |
| AP_ROLE_TRANSITION_STATUS | PASS（按每条采样 LinkState 建序列并保留切换事件） |
| COUNTER_BASELINE_STATUS | PASS_WITH_LIMITATIONS（已补齐 Tx/Rx、Retry/Err、GARP/MulJoin 增量与每秒速率，并按完整链路身份分区；完整多指标趋势 UI 尚未接入） |
| ACTIVE_SWITCH_STATUS | PASS（合成切换事件和图表节点定向回归） |
| COMPACT_KPI_STATUS | PASS（统计区改为紧凑栏，点击行为保留） |
| UI_RESPONSIVE_STATUS | PASS_WITH_LIMITATIONS（Renderer/typecheck；真实 Windows 125% 与 GUI 仍待） |
| TOOLTIP_PIN_STATUS | PASS（主链路、轨旁和空口忙时 Tooltip 双击固定/解锁、Esc 清理） |
| TOOLTIP_FIELD_SIMPLIFICATION_STATUS | PASS（主链路/备链去除重复 MAC/本端 Radio，切换事件仅保留 AP 名称与 RSSI） |
| PEER_RADIO_PORT_STATUS | PASS（radio1/radio2 显示 1/2，无法解析显示 —） |
| TOOLTIP_LAYOUT_STATUS | PASS_WITH_LIMITATIONS（容器边界/内部滚动已实现，未做真实窗口截图验收） |
| TOOLTIP_REGRESSION_STATUS | PASS（本轮定向 Tooltip/挂载/trackside 回归 4 files / 54 tests passed；`vue-tsc -b` passed） |
| LOADING_STATE_STATUS | PASS（统一 IDLE/PREPARING/QUERYING/PROCESSING/RENDERING/COMPLETED/ERROR/CANCELLED 状态与阶段文案） |
| DATABASE_QUERY_FEEDBACK_STATUS | PASS_WITH_LIMITATIONS（页面、会话、主链、轨旁、单 AP 空口查询接入真实请求边界；无伪造数据库百分比） |
| DATA_PROCESSING_FEEDBACK_STATUS | PASS（响应后按实际缓存构建、整理、降采样和角色识别阶段更新） |
| CHART_RENDER_FEEDBACK_STATUS | PASS（ECharts setOption/resize 完成后由 render-complete 事件标记完成，异常发 render-error） |
| PER_CHART_LOADING_STATUS | PASS（主链 RSSI、轨旁 AP、空口负载独立状态，单图错误不阻塞其他图） |
| CANCELLATION_STATUS | PASS_WITH_LIMITATIONS（已有 AbortController/generation 与状态清理接入；页面关闭和真实慢查询 GUI 尚未人工验收） |
| CACHE_LOADING_STATUS | PASS（窗口缓存恢复显示缓存命中并仍等待实际图表渲染完成） |
| ERROR_STATE_STATUS | PASS_WITH_LIMITATIONS（加载、无有效数据、查询/绘图错误、取消文案已区分；真实后端故障注入未执行） |

产品分支：`codex-A/mesh-analysis-scope-ui-optimization`；既有实现提交：`225e05d2`、`2a6ea78e`、`43eef05d`；本轮加载状态提交：`57ee2eaf`。DevStatus 单独提交：`6f2679e`，两个仓库均不推送。

限制：用户要求的原始 Excel ZIP 在本轮附件目录不可见，不能声称真实样本字段或三视口人工截图已独立复核；Windows 原生 DPI、Excel/WPS GUI、真实局点与设备仍待外部验收。Noise/CPU/内存/Rate/TxDesFree、完整 Tx/Rx/Retry/Err/GARP/MulJoin 趋势分组及单 AP 历史选择器仍未接入主页面；当前计数器后端已完成合成数据回归，但不把未接入的图表与真实样本验收写成 PASS。加载状态本轮完成 Renderer 定向验证，未执行真实数据库慢查询、故障注入或 Electron 三尺寸截图。`FULL_GATE_STATUS=PASS` 仅引用 2026-11-08 的既有本地 Gate 证据，本轮按要求未重复全量 Gate。
