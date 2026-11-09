# Mesh Phase 11.4 实施与验证计划

日期：2026-11-09。范围：主链路右侧详情可读性、两端 Tooltip、任意时间定位和共享时间选择。

## 实施范围

1. 沿用现有 Workbench、MeshMetricChart、指标构建器和 links 查询，不新增日志解析或身份映射路径。
2. 详情展示中文业务指标、本端/对端；保留底层原始证据，不将内部字段混入普通 UI。
3. Tooltip 以指标分组、本端/对端并列；counter 展示本次累计、上次累计、增量、实际间隔、每秒值和状态。
4. 选中原始样本时，Tooltip 与右侧详情使用同一条记录，不能拼入图表下采样点的数据。
5. Shift+左键定位任意 X 的最近有效 ACTIVE 毫秒采样；Ctrl 移动复用当前窗口索引或受当前条件约束的最近采样查询；Esc 退出固定。
6. 普通滚轮留给页面滚动；Shift 滚轮改变共享窗口。保留取消、请求代次、节流与缓存边界。
7. 每个监控面板以IntersectionObserver及240px预加载边界独立触发查询，隐藏指标不查询；四张counter图共享查询结果。

## 验证顺序与证据

- 定向 Vitest：Tooltip 精确单元格与 selected raw 隔离、图表原生事件、Workbench 最近采样与竞态。
- 真实数据：开发 Authority 内 SQLite 只读三点，独立手算与当前源码比较，前后 hash 不变。
- 真实 Electron：1920×1080/DPR1 截图与前后交互 JSON，包括悬浮、固定、离开、Ctrl、Esc、共享窗口、字号与裁切。

## 当前执行边界

自动测试与离线真实数据核验已完成；新源码 Electron 因启动被自动策略以 `blocked by policy` 拒绝而未执行。不得以旧截图、静态页面或测试 mock 代替。详见 [STATUS.md](STATUS.md)。
