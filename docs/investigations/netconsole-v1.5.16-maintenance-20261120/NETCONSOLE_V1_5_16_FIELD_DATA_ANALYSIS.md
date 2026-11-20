# NetConsole v1.5.16 现场数据分析

## 数据包

| 项目 | 值 |
| --- | --- |
| 文件 | `hzl9-NetConsoleData.rar` |
| SHA-256 | `B785746E5C9299C5795DD375C5118308F854AAEA8275F492CF070DA5C347A383` |
| 大小 | 17,157,492 bytes |
| 解压文件数 | 1,103 |
| 分析方式 | Workspace 隔离目录，只读 |

## 复核到的线索

1. Electron 日志存在 Renderer `reason=crashed`、`exit_code=-36861`；该记录不足以单独证明根因。
2. Quick Ping 持久运行对象把内部 `_close_confirmed` 带入严格 API DTO，触发 `extra_forbidden`。本轮在 DTO 边界净化内部字段并增加回归。
3. Backend 关闭阶段读取 `task_snapshots` 时可能遇到表不存在。本轮把该数据库错误转为警告和运行态计数，不再形成未处理关闭异常。
4. 局点回收/导入日志显示首次导入失败、活动登记不一致和后续重试恢复。main 已有 staged replacement 与恢复测试，本轮复核并运行回归，不操作现场 `.trash`。
5. Heartbeat、基础资料和 AC 相关查询存在大数据量耗时线索；本轮不通过丢字段或一次性加载历史来换取表面性能。

## 隐私与数据完整性

本文不记录设备密码、密钥、真实管理地址、MAC 清单或主机指纹。未打开写事务修改现场 SQLite，未把解压目录作为运行数据根。
