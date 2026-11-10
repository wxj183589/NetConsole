# CI results

| Run / attempt | Result | Notes |
| --- | --- | --- |
| `42873402362` | failed | Python 10 failures，修复后继续 |
| `42881083451` | failed | 单个 burst test failure |
| `42886345342` | failed | 单个 short UDP burst failure |
| `42894322495` | failed | Syslog stress timeout |
| `42900954803` | success | pending deque 优化后的 8 jobs 全绿 |
| `42907168415` | failed | 旧 review 修复提交的 Renderer 4 failures |
| `42908531183` attempt 1 | cancelled | 长时作业在完成前主动取消，非最终依据 |
| `42908531183` attempt 2 | failed | 5665 passed、1 个间歇性 heartbeat test failure |
| `42908531183` attempt 3 | success | 7 子门禁 + blocking gate 全部 PASS |

最终合并只依据 `42908531183` attempt 3；没有 bypass、假 CI 或人工修改 check 结果。
