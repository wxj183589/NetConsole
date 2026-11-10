# R2.3.2 位置准确性

## 事件模型

合成链路覆盖 AP-A→AP-B→AP-C、重复、旧 Event Time、乱序、未知 AP、坏格式和最终有效 AP。Position Engine 按有效事件时间与接收序号处理；重复只增加审计计数，旧事件不能覆盖新状态；中间历史保留，批量合并只减少中间 projection/UI 写入。

## 长稳结果

- 长稳 W-MESH 事件 28,393 个：`POSITION_UPDATED=27,010`、`OUT_OF_ORDER_POSITION_EVENT=826`、`POSITION_RETAINED_UNRESOLVED=557`。
- 状态累计重复事件 1,521、乱序事件 826；未知 AP 保持 unresolved，不强行关联；坏格式仍保留 Raw，不清空已有位置。
- 最终 AP-B 为 `100/100 MR`，位置状态行 100，历史记录保留。
- CT/CW 作为独立 MR endpoint；未识别 MR/AP 不强行关联；不完整事件不能清空已有位置；AC reconciliation 不做无条件覆盖。

## Electron AP 切换交叉验证

在 `r2_3_2-electron-gui-switch-023-20261110` 中，`test-mr-001/CT` 的同一运行前后截图分别显示 `R232-AP-A-001` 和 `R232-AP-B-001`。SQLite 最终状态为 `current=B`、`previous=A`、`VALID/SYSLOG`；目标历史含 A 21 条、B 19 条事件，重复计数 147，乱序计数 0。旧 AC 快照保护由 AC 专项 119 passed 覆盖。

## 边界

上述准确率是脱敏 Fixture 与合成 inventory 内的可复现准确率。没有真实设备时，不能推导现场 AP 命名、设备时钟或 UDP 丢包条件下的现场准确率。`POSITION_LOCAL_ACCEPTANCE=PASS_WITH_EVIDENCE_CAVEATS`。
