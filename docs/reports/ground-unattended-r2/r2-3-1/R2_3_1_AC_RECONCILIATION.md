# R2.3.1 Syslog / AC 位置对账

对账只记录证据，不允许 AC 快照无条件覆盖 Syslog Position 状态。状态集合为：`CONSISTENT`、`SYSLOG_NEWER`、`AC_NEWER`、`CONFLICT`、`STALE`、`UNKNOWN`。

## 结果

- 本地 Syslog 先产生 A→B，构造延迟到达的 AC-A：100/100 为 `SYSLOG_NEWER`，没有改变 Syslog 的 B 位置。
- 随后构造与当前 Syslog 身份匹配的 AC 快照：100/100 为 `CONSISTENT`。
- 单元测试覆盖 `AC_NEWER`、`STALE`、缺少精确身份的 `UNKNOWN`。
- 持久化表保存 MR、两侧 AP identity、两侧时间、received time、reason、observed time；UI DTO 显示状态和 AC 时间，数据来源与新鲜度由现有字段继续保留。

AC 60 秒轮询不会成为 Syslog 30 秒位置更新的同步前置条件；两者在 Supervisor 中独立运行。
