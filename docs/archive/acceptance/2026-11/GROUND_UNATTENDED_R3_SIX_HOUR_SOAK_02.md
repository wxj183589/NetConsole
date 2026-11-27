# Ground Unattended R3 Six-Hour Component Soak 02

Status: `PASS` for the isolated synthetic Ground component scope. Field acceptance remains `NOT VERIFIED`.

## Execution

- Product baseline: `70f5f8b1` on `codex-A/organization-task-network-services-phase6`.
- Requested / observed wall time: 21,600 / 21,621.528 seconds.
- Run root: `D:\study\NetConsole-Workspace\test-data\NetConsole\r2_3_2-long-20261127-r3-6h-02`.
- Scope: 100 synthetic MR, loopback UDP Syslog through the production Ground receiver, Raw writer, parser and SQLite projection, in-process synthetic Heartbeat, and synthetic AC delta/reconciliation.
- The run did not use TCP, Quick Ping, Electron, real fping, a real AC, a physical device or a configured site. It is not a mixed-history-query soak.

## Results

| Metric | Result |
| --- | ---: |
| Harness status | `PASS` |
| Syslog sent / received / Raw / parsed | 27,415 / 27,415 / 27,415 / 27,415 |
| Application drops / Raw write failures / projection failures | 0 / 0 / 0 |
| Final queue depth / parser spool / compression pending | 0 / 0 / 0 |
| Max Syslog queue depth | 86 |
| Position latency P50/P95/P99 | 615 / 1,110 / 2,456 ms |
| Receive-to-Raw P95 | 5 ms |
| Raw-to-Parse P95 | 81 ms |
| Parse-to-Position P95 | 1,033 ms |
| RSS first / sampled peak / last sample | 73.6 / 107.0 / 86.4 MiB |
| RSS at final summary | 150.3 MiB |
| CPU time | 2,942.891 seconds |
| SQLite final size | 264,015,872 bytes |
| Heartbeat samples / workers stopped | 431,036 / 9 of 9 |
| AC polls / injected timeout windows / partial / duplicate snapshots | 338 / 21 / 15 / 31 |
| Compression completed / queue-full / recovery / failure | 700 / 0 / 0 / 0 |
| UDP port released / residual receiver threads | Yes / 0 |
| Position final AP-B state | 100 / 100 MRs |

`summary.json` reports `data_complete=true`, receiver and Heartbeat stop success, empty receiver and compression queues, flushed Raw projection and metadata, no errors, and UDP port release. The final interval after the last periodic metrics sample is represented by this summary.

## Boundary

The run confirms a second independent six-hour UDP component stability run with synthetic Heartbeat and AC workloads. Together with [Run 01](./GROUND_UNATTENDED_R3_SIX_HOUR_SOAK_01.md), it does not verify TCP, concurrent history queries, Quick Ping, Electron rendering, network disconnect/reconnect, abnormal process termination, device behavior, or field acceptance.

No Production data, real development business data, source archive or device configuration was modified. The run root and its evidence remain in the isolated Workspace test-data container.
