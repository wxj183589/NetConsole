# Engineering hardening blocking gate

最终门禁证据：

- Workflow run：`42908531183`
- Final attempt：`3`
- Head SHA：`6bde7526ebab19c9cc91d75e4be722e72e615366`
- Blocking job：`130203821581`
- 结论：`success`

最终 7 个子门禁全部成功：

| Gate | Result |
| --- | --- |
| Architecture contract | PASS |
| Python regression without baseline debt | PASS |
| Renderer tests, typecheck, and build | PASS |
| Electron tests, typecheck, and main build | PASS |
| Main contract smoke | PASS |
| Docs, path, and diff guards | PASS |
| Baseline debt audit and new failure detection | PASS |

attempt 2 的 Python 作业出现一次间歇性 `test_heartbeat_without_ac_or_credentials_persists_both_ip_stats` 失败（5665 passed、1 failed），未改变代码；本地重复验证后重跑 attempt 3 全绿。该过程没有将失败结果伪装为成功。
