# R2.3.2 最终本地验收

日期：2026-11-10

## 验收矩阵

```text
SYSLOG_LOCAL_ACCEPTANCE=PASS_WITH_EVIDENCE_CAVEATS
POSITION_LOCAL_ACCEPTANCE=PASS_WITH_EVIDENCE_CAVEATS
HEARTBEAT_LOCAL_ACCEPTANCE=PASS_WITH_EVIDENCE_CAVEATS
AC_LOCAL_ACCEPTANCE=PASS_WITH_EVIDENCE_CAVEATS
SOAK_ACCEPTANCE=PASS_WITH_EVIDENCE_CAVEATS
LONG_STABILITY_8H=WAIVED_BY_USER
ELECTRON_GUI=PASS_WITH_EVIDENCE_CAVEATS
FULL_LOCAL_GATE=PARTIAL
LOCAL_ACCEPTANCE=PARTIAL
FIELD_ACCEPTANCE=NOT_AVAILABLE
RELEASE_READINESS=NOT_READY
OVERALL_STATUS=PARTIAL
```

`LONG_STABILITY_8H=WAIVED_BY_USER` 仅表示用户取消剩余 1.5 小时等待，不表示达到 8 小时。机器可读结果使用合法枚举 `PARTIAL`，备注为 `USER_WAIVED_REMAINING_DURATION`。

## 关键证据

- 长稳实际运行 `24,000.379 s`，从 `2026-11-10T08:57:10.438+08:00` 到 `2026-11-10T15:37:10.817+08:00`；停止机制正常完成，队列排空，SQLite `integrity_check=ok`。
- 长稳 Syslog `30,424 received / 30,424 raw / 30,424 parsed / 0 dropped`；位置有效样本 P50/P95/P99 为 `622/1,134/3,877 ms`，最大 `6,639 ms`，超过 10 秒和 30 秒均为 0，最终 AP-B 为 `100/100 MR`。
- 正常/突发独立位置场景分别为 `506/973/1,010 ms` 与 `2,120/5,899/6,286 ms`（P50/P95/P99），未与长稳故障窗口混合。
- 实际 Electron GUI 运行 `r2_3_2-electron-gui-switch-023-20261110` 显示同一目标 MR 的 AP-A 前截图与 AP-B 后截图；API/SQLite 同时确认 `current=R232-AP-B-001`、`previous=R232-AP-A-001`、`position_status=VALID`、`position_source=SYSLOG`。Ground 正常停止后 Heartbeat 保留 200 targets/17 processes，Renderer reload 通过。
- AC 旧快照保护、SQLite lock/recovery、Parser/Raw Writer/Heartbeat 故障隔离由专项 `119 passed` 证据覆盖；GUI 运行本身未配置真实 AC/SSH，不把 no-data 页面写成现场 AC 成功。

## 限制与发布结论

所有数据来自合成 inventory、脱敏 Fixture、loopback UDP、隔离 SQLite 和 synthetic Heartbeat。事件时间明确标记为 `DEVICE_TIMESTAMP`，不构成真实设备时钟证明；长稳未单独持久化 AC 查询耗时，UI Available Time 也未作为逐事件延迟样本单独埋点。Full Gate 仍受既有 Mesh/DataRoot/架构/文档治理失败以及安装器 upstream push 对齐保护影响，故本轮不是发布 PASS，也不是现场验收 PASS。
