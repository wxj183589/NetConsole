# UDP Syslog Reliable Spool 第二阶段验证报告

## 基线与边界

- 基线：`2f6114a21e8b1989e42f430be6a2dcc442289795`
- Branch：`codex-B/fix/udp-syslog-reliable-spool`
- 样本：仓库现有 `tests/fixtures/ground_unattended/h3c_mr_syslog_3cd.txt`，包含 H3C IFNET、WMESH LINKUP/LINKDOWN 和 MESH_ACTIVELINK_SWITCH 格式。
- 数据：仅使用 pytest 临时目录和 `D:/study/test-data/NetConsole` 下的临时 replay 目录；未访问、复制或修改 `D:\NetConsoleData`、`D:\NetConsoleData-production` 或 `D:\NetConsoleData-dev`。
- 本阶段没有新增生产架构；只修正测试契约并增加验证测试/报告。

## 1. 测试契约修正

旧断言要求 raw NDJSON 同步包含 `resolved_ap_name`、`parsed_details`。该断言已改为：

- Raw：保存接收序号、来源、时间、facility/severity、原始文本和 `raw_bytes_base64`；不要求派生 AP 字段。
- Parser/DB：从 `ground_unattended_wmesh_events` 读取 `peer_name`、Identity entity 和 revision 等派生字段。

没有恢复 raw 写入派生字段，也没有重写历史 raw。

## 2. Syslog 样本 UDP replay

指标顺序为 `received / raw_written / parsed / db_saved / drop`。

| 场景 | 发送规模 | 结果 | spool 峰值 |
| --- | ---: | --- | ---: |
| 1 MR | 100 | `100 / 100 / 100 / 100 / 0` | 0 |
| 7 MR 并发 | 700 | `700 / 700 / 700 / 700 / 0` | 0 |
| 7 MR 高并发 | 7000 | `7000 / 7000 / 7000 / 7000 / 0` | 268 records |

高并发使用 7 个 loopback source IP 的并发发送线程；释放后 parser 完成全部 spool 回放，停止返回成功。

## 3. Raw rollover

`RawStreamWriter` 在接收时间小时变化时关闭旧文件并打开新文件。验证写入 10:59 与 11:00 两条记录后登记 2 个 raw 文件，`open_file_count` 从 1 保持有界，调用 close 后为 0。既有路径保持：

```text
realtime/syslog/<train>/<role>/<date>/<hour>_<generation>.ndjson
```

单小时文件仍受记录时间分片约束，不会跨小时无限增长；本阶段未新增按字节切分规则。

## 4. Spool 磁盘保护检查

已确认的保护行为：

- UDP 和 parser spool 均位于 active run 下的 `realtime/syslog/_spool`，不进入 raw file registry。
- 每条追加后 flush；正常停止且 backlog 清空时截断已消费 spool，避免同一 run 重启重复回放。
- 异常退出时 spool 保留，启动会重计记录并回放。
- spool 写失败会记录错误并递增 `dropped`，不会伪装为成功。

发现的残余风险：当前没有 spool 最大字节数或磁盘余量 watermark；数据库长时间不可用时 spool 仍可能持续增长。归档服务当前递归打包 active 目录，`_spool` 未被显式排除，因此归档期间若 spool 尚有 backlog，可能把临时 envelope 一并纳入 ZIP。该风险本阶段只记录，未扩大为新的架构或归档改造。

## 5. 回归结果

| 套件 | 结果 |
| --- | --- |
| UDP replay/rollover/spool tests | `8 passed` |
| Ground foundation、Syslog field、raw lifecycle、schedule、scheduler、API | `103 passed, 1 warning` |
| Online MR collection、collection Job | `123 passed` |
| Renderer Ground、Syslog API、Online MR views | `99 passed` |
| `py_compile`、Ruff、`git diff --check` | PASS |

## 6. 结论与现场缺口

本地证据显示 commit `2f6114a2` 的 raw-first 接收链路在 1/7 MR 和 7000 条高并发 replay 下应用层 `drop=0`，且 Ground、Online MR 与 Syslog 页面定向回归未见行为回归。仍需主机在最终合并 commit 上复验 Change Impact consumer suite，并由现场验证 7 台真实 MR 的长时间运行、低磁盘/数据库持续故障、归档时 backlog 和 Electron 启停。当前结果不能替代真实设备验收。
