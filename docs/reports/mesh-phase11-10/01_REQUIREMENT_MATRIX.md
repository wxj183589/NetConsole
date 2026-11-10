# Phase 11.10 需求矩阵

验收结论：PHASE_11_10=PASS_WITH_EXTERNAL_BLOCKERS。

本结论基于真实 Electron Main、真实 Renderer、真实 Python Service、隔离快照
mesh-phase11-8-run-001 和 1920×1080 Windows 窗口。PASS_WITH_EXTERNAL_BLOCKERS
只用于标记 Excel 可执行文件缺失和既有 Workspace 顶层 docs 规则阻塞；关键 MESH
业务交互已完成。

| 验收项目 | 结果 | 证据 |
| --- | --- | --- |
| 真实 Electron 运行 | PASS | Electron PID 42676；Renderer PID 61540；CDP 9224；Backend 8133 |
| 七项业务导航 | PASS | 分析概览、链路明细、RSSI、AP、主链路监控、切换事件、报告与来源均真实进入 |
| 主链路全部指标 | PASS | RSSI、CPU、Memory、TxBusy、RxBusy、Rate、Noise、TxDesFreeCnt、Tx/Rx、Retry、Err、GARP、MulJoin；13/13 |
| 本端/对端显示 | PASS | 右侧详情和链路表均显示本端与对端字段 |
| 普通滚轮缩放 | PASS | 08、09、10；25%、50%、75% 锚点窗口变化 |
| 时间轴同步 | PASS | 13、14、17；选择、浏览和缺口范围可追溯 |
| 绘图区外页面滚动 | PASS | 06；主链路工作台下方记录和历史区可见 |
| Tooltip | PASS | 11、12；普通 tooltip 与固定 tooltip 均真实显示 |
| Counter Tooltip | PASS | 11、12；previous、delta、interval、per-second、状态均显示 |
| 双击固定 / Esc | PASS | 12；双击固定，Esc 解除；增加原生 dblclick fallback 回归 |
| Shift 左键定位 | PASS | 13；选择时间并联动右侧详情 |
| Ctrl 动态浏览 | PASS | 14；Ctrl 浏览不改变固定选择 |
| 右侧详情 | PASS | 16；AP、MAC、Radio、建链、持续时长和指标对照可见 |
| AP / Radio 切换 | PASS | 15；Radio 2 真实空数据提示，Radio 1 恢复有效数据 |
| Link Continuity | PASS | 17；连续性边界和监控缺口真实绘制 |
| RSSI 分析 | PASS | 03；真实数据、图表和状态 |
| AP 情况 | PASS | 04；AP 统计、角色和射频筛选 |
| 切换事件 | PASS | 07；切换结果和事件表 |
| 链路明细 | PASS | 02；108700 条真实分页数据；角色和文本筛选均生效 |
| 分页与列设置 | PASS | 真实验证分页、角色筛选和“本端 CPU 利用率”列设置 |
| 已缓存范围零重复请求 | PASS | HTTP_SQL_TRACE；热范围复用时 HTTP=0、SQL=0 |
| 真实 Electron 截图 | PASS | 20 张当前源码运行截图，全部 1920×1080 |
| 导出文件结构 | PASS | 报告 16 worksheets；链路明细 5 worksheets；ZIP 校验通过 |
| Excel / WPS 原生 GUI | PASS_WITH_EXTERNAL_BLOCKERS | WPS 实际打开报告并关闭；Excel 可执行文件未安装 |
| ECharts 生命周期 | PASS | 重入和切换后 init 33 / dispose 30，active 3，native listeners 15 |
| MESH 回归 | PASS | Renderer 1541 tests；Python 491 tests；定向 106 tests |
| 数据完整性 | PASS | 隔离源、解析库、计数和导出校验均有记录 |
| Git 本地交付 | PASS | 仅本地 commit；不 push、不 merge、不 release |
| Workspace 检查 | BLOCKED | 既有顶层 D:\study\NetConsole-Workspace\docs 触发规则基线告警，未修改 |

未通过 / 外部阻塞不影响关键 MESH 交互：Excel 原生 GUI 未执行；Workspace
layout 检查为既有无关目录阻塞；本轮未把这两项伪装成 PASS。
