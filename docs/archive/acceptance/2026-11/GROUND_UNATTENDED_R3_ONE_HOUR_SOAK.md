# Ground Unattended R3 One-Hour Component Soak

Status: `PASS` for the isolated synthetic Ground component scope. Field acceptance remains `NOT VERIFIED`.

## Execution

- Baseline: product branch `codex-A/organization-task-network-services-phase6`, commit `db9fbbab`.
- Command: `.venv/Scripts/python.exe -B -m scripts.dev.ground_unattended_r2_3_2_long_stability --duration-seconds 3600 --heartbeat-period-ms 5000 --ac-interval-seconds 60 --metrics-interval-seconds 60 --run-id r2_3_2-long-20261127-r3-1h-01`.
- Root: `D:\study\NetConsole-Workspace\test-data\NetConsole\r2_3_2-long-20261127-r3-1h-01`.
- Scope: 100 synthetic MR, Ground Syslog UDP loopback, the production receiver/raw writer/parser/SQLite projection, in-process synthetic Heartbeat, and synthetic AC delta/reconciliation. The run injected duplicate and out-of-order Syslog, unknown AP, malformed input, periodic AC timeout/partial/duplicate windows. It did not launch Electron, TCP, Quick Ping, real fping, real AC, or a device.

## Results

| Metric | Result |
| --- | ---: |
| Requested / observed wall time | 3,600 / 3,606.175 seconds |
| Overall harness status | `PASS` |
| Sent / received / raw written | 4,634 / 4,634 / 4,634 |
| Dropped / raw write failures | 0 / 0 |
| Final queue depth / oldest wait | 0 / 0 seconds |
| Maximum queue depth | 86 |
| Position latency P50/P95/P99 | 512 / 991 / 1,064 ms |
| Receive-to-Raw P95 | 4 ms |
| Raw-to-Parse P95 | 28 ms |
| Parse-to-Position P95 | 975 ms |
| RSS first / peak / last | 74.0 / 93.2 / 93.2 MiB |
| Threads minimum / maximum | 16 / 17 |
| SQLite size at final sample | 33.2 MiB |
| CPU time | 287.656 seconds |
| AC polls / injected timeouts | 57 / 3 |
| Heartbeat samples / stopped workers | 71,808 / 9 |
| Raw projection failures | 0 |
| Compression failures | 0 |
| UDP port released | Yes |

`summary.json` records `data_complete=true`, an empty error list, successful receiver and Heartbeat stop, empty alive-thread/worker lists, completed compression, and `udp_port_released=true`. The raw archive and the summary remain in the isolated test root for review. No production data, real development data, source archive, or device configuration was changed.

This result verifies a one-hour component soak only. The run did not perform concurrent history SQL/timeline queries, TCP input, actual network disconnect/reconnect, Electron rendering, Quick Ping, or six-hour stability. Those acceptance items remain `NOT RUN` or `NOT VERIFIED`.
