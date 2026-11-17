# SQL 共享读取定向验证（2026-11-17）

最终范围状态：`PARTIAL_SQL_QUERY_OPTIMIZATION`。本分支定向测试通过，不代表全局优化、main 集成或发布验收。

## 证据与复现边界

- 基线 `dd026f2fffa280bb9fa43d3c6da34f831bad9a16`；分支 `codex-A/sql-read-model-sharing-20261117`。
- Python 为仓库 `.venv/Scripts/python.exe`，所有数据来自 TEST 模式合成 fixture，无真实设备命令、lifespan 探测或真实数据 DB 读取。
- 机器证据根：`D:\study\NetConsole-Workspace\reports\diagnostic\sql-query-optimization-20261117`。
- `baseline.json`、`optimized.json` 含各规模逐样本 SQL count、SELECT/WITH、PRAGMA、write/transaction 类别、连接、SQL ms、wall ms、fetched rows、response bytes、最慢 SQL 模板；参数不写日志。
- `comparison.json` 为每个指标 p50/p95/p99 的 baseline/optimized/delta/change_percent，含输入 SHA-256；`query-plan.json` 为既有代表性查询和实际共享读取计划。
- `targeted-tests.xml` 与 `boundary-tests.xml` 为本轮 pytest JUnit 结果。JSON/JUnit 保留在 Workspace，不提交运行数据到产品 Git。

## 定向测试

主回归 **330 passed，193.62 秒**，仅 1 条既有 Starlette/httpx 依赖弃用警告：

```powershell
$env:NETCONSOLE_PRESERVE_TEST_BASETEMP='1'
.\.venv\Scripts\python.exe -m pytest -q `
  tests/test_ground_inventory_sharing.py tests/test_device_repository.py `
  tests/test_ground_unattended_heartbeat_inventory.py `
  tests/test_ground_unattended_heartbeat_resident.py `
  tests/test_ground_unattended_heartbeat_state.py `
  tests/test_ground_unattended_quick_ping.py `
  tests/test_ground_unattended_quick_ping_repository.py `
  tests/test_ground_unattended_quick_ping_ip_exclusivity.py `
  tests/test_ground_unattended_foundation.py tests/test_ground_unattended_scheduler.py `
  tests/test_ground_unattended_api.py tests/test_ground_unattended_eligibility.py `
  tests/test_ground_unattended_syslog_field_validation.py `
  tests/test_ground_unattended_syslog_position_latency.py `
  tests/test_ground_unattended_raw_v2_consumers.py `
  tests/test_ground_unattended_r2_3_3_burst.py `
  tests/test_job_center_web_api.py tests/test_job_center.py `
  --basetemp D:\study\NetConsole-Workspace\test-data\NetConsole\sql-sharing-final-20261117-a `
  --junitxml D:\study\NetConsole-Workspace\reports\diagnostic\sql-query-optimization-20261117\targeted-tests.xml
```

追加源版本变化/不稳定两项后，重新运行整个 `tests/test_ground_inventory_sharing.py`：**21 passed，10.15 秒**，独立新 basetemp `sql-sharing-final-boundaries-20261117-a`，结果 `boundary-tests.xml`。它与主回归有重叠，不相加宣称 351 个不同测试；本轮两组共覆盖 332 个不同测试。

| 契约 | 实际验证 |
| --- | --- |
| UUID 批量读取 | 空集零连接；重复/缺失；902 唯一参数跨两批仍 1 connection / 6 SELECT；Device DTO 与逐条结果一致 |
| 凭据 | available、needs_reentry、key_file_missing、legacy 无状态表；只暴露存在性，无秘密快照 |
| collection | 递归不可变；解包/DTO 独立；source revision/TTL；注入 reader 不跨调用缓存 |
| 一致性 | 读取中 revision 变化重试，三次仍变化不发布；preview/sync 只 collect 一次；stale preview 和跨 Site 拒绝 |
| Ground snapshot | 冷读 1 connection / 3 SELECT，暖读 0/0；成功提交失效、rollback 不失效；跨实例 TTL 可见 |
| 并发 | 线程独立 connection；延迟 load 与 commit 不会发布覆盖失效；Syslog 迟到旧 snapshot 被拒绝 |
| Heartbeat/Syslog | 同 snapshot 重复十次无 SQL/重配；主备 IP；冲突；1000 次 identity resolve 无 SQL |
| Deep | 即使静态 collection 被显式保留，启动前仍读取当前参与资格及凭据 |
| 业务回归 | Heartbeat resident/state/clear，Quick Ping 地址校验及 IP 独占，Ground scheduler/API，Syslog raw/position/burst，Job API |

## 性能复现

首次测量前保持独立新 fixture 路径；脚本拒绝复用已存在的 fixture-root，不删除已有根。示例中的路径若已存在，请更换任务内唯一后缀，勿先清理：

```powershell
.\.venv\Scripts\python.exe -m scripts.dev.sql_read_sharing_profile_20261117 `
  --fixture-root D:\study\NetConsole-Workspace\test-data\NetConsole\sql-sharing-optimized-20261117-a `
  --output D:\study\NetConsole-Workspace\reports\diagnostic\sql-query-optimization-20261117\optimized.json `
  --iterations 30 --trains 25 50 100 --cold-reads
