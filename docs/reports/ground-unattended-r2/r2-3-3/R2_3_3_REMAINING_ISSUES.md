# R2.3.3 剩余问题与边界

1. Full Gate 仍为 `PARTIAL`：Python 全量有 38 项失败，主要是既有 Mesh 架构 findings、DataRoot/隔离运行根契约和文档治理；本轮未扩大范围修改这些模块。
2. package-smoke 退出码 1，正式安装器要求 Git 工作区干净；按任务约束未清理、未 push、未发布，安装版/免安装版尚未形成发布 PASS。
3. Electron GUI 运行和截图真实完成，但截图视口未显示当前 AP 详情行；`UI_VISIBLE_LATENCY=PARTIAL`，不能声称 AP-A→AP-B 的 UI Visible 已直接验证。
4. 归档缺少 Raw Persist、Parse Complete、Position Commit、UI Available 原始阶段时间，历史回放只能验证读取/解析/归并/对账，不能反推线上 P95/P99。
5. 归档 Ping 原始文件计数与 manifest/日汇总不一致：原始读取 216,743 行，manifest 207,524，日摘要 207,509；39 个目标的摘要存在差异，保留为 `PING_HISTORY=REVIEW`，未据此修改业务代码。
6. 归档 39,704 条 Syslog 的源 IP 身份仍是 `UNCONFIRMED_SOURCE_IP`；未扩大模糊身份匹配，也未把未识别 AP 强行关联。
7. 归档 AC 对账出现 AC_NEWER/STALE 分类；这是时间窗口/数据新鲜度限制，不是允许 AC 无条件覆盖 Syslog Current 的理由。
8. R2.3.2 长稳仍为 `LONG_STABILITY_8H=PARTIAL`，用户已豁免剩余时长；本轮没有重复 8 小时等待。
9. 真实 AC/SSH、真实设备、现场 UDP 网络丢包和跨机器安装验收未执行，`FIELD_ACCEPTANCE=NOT_AVAILABLE`。

以上均已在主报告和 `legacy-replay/` 归档回放报告中保留，未删除原 ZIP、未修改真实数据根。
