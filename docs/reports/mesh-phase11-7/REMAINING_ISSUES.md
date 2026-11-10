# Phase 11.7 遗留问题与解除条件

## 阻断 COMPLETE 的验收缺口

1. 当前源码真实 Electron + 宁波 MESH 运行态验收和 1920×1080 截图未执行。启动开发 runtime 会初始化后端数据库；未确认它在该真实库上的只读/不迁移保证，也缺少当前可用的原生窗口交互截图控制。
2. 真实数据完整分析链（目录索引 → API → Renderer → ECharts）未在本轮运行；只有既有 Service 直接只读 SQL/DTO 证据。
3. 当前大型真实日志的首次加载性能、首图时间、完整可交互时间和峰值内存未测量。
4. 慢查询、超时、取消、快速切换、延迟绘制、并发乱序和页面退出的运行态故障注入未执行；自动化覆盖不等于真实运行态注入。
5. 30分钟/100次操作长稳数据缺失，Canvas/ECharts/listener/request/cache 曲线未记录。
6. MESH Excel/WPS GUI 打开、筛选、冻结、精度、保存与大文件性能未执行。
7. Phase 11.7 最终报告提交后的 MESH 集成 Gate 未执行。

## 范围说明

- 本轮未确认新的 MESH 产品缺陷，未改业务源码。
- 任务书“4个业务工作区”列举日志解析入口；当前产品导航报告为七项，日志解析摘要集成在内容/报告中。需要在真实 UI 中确认该产品定义是否仍要求独立入口。
- 任务书写“十二组双端指标”，同时列出 RSSI、CPU、Memory、TxBusy、RxBusy、Rate、Noise、Tx、Rx、Retry、Err、GARP、MulJoin 共13个指标项。当前实现按本端/对端曲线组展现，验收报告按指标项而非误算为12项；UI 视觉实验需按产品实际分组口径完成。
- 现存 DataRoot/Ground 和 Job Center dirty 修改是并行工作，必须在提交时排除。

## 下一步

1. 准备不会在真实 Authority 写入 schema 的受控当前源码 Electron 启动方式，并有原生窗口操作/截图能力。
2. 对宁波地铁12号线指定会话执行真实 MESH UI、性能、慢查询和长稳验收；每个证据绑定当前 commit、会话和操作。
3. 通过 MESH Export 流程生成文件并在现有 WPS/Excel GUI 中实际检查，不干扰用户当前 WPS 会话。
4. 完成所有门槛后重跑 MESH Export/共享图表消费者和适用 Gate，再评估能否将 `MESH_STATUS` 改为 `COMPLETE`。
