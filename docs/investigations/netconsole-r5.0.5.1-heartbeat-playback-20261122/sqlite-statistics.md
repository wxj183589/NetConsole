# SQLite 原始 Heartbeat 统计

查询方式：SQLite `mode=ro`，未执行写入、迁移、WAL 清理或数据修复。

## 运行与身份

```text
run_id: ground_20261120_c8f2edb88f15
state: COMPLETED
actual_started_at: 2026-11-20T15:11:00.504+08:00
actual_ended_at: 2026-11-20T16:08:24.710+08:00
heartbeat stream: heartbeat-resident
MR UUID: 09bb8f5e-0749-443f-859a-15947d308854
train/role: train:35 / CT
primary: 10.82.24.235
backup: 192.168.35.249
```

## 逐条样本（精确回放窗口）

| 地址 | 原始采样 | 成功 | 失败/超时 | 最早 | 最晚 |
| --- | ---: | ---: | ---: | --- | --- |
| 10.82.24.235 | 3,144 | 2,289 | 855 | 15:11:01.015+08:00 | 16:08:24.161+08:00 |
| 192.168.35.249 | 3,404 | 2,342 | 1,062 | 15:11:01.208+08:00 | 16:08:24.154+08:00 |
| 合计 | 6,548 | 4,631 | 1,917 | 15:11:01.015+08:00 | 16:08:24.161+08:00 |

原始数据时间、MR UUID、列车和端位均匹配；地址字符串与 Endpoint 注册信息完全一致。摘要表 `ground_unattended_ping_summaries` 也确认两地址属于同一 MR/CT，但其 `run_id` 同样是 `heartbeat-resident`。

## 相关表数量

```text
ground_unattended_runs                         1
ground_unattended_heartbeat_states            30
ground_unattended_ping_summaries            7675
ground_unattended_wmesh_events              1663
ground_unattended_ping_loss_intervals       1900
ground_unattended_raw_files                   92
ground_unattended_quick_ping_runs              0
```

