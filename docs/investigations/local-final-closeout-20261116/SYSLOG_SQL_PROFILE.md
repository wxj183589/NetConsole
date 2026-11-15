# Syslog SQL 与可靠性剖析

状态：PASS（定向本地剖析）

本次使用真实 UDP loopback、合成 MR 负载、重复报文和并发发送器验证 Syslog 采集边界。负载为 20、50、100 个 MR；每个 MR 生成管理地址和备份地址，并发送重复地址对。剖析数据和 metrics 位于项目 Workspace 的 `test-data/NetConsole/` 下，未使用生产数据。

| MR / 消息数 | before EPS | after EPS | before 提交 p95(ms) | after 提交 p95(ms) | 丢弃 | 锁冲突 | SQL trace |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 20 / 40 | 50.158 | 49.505 | 10.728 | 11.426 | 0 / 0 | 0 / 0 | 1456 / 1456 |
| 50 / 100 | 123.451 | 130.317 | 17.664 | 15.824 | 0 / 0 | 0 / 0 | 2812 / 2764 |
| 100 / 200 | 241.303 | 244.289 | 27.788 | 30.312 | 0 / 0 | 0 / 0 | 5050 / 5032 |

结论：重复报文未造成重复身份写入、丢弃或锁冲突；本次没有对 Syslog 业务实现做未经证实的 SQL 优化，因此只报告可靠性和剖析结果，不宣称稳定的吞吐提升。Ground read profile 同样显示各接口 SQL 次数保持不变，属于机器方差范围，详见最终门禁报告。

测试脚本：`scripts/dev/syslog_loopback_profile_20261116.py`

安全边界：`PRODUCTION_DATA_MODIFIED=0`，`DATABASES_REMOVED=0/0`，`MAINTENANCE_AUTHORIZED=NO`。
