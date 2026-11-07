# R3 快速 Ping 隔离报告

Quick Ping 保持独立运行 ID、IP reservation、目标停止、最大活动任务数、Raw NDJSON、压缩队列和恢复流程。新增同一共享丢包事件表的 per-run 事件跟踪，事件详情含 train、CT/CW、AP/站点快照和恢复信息；事件开始时冻结 AP/站点，恢复记录最后成功 AP/站点，切换不会改写历史快照。UI 详情隐藏管理 IP，显示 MR、AP、站点和区间。

当前默认并发仍受已有 4 个活动任务和 32 个 in-flight 配置约束，未扩大默认并发。