```

复用既有 `begin_request_profile/end_request_profile`、ProfilingConnection/Cursor、Ground/Job fixture、percentile 和 EXPLAIN，不建立生产 SQL 日志系统。`executemany/executescript` 为一个 profiler call，类别不会展开每条写入；不能把类别之和当所有 SQLite 内部语句数。计数边界在报告中保留。

### 主规模时间分位（100 MR，ms）

每格为 p50 / p95 / p99。连续场景按顺序执行，包含偶发 TTL 到期；冷读在每次计时前令应用静态缓存过期，非物理磁盘冷启动。

| 场景 | 基线 | 优化连续读取 | 优化应用缓存冷读 |
| --- | --- | --- | --- |
| collect | 309.82 / 343.03 / 368.97 | 4.37 / 4.59 / 5.15 | 33.33 / 44.51 / 51.32 |
| preview/synchronize | 626.74 / 652.97 / 689.56 | 25.98 / 43.29 / 54.95 | 58.21 / 110.97 / 212.47 |
| Heartbeat targets + Syslog | 8.76 / 13.92 / 33.35 | 0.01 / 0.02 / 9.64 | 6.04 / 7.53 / 8.71 |
| Heartbeat API empty | 25.23 / 28.30 / 29.91 | 19.15 / 24.51 / 34.90 | 24.92 / 30.64 / 34.44 |
| Quick Ping validate | 66.78 / 73.17 / 73.37 | 5.19 / 6.52 / 35.22 | 36.58 / 43.17 / 43.34 |
| Quick Ping history | 1.72 / 2.41 / 2.76 | 1.87 / 2.64 / 2.90 | 未测 |

### 主规模行数和 SQL 累计时间

各数值为 p50；bytes 是相同 harness 的 JSON 投影大小，collect 新旧结构不同不可按等价响应比较。

| 场景 | SELECT/连接：基线 → 冷读 | fetched rows：基线 → 冷读 | SQL ms：基线 → 冷读 | bytes：基线 → 冷读 |
| --- | --- | --- | --- | --- |
| collect | 304/101 → 9/4 | 407 → 310 | 195.27 → 7.40 | 45539 → 143714 |
| preview/synchronize | 613/205 → 15/7 | 1114 → 611 | 386.92 → 13.98 | 382 → 382 |
| Heartbeat/Syslog | 5/3 → 3/1 | 300 → 150 | 3.79 → 1.56 | 22 → 22 |
| Heartbeat API empty | 14/9 → 12/7 | 402 → 252 | 11.78 → 10.31 | 144850 → 144850 |
| Quick Ping validate | 32/11 → 9/4 | 549 → 310 | 19.41 → 8.09 | 17 → 17 |

最慢 SQL 模板（100 MR 的冷读样本）：collect 是 schema_metadata 版本查询，单次最大 2.83 ms；Heartbeat API 是 inventory/policy join 排序，最大 6.31 ms；Quick Ping 是版本查询，最大 3.09 ms。完整前五项及各规模见 JSON；不记录凭据或 SQL 参数。

Job Center list/summary/detail/logs 优化前后均为 **5/5/7/4 SELECT、各 1 connection**。p50 从 13.19/11.15/1.74/1.28 ms 到 11.26/11.37/1.92/1.37 ms；业务无修改，不将主机噪声解释为优化成果。

## 查询计划

`query-plan.json` 中真实共享读结果：

- devices：`SEARCH ... USING INDEX sqlite_autoindex_devices_1 (device_uuid=?)`。
- credential states：命中 `sqlite_autoindex_device_credential_states_1`。
- train inventory/policies/state：Site/复合主键 SEARCH，无全库库存扫描。
- train 和 endpoint 的 ORDER BY 仍使用临时 B-tree；未增加索引，不声称完全消除排序。
- 既有 profiler raw_files 计划保留 `USE TEMP B-TREE FOR LAST TERM OF ORDER BY`。

## 静态检查与未验证范围

- 修改范围 Ruff、py_compile、`git diff --check`：PASS。
- `python -m scripts.check_workspace_layout`：PASS，未跟随 Reparse Point、无破坏动作。
- `python -m scripts.architecture.check_direct_sql_access`：PASS，0 findings、0 waived。
- Change Impact Registry：最低 L2；本轮共享层按人工 L3 审计和消费者定向回归交付。
- Renderer/Electron/typecheck：NOT RUN（无相关代码修改）；全量 pytest、完整 Release Gate：按任务要求 NOT RUN。
- 非空 AC/Mesh/ARP/历史专项性能、真实 GUI/设备/数据、长时、安装包、发布与合并后结果：NOT VERIFIED。

部分尾延迟退步及测量并行负载限制见[优化报告](SQL_QUERY_OPTIMIZATION_REPORT_20261117.md)。没有因为 SQL 数减少而宣称所有耗时通过。

## 安全声明

`PRODUCTION_DATA_MODIFIED=0`；`DATABASES_REMOVED=0` 指业务/历史数据库；`MAINTENANCE_AUTHORIZED=NO`。早期默认 pytest 临时 fixture 的框架自动清理单独披露，最终测试采用 preserve 标志和新 basetemp；不声称所有临时数据从未被框架清理。无真实数据库、用户工作簿、设备命令、WAL/SHM 删除、版本或安装器修改。
