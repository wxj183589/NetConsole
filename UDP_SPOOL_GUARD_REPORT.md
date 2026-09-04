# UDP Syslog Spool Guard 第三阶段报告

## 变更范围

基于 `2a90b5f6`，仅修改 UDP Syslog runtime 健康诊断、Ground active 归档边界、健康 DTO/Renderer 类型和相关测试。Raw-first 接收、Parser 流程、Ground/Online MR 业务流程及数据库结构均保持不变。

## Spool 磁盘保护

`SyslogUdpReceiver` 对现有 `realtime/syslog/_spool` 递归统计：

- `spool_bytes`：spool 普通文件总字节数
- `spool_files`：spool 普通文件数
- `disk_free_bytes`：spool 所在卷的可用字节数
- `disk_usage_percent`：spool 所在卷的使用率

默认阈值可在 `start()` 通过参数覆盖，且要求按序排列：warning `70%`、critical `85%`、emergency `95%`。状态变化时写入健康事件：

- `SYSLOG_SPOOL_DISK_WARNING`（warning）
- `SYSLOG_SPOOL_DISK_CRITICAL`（error）
- `SYSLOG_SPOOL_DISK_EMERGENCY`（error）
- `SYSLOG_SPOOL_DISK_RECOVERED`（info）

告警写库失败只记录 runtime error，不阻塞 UDP 接收，也不因阈值主动丢弃原始报文。磁盘真正写满时仍按既有写失败计数和错误处理，现场需要持续监控磁盘容量。

## 归档隔离

普通 Ground 归档的 manifest、ZIP 目录扫描均跳过 `_spool` 及其子路径。active 清理前检查 `realtime/syslog/_spool` 是否存在非空待处理文件；存在时保留 active，设置 `active_cleanup_pending`，不移动、不删除 spool 数据。空 spool 文件不阻止已完成 active 清理；符号链接或扫描异常按待处理处理，优先保留数据。

## 测试结果

- UDP Syslog/spool/归档定向测试：`14 passed`
- 新增 spool 增长、磁盘阈值和归档隔离测试：包含在上述定向测试中
- Ground 无人值守全量 `test_ground_unattended_*`：`223 passed, 1 skipped`
- Online MR collection/Job：`122 passed, 1 failed`。失败为既有 `online_mr_worker_cancel_stdout_is_jsonl_and_has_one_terminal_event` 返回码环境契约（实际 `1`、期望 `2`），未涉及本次修改文件
- Renderer Ground/Syslog/Online MR 定向：`103 passed`
- Renderer 全量：`1279 passed, 2 failed`。失败为既有 MESH 动态图性能阈值（overlay 约 `60ms` 超 `50ms`、颜色分配约 `165ms` 超 `100ms`），并伴随测试环境未启动 backend 的 `localhost:3000` 连接拒绝
- Renderer 构建：`pnpm build` 成功
- Ruff：通过
- Python `py_compile`：通过
- `git diff --check`：通过

所有测试使用临时测试目录；未访问或修改 `D:\NetConsoleData`、`D:\NetConsoleData-production`、`D:\NetConsoleData-dev`。

## 风险与现场验证

磁盘容量持续不足时，spool 最终仍可能无法追加并产生 dropped/error；本阶段通过分级健康告警避免静默增长，但不替代磁盘清理和现场容量监控。现场应确认 7 台 MR 并发时告警可见、停止后文件句柄关闭、待处理 spool 在归档期间保持不变，并验证恢复到正常容量后产生 recovered 事件。
