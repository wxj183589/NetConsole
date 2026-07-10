# NetConsole 更新日志

## 未发布 - 2026-07-10

### 架构
- 已建立 NetConsole 分层架构规范。
- 已引入并整理 Job Center 规则，以领域注册表替代巨型任务分发。
- 已明确 UI 线程治理、Worker Process、Export Process 和 Domain Service 边界。
- 已为后续 AC / SNMP / MR / iperf / Export / Agent 开发提供统一规范。
- 已将车载 MR 在线 SSH 实时采集迁入长运行 Job / Worker Process，页面不再执行 SSH、采集循环、大日志解析或停止后打包。
- 已集中在线 MR 命令序列与会话路径，停止时协作取消并清理 SSH/文件句柄，压缩失败保留原始日志；Worker stdout 仅输出 UTF-8 JSONL。
- 在线 MR 手动/实时解析与分析报告分别接入 Job Center 和 Export Process；Agent 本次未实现，仅预留可替换执行端边界。
- SNMP GET、GETNEXT、GETBULK、WALK、SET 查询执行链路已接入 `snmp_query_execute`；Worker 负责创建查询服务、格式化结果和写入兼容缓存，页面不再直连 SNMP Client 或查询 QThread。
- SNMP 查询支持统一进度、异常与协作取消事件；MIB 浏览/搜索、全局 MIB 仓库、H3C 映射、Trap、Poll 和产品参考库保持原状。
- 新增 `snmp_collection_execute` 与 `SnmpCollectionService`，支持多设备、多 OID、5～50 并发、失败重试、部分成功汇总和协作取消；每设备使用独立 SNMP Client。
- SNMP 批量结果以原子 JSON 缓存保存任务摘要和去敏 records，包含 device_id、OID、value、timestamp、success、error，不新增数据库表。
- 新增 `services/ac` facade，FIT-AP/AP状态/Radio/LLDP 资源刷新复用既有 `ac_fit_ap_resources_refresh` 进入 Job Center；H3C CLI collector、parser、raw log 和 repository 规则保持不变。
- AC 页面不再为资源刷新创建 `AcResourceCollectThread`；取消、异常和完成改为统一 Job 终态。SNMP Collection 仅在提供明确 OID 与已验证映射器时使用，避免未经验证的数据覆盖 FIT-AP 主数据。

### 测试
- 新增可按测试模块启用的 Qt 页面生命周期 fixture，修复 Vehicle MR 测试全部通过后在 pytest 最终 GC 阶段触发 `0xc0000374` 的问题。
- Qt fixture 保持单一 `QApplication` 强引用并逐条清理顶层窗口；带异步任务的页面不做全局强制清理，避免中断仍在运行的 QProcess。
- 新增 SNMP 请求模型兼容、五类操作 handler、Worker JSONL 成功/异常/取消、结果缓存和页面提交/状态恢复测试。
- 新增 100 设备并发、部分 timeout、重试、停止策略、取消、JSONL、去敏缓存和内部提交接口测试；增加默认跳过的真实设备 GET/WALK/GETBULK smoke 框架。
- 新增 AC Domain 的 CLI/SNMP 策略、未映射拒绝、Job finished/failed/cancelled、页面 Job 提交和依赖边界测试；AC 既有业务回归保持通过。

## v1.3.7 - 2026-07-08

### 新增
- 新增磁盘清理入口，用于扫描和清理软件运行日志、缓存和临时文件。
- 新增开源许可说明入口，展示第三方组件、版本、许可证和用途。

### 优化
- 优化启动流程，主窗口优先显示，日志清理和缓存清理延后到后台执行。
- 优化 MR 原始 MESH 日志分析大数据页签加载体验，减少 UI 卡顿。
- 优化车载 MR 离线收集分析 Excel 报告，默认输出诊断型汇总、问题、切换、MESH 质量和证据类 Sheet，不再默认导出大体量明细和趋势图。
- 优化 MR 原始 MESH 链路明细导出字段，移除“归属来源”和“Peer Radio MAC”，保留现场排查需要的 Peer MAC、对端射频口、归属信息和源定位字段。
- 优化文件管理设备侧操作为只读下载模式。

### 修复
- 修复车载 MR 收集分析图表 tooltip 残留和遮挡问题。
- 修复功能开关默认注册和空值回退导致的模块页丢失问题。
- 修复 MR 原始 MESH 主链路建链顺序和 Active 主链路区段 RSSI 统计不一致问题，确保平均、最低、最高和 P10 RSSI 来自同一组有效样本，缺失数据统一显示为 N/A。
- 修复 MR 原始 MESH 导出中“平均 RSSI/最高 RSSI 有值但最低 RSSI 为空”的问题，单样本区段保持平均、最低、最高一致。

## v1.3.6 - 2026-07-06

### 优化
- 优化车载 MR 在线收集、Mesh 日志分析和轨道交通相关页面体验。
- 增强日志中心分页、中文化和运行日志清理能力。
- 优化无线扫描页面的基础交互和导出体验。

### 修复
- 修复部分设备采集和解析结果显示不一致问题。

## v1.0.0 - 2026-06-12

### 新增
- 初始版本包含设备管理、无线扫描、车载MR在线收集和基础日志查看能力。
