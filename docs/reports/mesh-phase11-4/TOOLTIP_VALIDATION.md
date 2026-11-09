# Tooltip 验证

日期：2026-11-09。

## 源码检查

- `meshMonitorTooltip.ts` 使用时间、AP名称和地址作为单份身份头，按指标排列本端/对端列。
- counter 每组6行：当前累计值、上次累计值、区间增量、实际间隔（秒）、每秒速率（次/s）、状态。
- `MeshMetricChart.vue` 在有效时间选择时传入 selectedSample；Tooltip 第4参数提供原始样本，sampleField映射普通指标，counterField映射计数器。
- RSSI 从原始 DTO 的 local_rssi_db/peer_rssi_db 取值；缺失值显示暂无数据，不从下采样点补值。
- AP显示值进行HTML转义；普通业务Tooltip不含来源、解析规则或内部记录ID。
- 当前counter图高285px，Tooltip设置max-height270px；实际边缘位置、内容完整性和长文本布局仍需GUI检查。

## 自动测试

文件：`apps/desktop_renderer/src/components/mesh-analysis/meshMonitorTooltip.test.ts`，21个用例。

覆盖：双端RSSI/CPU、身份仅一次、Tx/Rx/Retry/Err/GARP/MulJoin共12字段、6行并列表单元格精确值、首点/重置/长间隔/链路切换/无效时间说明、空数据和HTML转义。

新增selected raw隔离证据：

1. RSSI和CPU传入与params完全不同的时间、AP、地址与双端数值，逐单元格只显示原始选点值。
2. 为12条counter曲线构造各自不同的旧sample，原始选点提供独立12字段元数据；6张指标表的本端/对端累计、前值、增量、间隔、每秒值逐项等于selected raw。
3. 原始选点缺失counter时，各数值为空，不回填旧sample的数据。

四组定向测试合计82/82通过；命令见 [FINAL_REPORT.md](FINAL_REPORT.md)。Workbench另验证12项counter右侧详情与所有图表selectedSample来自同一原始记录。

## 真实数据与限制

真实开发数据三点的0.034秒/0.966秒间隔及12字段元数据与当前sampling源码一致，见 [真实数据报告](../mesh-phase11-2/REAL_DATA_VALIDATION.md)。该证据不证明运行API序列化或真实ElectronTooltip布局。

真实Electron悬浮截图、Tooltip与右侧详情视觉对照、边缘防遮挡未执行，原因见 [ELECTRON_UI_ACCEPTANCE.md](ELECTRON_UI_ACCEPTANCE.md)。
