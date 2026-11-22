# R5.0.4 Ping 数据映射与回归测试报告

## 状态映射

`pingChartStatus.ts` 统一处理显式 `SUCCESS`、`TIMEOUT`、`PACKET_LOSS`、`UNKNOWN`，并兼容当前业务采样的 `ok/rtt_ms` 字段：

- `ok=true` 且有效 RTT、无丢包比例 -> `SUCCESS`、RTT 保留、丢包 `0%`；
- 超时或失败 -> 红色失败状态，RTT 为 `null`，不会生成 `0 ms`；
- 有效部分丢包比例 -> 红色失败状态，保留有效 RTT 和原始比例；
- 缺失/非法状态 -> 灰色 `UNKNOWN`，丢包率保持无数据。

## 测试结果

```text
RENDERER_GROUND_UNATTENDED=PASS (7 files, 26 tests)
PING_STATUS_MAPPING=PASS (SUCCESS/TIMEOUT/PACKET_LOSS/UNKNOWN)
ZERO_AND_NONZERO_LOSS_MAPPING=PASS
NULL_RTT_PROTECTION=PASS
TOOLTIP_VALUE_CONSISTENCY=PASS
PRIMARY_BACKUP_SERIES_ISOLATION=PASS
FIVE_CHART_TIMELINE_REGRESSION=PASS (existing shared viewport tests)
QUICK_PING_REPLAY=PASS
PYTHON_GROUND_TARGETED=PASS (95 passed, 1 warning)
RENDERER_BUILD=PASS
ELECTRON_TYPECHECK=PASS
DIFF_CHECK=PASS
```

Python command:

```text
.venv\Scripts\python.exe -m pytest -q tests/test_ground_unattended_monitoring.py tests/test_ground_unattended_quick_ping.py tests/test_ground_unattended_heartbeat_state.py tests/test_ground_unattended_heartbeat_resident.py tests/test_ground_unattended_fleet_ping.py
```

No full suite, package build, version bump, release, or production-data operation was performed.
