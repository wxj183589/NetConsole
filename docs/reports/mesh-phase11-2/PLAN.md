# Phase 11.2–11.4 实施与消费者审计

基线：ec174410；分支 codex-A/mesh-analysis-scope-ui-optimization。仅本地提交，不 push/merge/release。

## 风险与契约

- L3：NcDataTable 列偏好批量应用；API 增加可选计数器采样元数据。保留旧字段、数据库及原始日志。
- 表格写入方：用户应用列草稿；持久化：现有 tablePreferences；读取/缓存/展示：NcDataTable。列变化复用当前行数据，不发业务查询。取消不写偏好。
- 消费者：Devices、AC/FIT-AP、Trackside、MESH、Online MR、Ground、Tasks、Config、Files、Network。Registry 要求 renderer-full，执行完整 Renderer 测试及 build。
- 图表只改 MESH 专用组件；共享图表工具与其他领域不改。Tooltip、null gap、单位、viewport、选择和生命周期定向回归。
- 计数器由现有 Service 在降采样前计算；DTO 新增默认空元数据；旧 API/分页/导出默认行为保持兼容。只读查询，不迁移 schema。
- 导出沿用现有 Export Worker 与保存协调器，只审查/修改业务表头。
- 当前唯一 worktree 为主仓库，开工无 dirty；未发现本地并行共享路径修改。
- 不合并 main，本分支结果不能替代后续 main 合并后的 consumer gate。

## 实施顺序

1. 后端真实 dt、delta、rate 与基线边界；定向测试。
2. 列草稿一次应用；七项统一导航；中文成对指标与独立计数器图。
3. Tooltip、Shift 定位、Ctrl 动态浏览、Esc、同步窗口和请求保护。
4. 完整 Renderer 消费者测试、typecheck/build、后端定向、Ruff、架构检查。
5. 使用 D:/NetConsoleData-dev 只读真实 Electron 验收与三阶段报告；本地产品及 DevStatus 提交。

验收不得用静态 HTML 或 fixture 冒充真实 Electron；无证据项目标记未验证。
