# R2.3.3 AC Query Duration

## 实现

AC Mesh Link 查询和 resident polling health 现在记录：

- `last_query_started_at` / `last_query_completed_at`
- `last_query_duration_ms`
- `last_query_succeeded`
- `query_timeout_count`
- `last_query_success_at` / `last_query_failure_at`
- `snapshot_processing_duration_ms`
- `snapshot_change_count`

timeout 与查询失败独立计数，不能被普通 heartbeat 或 AC snapshot 成功覆盖。

## 证据

```text
D:\study\NetConsole-Workspace\NetConsole\.venv\Scripts\python.exe -m pytest tests/test_ac_mesh_link_resident_polling.py -q
退出码：0（该文件同时包含查询耗时、超时和恢复断言；本轮定向集合总计 43 passed）
```

测试覆盖成功查询、超时、失败退避和 health 暴露；没有真实 AC/SSH 连接，因此没有现场查询耗时分布，也不把 no-data GUI 页面写成 AC 成功。

结论：`AC_QUERY_DURATION=PASS_WITH_EVIDENCE_CAVEATS`。字段和失败边界已落地，现场 AC 的耗时 P50/P95/P99 仍待真实连接或等价受控测试。
