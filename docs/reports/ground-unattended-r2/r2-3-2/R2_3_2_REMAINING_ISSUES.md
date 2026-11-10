# R2.3.2 剩余问题与下一阶段

1. `FULL_LOCAL_GATE=PARTIAL`：全量 Python 有 5,624 passed / 36 failed / 2 skipped，失败集中在既有 Mesh/DataRoot/生产维护/文档治理；architecture guards、docs path guards 和既有 Mesh trailing whitespace 仍失败。独立 Renderer 全量、Electron 全量和 20,000 ingress 复跑均通过，未修改门禁断言掩盖基线差异。
2. `package-smoke=NOT_AVAILABLE`：正式安装器保护要求最终提交已 push 且 HEAD 与 upstream 对齐；本轮明确 `Push=NO`，因此不生成发布 PASS，不把发布候选写成可发布。
3. `LONG_STABILITY_8H=WAIVED_BY_USER`：长稳真实运行 `24,000.379 s`，用户取消剩余 1.5 小时且不补跑；`SOAK_ACCEPTANCE=PASS_WITH_EVIDENCE_CAVEATS`，不得描述为 8 小时 PASS。机器可读状态为 `PARTIAL + USER_WAIVED_REMAINING_DURATION`。
4. 事件时间来自脱敏 Fixture 的 `DEVICE_TIMESTAMP`；Event/Receive/Raw Persist/Parse Complete/Position Commit 已在位置事件详情中记录，但长稳没有逐事件 `UI_AVAILABLE_TIME` 埋点。GUI 截图证明页面可见，不将截图时间冒充精确 UI 延迟样本。
5. 长稳 AC 查询耗时未单独持久化，因此报告只给出 376 polls、成功/timeout/partial 等真实计数，不伪造查询毫秒值。真实 AC SSH、现场 AP/MR、现场无线和设备时钟仍未覆盖。
6. 压缩队列曾出现有界 `compression queue is full`，压缩失败为 0，原始 NDJSON 保留；下一阶段按现场 EPS、磁盘和压缩消费能力确认存储规格。
7. `FIELD_ACCEPTANCE=NOT_AVAILABLE`，不能用本地 loopback/synthetic 数据替代车辆、AP、AC、WLAN 现场验收。

## 下一阶段清单

- 冻结当前 Syslog/Position/AC/Heartbeat 核心行为，继续使用新增的阶段延迟和队列指标。
- 补充部署、启动、停止、Backend 重启和现场故障恢复说明；保持 AC 不成为位置更新前置条件。
- 在批准的推送/集成流程中重新执行 package-smoke 和 Full Gate，不在本地绕过 upstream/dirty 保护。
- 具备真实设备和现场网络后，单独执行 Field Acceptance，不把本地结论升级为现场结论。
