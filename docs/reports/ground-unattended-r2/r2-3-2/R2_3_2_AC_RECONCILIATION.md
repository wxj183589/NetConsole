# R2.3.2 AC delta / reconciliation

## 覆盖

AC 默认轮询周期按 60 秒验证，AC-Mesh-Link 与 Syslog 独立。测试覆盖首次快照、unchanged、add/remove/update、AP/radio/mesh 变化、重复旧快照、timeout、partial、连续失败与恢复。

## 结果

- AC/Heartbeat/recovery 专项：`119 passed`。
- 长稳 AC：376 polls、360 accepted、23 timeouts、23 failure windows、16 partial、34 duplicate；delta 为 ADDED 100、UPDATED 18,460、UNCHANGED 17,440、UNKNOWN 1,584；reconciliation 为 `SYSLOG_NEWER=3,099`、`AC_NEWER=34,047`、`STALE=300`、`UNKNOWN=16`，errors=[]。
- 失败/不完整响应不删除上一次有效 AC 行；Syslog 新于 AC 时保留 `SYSLOG_NEWER`；旧 AC 不无条件覆盖更新 Syslog 位置；AC 失败不会阻塞 Syslog UDP、Raw/Parser 或 Heartbeat resident。
- AC 查询耗时没有单独持久化，报告不伪造查询毫秒值；实际 Electron GUI AC 页面显示未配置/no-data，符合无现场 AC/SSH 的边界。

## 判定

`AC_DELTA=PASS`；`AC_RECONCILIATION=PASS`；`AC_STALE_PROTECTION=PASS_WITH_EVIDENCE_CAVEATS`；`AC_LOCAL_ACCEPTANCE=PASS_WITH_EVIDENCE_CAVEATS`。60 秒现场周期、AC 设备协议和真实凭据仍不可用，`FIELD_ACCEPTANCE=NOT_AVAILABLE`。
