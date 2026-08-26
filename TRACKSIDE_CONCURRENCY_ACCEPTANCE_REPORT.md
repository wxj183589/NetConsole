# Trackside Concurrency Acceptance Report

日期：2026-08-26

## 测试边界

- 数据根：`D:\NetConsoleData-dev`；局点：宁波地铁12号线。
- 生产根未访问、未写入；并发测试只读 DEV 数据库。
- 8 个并发 worker：轨旁页面 4、轨旁 XLSX 导出 2、FIT-AP 查询 2。
- 导出输出位于 `D:\study\diagnostic\NetConsole\real-acceptance\concurrency`，不写入生产目录。

## 结果

| 类型 | 数量 | 结果 | 观测 |
| --- | ---: | --- | --- |
| Trackside page/snapshot | 4 | PASS | 全部 1,247 行，`partial_data=false`，同一 revision；2,253.51–2,263.80ms |
| Trackside export | 2 | PASS | 全部 1,247 行，XLSX 文件 141,150/141,152 bytes；约 46.51–46.57s，并发期间无锁错误 |
| FIT-AP query | 2 | PASS | 全部 992 resources、946 optical current；378.05–393.30ms |
| SQLite lock/error | 0 | PASS | 没有 `database is locked`、500 或线程异常 |

并发页面返回相同业务 revision：`d42025e133a1f5390ae1bdce6dfad61c6638c101cb48646a9c45de3e188c6691`。两份导出实际文件已检查存在；测试代码中的返回值没有携带 output path，因此终端摘要中的 `output_exists=false` 只是摘要字段缺失，不是文件失败，目录核验为 PASS。

## 结论与限制

**PASS（当前读/导出并发）**。Current/treatment 读路径没有重复创建历史，也没有锁冲突。

本次没有在 live DEV 上执行会改变业务事实的 Update All/full refresh；避免把验收造数写回人工维护的数据副本。若需要验证写入竞争，应在新的 DEV candidate copy 上单独执行，并记录 writer/reader 事务边界。
