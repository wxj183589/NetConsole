# Phase 11.6 剩余阻塞

## BLOCKED

1. 真实 Electron GUI：启动/恢复 runtime 受历史自动审批策略 blocked by policy 阻断；缺少截图和实际交互证据。
2. Windows 原生 125% DPI：没有对应有效 Windows GUI 验收，浏览器 deviceScaleFactor 不能替代。
3. Excel/WPS 原生验收：只有 XLSX 结构/ZIP64 自动化，未执行打开、筛选、冻结、格式和保存。
4. 长稳和慢查询注入：没有 30 分钟/100 次操作内存曲线，也没有真实慢查询失败隔离证据。
5. 最终集成 Gate：本轮图表改动提交后仍需在包含本轮 commit 的最终集成组合重跑适用 consumer/full gate。

## 非阻塞的实现限制

- 真实完整原始日志字段覆盖仍需现场数据复核；当前 parser/DTO/fixture/只读 Service 证据一致。
- 历史基准是合成单轮，不推导长期 SLA。
- 工作树有用户既有 DataRoot 变更；本轮不能替其提交、回滚或纳入 MESH commit。

## 解除条件

提供可启动的 Electron/runtime 验收窗口、有效原生 DPI 环境、Excel/WPS GUI 或明确接受自动化结构验证边界，并在最终集成 commit 重跑 gate。
