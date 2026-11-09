# R2.3.1 Heartbeat / fping 测试

本地模拟使用 100 个合成 MR 的 primary + backup 地址，共 200 个目标，模拟 fping v5 JSON 样本，不触碰 `D:\study\fping` 上游仓库，也不向现场地址发包。

## 结果

- 目标数：200；分片大小 12；运行分片：17。
- 模拟样本在停止时累计 2104 条；Heartbeat raw 文件 100 个。
- 停止结果：`success=true`、`fping_processes_exited=true`、无存活 worker、metadata/compression 均完成。
- 更新/移除目标、失败、超时、进程错误、退避和重启恢复由现有 Heartbeat/Fleet 测试覆盖。
- Heartbeat 不推断车辆位置；位置字段只作为已有 Syslog/AC 上下文的可选 enrich，不写入 PositionEngine。

专项命令覆盖 `test_ground_unattended_heartbeat_inventory.py`、`heartbeat_resident.py`、`heartbeat_state.py`、`fleet_ping.py`、`fleet_ping_retention.py`，与 AC/Health/Monitoring 合计 142 项通过。
