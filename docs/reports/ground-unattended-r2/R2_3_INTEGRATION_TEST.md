# R2.3 集成测试报告

日期：2026-11-10。结论：定向自动化 **PASS**；完整 R2.3 集成 Gate **PARTIAL**。

## 已执行

| 命令/范围 | 结果 |
| --- | --- |
| `pytest -q tests/test_ground_unattended_position_engine.py` | 6 passed |
| `pytest -q tests/test_ground_unattended_syslog_position_latency.py` | 2 passed |
| 位置测试 + latency 测试 + `test_udp_syslog_reliable_spool.py::test_live_and_replayed_timeline_preserve_device_and_receive_times` | 10 passed |
| `pytest -q tests/test_udp_syslog_reliable_spool.py tests/test_ground_unattended_syslog_v2_stress.py tests/test_ground_unattended_radio_correlation.py` | 41 passed |
| 相关 Python `py_compile`、Ruff check | PASS |
| `pnpm exec vue-tsc --noEmit`（`apps/desktop_renderer`） | PASS |

## 覆盖到的事实

临时 SQLite 中验证了位置表初始化、批量提交、当前/上一个 AP、重复/乱序计数、阶段时间和健康分位数字段；纯逻辑测试验证位置顺序和状态恢复；既有可靠 spool/WMESH 回归保持通过。

## 未执行

没有运行完整全域测试、真实脱敏设备 UDP、持续正常负载、突发负载、慢 Parser/Raw Writer、SQLite 锁、Backend 强杀重启、8/24 小时长稳或 Electron GUI 截图。因此不能把本报告的 PASS 扩展为发布/现场验收通过。
