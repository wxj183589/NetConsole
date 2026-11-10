# 剩余问题与外部阻塞

## 外部阻塞

1. 本机没有 Excel 可执行文件；WPS 原生 GUI 已真实打开报告并验证可读，
   Excel GUI 标记 NOT_RUN / external blocker。
2. python -m scripts.check_workspace_layout 仍因既有
   D:\study\NetConsole-Workspace\docs 触发 UNAPPROVED_WORKSPACE_TOP_LEVEL。
   该目录不属于本轮 MESH 修改，未删除、移动或修改。

## 产品风险

1. 当前 Renderer heap 在反复全范围交互后达到约 2.00 GB usedJSHeapSize，
   虽低于约 4.30 GB limit 且没有 crash，但仍应在后续长期实际数据运行中
   继续关注。视觉样本上限、derived cache 上限和生命周期回收已生效。
2. 本轮复测的是受影响场景的持续空闲和重复交互；30 分钟长稳证据沿用
   Phase 11.9，不冒充为本轮 30 分钟结果。
3. 本机 WPS 版本已验证；未执行 Office Excel 专属渲染差异检查。

## 已关闭问题

- 全范围图表 Renderer crash：已以紧凑有界视觉样本和派生缓存复用修复，
  并完成真实 Electron 复测。
- Electron 原生 dblclick 在 ECharts 无 point data 时不固定：已增加 fallback
  和回归测试。
- 视觉降采样掩盖 Link gap 的风险：已强制保留 gap / continuity 边界。

本轮完成后停止，不自动进入下一阶段。
