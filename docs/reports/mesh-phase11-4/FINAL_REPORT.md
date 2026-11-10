# Mesh Phase 11.4 交付与验收边界

日期：2026-11-09。分支：`codex-A/mesh-analysis-scope-ui-optimization`。基础HEAD `ec174410dc3b491bcb3d3a29fc8df25012fee8f6`。本报告与实现统一本地提交，具体hash见DevStatus与git log；不Push、不Merge、不Release。

## 当前源码内容

- 主链路详情采用更大的中文指标字号和本端/对端列。
- Tooltip按指标双端并列，counter显示累计/前值/增量/实际间隔/每秒值/状态，图表预留285px高度。
- 原始选点通过selectedSample传入Tooltip，普通指标sampleField及counterField均取自同一选中记录；缺失不拼入下采样记录。
- 任意横坐标Shift选点、Ctrl移动、Esc退出固定、共享窗口和指针沿用现有查询/缓存/取消机制。
- 监控面板以IntersectionObserver及240px预加载边界按可见性加载；隐藏指标不查，四张counter图共享进行中请求和成功源结果，顺序滚入不重复查询。
- 图表结果缓存和源查询缓存分别限制16项；普通导航直接复用，显式刷新失效并重新查询，旧finished事件不能结束新QUERYING。
- 完整counter窗口提供最近采样索引，所有图表selectedSample与右侧12项counter累计/前值/增量/实际间隔/速率来自同一原始记录；无效focus拒绝，Esc清除选点及详情。

## 本次实际测试

在 `apps/desktop_renderer` 执行：

```text
pnpm exec vitest run src/components/mesh-analysis/meshMonitorTooltip.test.ts src/components/mesh-analysis/MeshMetricChart.test.ts src/components/mesh-analysis/meshBusinessMetrics.test.ts src/components/mesh-analysis/MeshPhase11Workbench.test.ts
```

实跑：4文件、82/82通过（2026-11-09 17:28，Workbench31、Tooltip21、图表21、指标9）。覆盖selected raw与旧params完全不同的12项counter逐格隔离、受控可见性加载/顺序counter源复用、显式刷新及独立16项缓存预算、图表交互、12指标分组、Workbench最近采样/固定/缓存/取消/竞态。此结果是组件与纯逻辑自动验证，使用测试mock，不能代替实际ECharts/Electron渲染。

真实开发数据以SQLite URI mode=ro与query_only读取连续三点，独立手算对当前sampling源码的12字段current/previous/delta/interval_seconds/per_second全部一致，DB与raw前后hash及首次API核验hash均相同。见 [真实数据报告](../mesh-phase11-2/REAL_DATA_VALIDATION.md) 与 [离线JSON](../mesh-phase11-2/real-counter-three-points-offline.json)。

## 未完成与风险

**当前源码真实Electron验收未完成。** 原runtime已退出，启动被自动策略以 `blocked by policy` 拒绝。未变更方式绕过、未生成截图。实际1920×1080/DPR1可读性、Tooltip边界、输入事件及请求数量、当前API序列化均待真实环境复验。

最终集成自动化：完整Renderer206文件1505项全部通过；vue-tsc -b及Vite build通过，独立vue-tsc --noEmit通过，存在大于500kB chunk提示。后端组合141项通过，最后sampler/nearest边界25项通过；文档布局13项、Ruff、Workspace布局与diff检查通过。架构12项中11项通过，设备命令审计把基础HEAD已有docstring中的display formatting or unit conversion误判为命令，保留失败，不宣称全绿。本次未执行产品全量Python、Electron测试套件、打包或发布。

当前Service真实只读SQL/DTO追加验证：三目标nearest及12项counter元数据与普通counter查询、独立计算一致；默认末尾五分钟465条→240条，2190.47/2306.04ms；DB/raw指纹不变。首次nearest raw零链路扫描690.73ms。详见Phase11.2真实数据报告。该证据不能替代运行态API与GUI。

## 数据影响与交接

未复制DB/Site、未改Production或真实业务数据。核验DB/raw size、mtime和SHA256均未变；内部追溯信息保留。

结论：自动测试和离线三点核验通过；GUI门禁保持BLOCKED，不能报告Phase11.4全部验收完成。入口见 [STATUS.md](STATUS.md)、[Tooltip验证](TOOLTIP_VALIDATION.md)、[时间选择验证](TIME_SELECTION_VALIDATION.md)、[Electron验收](ELECTRON_UI_ACCEPTANCE.md)。
