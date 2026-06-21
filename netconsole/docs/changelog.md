v1.2.0
- MESH Log Analysis: added structured analysis report generation with Excel export, including overview, active primary-link segments, switch order, flap detection, link establishment order, peer lifecycle, no-active/multi-active windows, RSSI statistics, channel busy statistics, raw events and parse issues.
- MESH Log Analysis: added a report settings dialog, background report worker, progress updates, cancel handling and temporary-file cleanup for Excel export.
- Startup and navigation: improved startup/preload experience, loading overlay behavior and version text consistency across splash, changelog, main window and About views.
- Rail Transit Trackside AP Service: refined navigation placement, localized visible fields, hidden internal connection/status columns from UI/export, and fixed interface/optical history dialog behavior.
- Packaging: fixed runtime tool path resolution and ensured bundled network tools are discoverable after clean builds.
- Onboard MR Online Collection UI: reorganized the page into connection, collection period, radio parameters, high-frequency ping, advanced parameters, live status and detail tabs, with bounded input widths, collapsible advanced settings and persistent table column widths.
- Onboard MR Online Collection: added Fast Pinger v3 discovery/version detection, high-frequency ping command construction, output parsing, summary parsing, ping sample persistence and Active-segment aggregation.
- Onboard MR Online Collection: added repeat command definitions for mesh link, channel busy, AP radio statistics, switch-history latest and interface rate collection, plus Ctrl+C repeat stop handling.
- Online diagnosis storage: switched online sessions to rail_transit/online_mr session layout and online_diagnosis.sqlite with ping, interface rate, terminal event and latest switch-history tables.
- Packaging: included tools/fping_v3/Fping_v3.exe in clean build runtime data and updated clean build allow-list.
- Rail Transit: added Onboard MR Online Collection with independent per-MR long sessions, max-2 concurrency guard, SSH/Telnet connection parameters, collection intervals, auto reconnect, session history, raw output and collector log views.
- Online MR persistence: each collection session now writes session_meta.json, flushed raw command logs, reconnect.log and parsed/live_records.sqlite with live_samples, live_mesh_links, channel busy, raw indexes, events and collector logs.
- Online MR reliability: added strict initialization command ordering, NetConsole-side periodic scheduling, safe stop flow, stale active-session recovery to ABORTED and throttled UI refresh.
- Tests: added online MR collection coverage for concurrency, init order, scheduling, reconnect, raw/sqlite/meta persistence, recovery, UI throttle and parse-failure continuation.
- 轨道交通：新增 MESH 日志分析能力，按车载 MR 独立保存历史日志、索引来源文件、链路明细、事件和解析问题。
- Peer 趋势窗口：保留接收信号、RSSI 与底噪、信道负载、当前主链路 RSSI、Active 链路信道负载五类图表，并支持 Hover、滚轮缩放、拖拽平移、时间滚动条和锚点居中。
- 当前主链路 RSSI：简化原 ACTIVE / Next Active 图，仅显示当前 Active MR 侧原始 RSSI，保留 Active 切换竖线，不再显示 Next Active 曲线、Next Peer 标记或 Peer 侧 RSSI。
- Active 链路信道负载：仅显示当前 Active MR 侧 TxBusy/RxBusy，移除 Peer 侧和下一主链路负载曲线。
- 性能与稳定性：优化 MR 切换防抖、仓储缓存、当前标签懒加载、大数据降采样和 Hover 缓存，补充 MESH 专项测试与全量回归。

v1.1.0
- 配置采集中心：支持 running/saved 配置采集、保存、快照归档、清洗后差异对比和中英文界面。
- 文件管理：新增独立双栏浏览下载页面，支持设备文件选择、列宽持久化、MESH 日志快速选择与本地命名规则。
- 设备管理：新增诊断下载、设备分组、详情入口和 AC 网页打开能力。
- AC 管理：修复 HTTPS 端口采集、旧站点数据库字段补齐、保存失败提示和默认端口回退逻辑。
- 稳定性：完善批量/顺序下载统计、配置与文件采集测试覆盖。

v1.0.0
- 初始版本发布
- AC管理模块
- FIT-AP光衰分析
- LLDP邻居解析
- 轨旁AP业务
