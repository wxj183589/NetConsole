# Ground Unattended V2 压力与长测（2026-11-07）

## 1. 结论与实测身份

**短时组件压力 PASS；24H_TEST=NOT_RUN；COMPONENT_24H_TEST=NOT_RUN。** 实际只运行约 245 秒，不能证明全系统或组件连续 24 小时稳定性。

版本化独立入口为 `scripts/dev/ground_v2_soak.py`，使用生产 Heartbeat/Quick/Syslog 组件、synthetic Ping runner、回环 UDP 和独占 Fixture SQLite/raw。AC 仅生成多 controller 延迟/离线指标，deep 仅 Mock 失败计数；没有运行真实 AC Poller/deep worker、Backend、Electron 或 fping 子进程。

证据根：`D:\study\NetConsole-Workspace\test-data\NetConsole\ground-v2-soak-verified-20261107`，内有 owner.json、metrics.ndjson、summary.json、隔离数据库及 raw/gzip。命令日志为仓库 `.local/ground-v2-final-audit/soak-verified.log`。报告引用最终 verified run，不混用前次试跑。

| 项目 | 实际值 |
| --- | --- |
| 开始 UTC | 2026-11-06T21:06:05.538994+00:00 |
| 结束 UTC | 2026-11-06T21:10:10.824733+00:00 |
| 本地时间 | 2026-11-07 05:06:05–05:10:10，Asia/Shanghai |
| 请求 / 实际 / workload 秒 | 245 / 245.2857228 / 245.0075024 |
| MR / 管理 IP | 200 / 300，CT/CW 和单/双 IP 混合 |
| 心跳 tick / 样本 | 245 / 73,500 |
| UDP 发送/接收/写入/解析 | 12,700 / 12,700 / 12,700 / 12,700 |
| 应用 dropped / raw write failed | 0 / 0 |
| Quick | 3 并行；45 秒手停 1 个；结束全部 CANCELLED |
| Quick sent | 1366 / 7222 / 7220 |
| 组件重建 / 真实 Backend 重启 | 1 / 0 |
| 监测点 | 25，每 10 秒 |
| 数据完整性 | data_complete=true；SQLite integrity=ok；errors=[] |
| 停止 | 队列清空、线程退出、UDP 端口释放，success=true |

## 2. 注入覆盖与限制

心跳合成数据覆盖瞬时/5 秒/10 秒丢包、单端/双端失联、交集确认和一端恢复、主备地址切换、采样中断和组件重建。产生 mr_loss_pending=5、mr_offline=3、mr_recovered=3、train_offline=1、train_recovered=1；heartbeat_engine_unavailable=200、heartbeat_sampling_interrupted=200 是计划注入结果，不是 400 次未解决运行异常。

持续 UDP、未知模块、突发与 parser 积压以及 Quick 无限/手停均执行。实际 10MiB 分段/gzip、20k burst、ENOSPC、SQLite 暂锁、压缩失败等还有独立 pytest 证据，不应把每一项都声称发生于该 245 秒脚本。脚本内磁盘指标来自实际剩余空间变化，没有耗尽真实磁盘。

AC 0/30/120 秒延迟及 offline、deep failure 的字段仅为模拟指标，不能用这些字段证明真实 Poller 或 SSH 隔离。fping 故障只通过合成 engine-unavailable 信号/定向组件测试验证；未杀真实 fping。Backend restart=0，不可用 component_restarts=1 冒充。

## 3. 资源趋势

| 指标 | 首个监测点 | 最后监测点 / 峰值 | 解释 |
| --- | --- | --- | --- |
| Harness RSS | 67,256,320 B（64.1 MiB） | 71,143,424 B（67.8 MiB），峰值同末值 | 增约 3.7 MiB；短时不足以判断长期泄漏 |
| 线程 | 13 | 10，峰值 13 | 最终停止后 alive_thread_names=[] |
| Harness CPU 累计 | 0.140625 s | 39.0 s | 不是 Backend CPU，不是瞬时 CPU 百分比 |
| Backend / Electron RSS | null / null | null / null | 未运行这些进程 |
| fping 进程数 | 0 | 0 | synthetic runner，不能证明真实 fping 无泄漏 |
| 目标 / IP | 200 / 300 | 200 / 300 | 最后定时点样本 72,300，最终汇总 73,500 |
| SQLite | 643,072 B | 647,168 B | integrity=ok |
| raw / gzip 文件 | 7 / 0 | 6 / 1 | 快照计数变化；最终索引/完整性另验 |
| Raw queue / 容量 | 0 / 100 | 1 / 100 | 停止时归零 |
| Parser queue / 容量 | 36 / 100 | 43 / 100 | 受控积压，停止时归零 |
| Spool bytes / files | 0 / 2 | 424,018 / 2 | 最终 drain；不是无界积压证明 |
| 磁盘剩余 | 491,716,583,424 B | 491,138,490,368 B | 同盘其它 Gate/构建也写入，不能全部归因脚本 |
| 任务 | RUNNING=3 | CANCELLED=1、RUNNING=2 | 最终收口全部 CANCELLED |
| 错误数 | 0 | 0 | 不含计划注入的状态事件 |

最后监测点是约 240 秒；结束汇总在约 245 秒。持续时长和最终完成性以 summary 为准，不能只拿最后定时点计数判断丢包。

## 4. 启动和停止

已经执行（cwd=主仓库）：

```powershell
.\.venv\Scripts\python.exe -m scripts.dev.ground_v2_soak --seconds 245 --metrics-seconds 10 --run-id ground-v2-soak-verified-20261107
```

独立 24 小时组件命令（**尚未执行**，需确保会话/主机保持运行，run-id 不可复用）：

```powershell
.\.venv\Scripts\python.exe -m scripts.dev.ground_v2_soak --seconds 86400 --metrics-seconds 10 --run-id ground-v2-soak-24h-20261107
```

提前受管停止：

```powershell
New-Item -ItemType File -Path 'D:\study\NetConsole-Workspace\test-data\NetConsole\ground-v2-soak-24h-20261107\STOP'
```

脚本拒绝已有根，设置 RuntimeMode.TEST，只写归属 run 根，不删除外部数据。停止后应检查 summary 的实际秒数、COMPONENT_24H_TEST、data_complete、errors、integrity 和停止结果；提前停止不能算 24 小时。即使脚本跑满，**全系统 24H_TEST 仍 NOT_RUN**，因为其 scope 没有 Backend/Electron/fping/真实 AC/deep 任务。

查看指标可使用 `Get-Content -LiteralPath <run-root>\metrics.ndjson -Tail 1`。汇总较大，建议用 Python 提取 started_at、ended_at、actual_seconds、result、data_complete、errors、stop_result、resource_first/last，而非整体输出。保留 owner 与证据至审阅后，再按归属精确退役自有测试数据，不清理历史或业务根。

## 5. 全系统长测缺口

需在隔离 Windows 环境运行实际 Backend/Electron/fping 及 200–400 个模拟目标，连接模拟 AC/SSH/deep 链路；逐 PID 采集 CPU/RSS/线程/句柄、fping 数、端口及队列/文件/SQLite/磁盘指标。注入真实进程退出/Backend 恢复，记录开始/结束、实际 86400 秒、所有中断、重放和完整性；比较资源趋势并核查停机空窗不生假离线。当前脚本提供组件压力入口，不能替代这套全系统长测。

恢复/存储定向测试和命令见[主报告](./ground-unattended-v2-final-stability-audit-2026-11-07.md)，原生步骤见 [Windows 报告](./ground-unattended-v2-windows-validation-2026-11-07.md)。
