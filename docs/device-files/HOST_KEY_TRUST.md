# 主机密钥管理

NetConsole 面向现场运维，SSH/SFTP Host Key 不需要用户确认、复制指纹或选择“仅本次/永久信任”。
所有 SSH consumer 使用同一个 managed known_hosts：

`PathResolver.global_known_hosts_path` → 数据根下的 `config/global/security/known_hosts`。

连接层统一采用 `AUTO_REPLACE`：

| 状态 | 处理 |
| --- | --- |
| `UNKNOWN` | 保存当前 `host:port` 的服务端 Host Key，继续连接 |
| `MATCH` | 继续连接 |
| `MISMATCH` | 只原子替换当前 `host:port` 的记录，记录旧/新指纹，继续连接 |

跳板机和目标设备都遵循这套规则。经过转发时，目标记录仍使用原始目标 `host:port`，不会把
`127.0.0.1:随机端口` 写入 known_hosts。连接路径、设备 UUID、设备名、`direct/jump`、旧指纹、新指纹
和时间写入后台日志；Host Key 变化是诊断/恢复事件，不是正常业务失败。

写入由锁文件和原子替换保护；按精确 `host + port` 替换，不影响其它设备或其它跳板机。known_hosts
损坏时保留仍可解析的行并记录恢复告警，避免单条坏记录拖垮全部 SSH/SFTP。不要求维护
`%USERPROFILE%\\.ssh\\known_hosts`，也不使用系统 SSH、设备文件、设备采集的第二份信任事实源。

## 跳板机现场维护

系统设置 → SSH 中转提供“重新获取指纹”和“删除指纹”。两者只作用于当前局点配置的
`jump_host + jump_port`：

- 重新获取：连接当前跳板机，取得真实 Host Key，原子替换记录并刷新页面，显示“指纹已更新”；
- 删除指纹：删除该精确地址，状态显示“未记录”；下一次测试或业务连接会自动重新登记。

按钮只用于排障，不是正常连接的前置步骤。真正的认证失败、凭据错误、网络不可达、设备拒绝登录或
Host Key 事实源无法写入，仍然失败。页面只显示脱敏稳定错误码，不返回密钥字节或密码。
