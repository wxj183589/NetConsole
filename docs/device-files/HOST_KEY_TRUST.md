# 主机密钥管理

NetConsole 面向现场运维，已登记且明确授权的设备不要求用户复制或填写
SHA-256 指纹。设备级 Host Key 的权威记录由
`PathResolver.host_key_database_path` 管理：

`config/global/security/host_keys.sqlite`

数据库只保存设备 ID、管理 IP、端口、Key 类型、SHA-256 指纹、策略、时间和审计元数据，
不保存 SSH 私钥、密码或 Host Key 原始字节。`known_hosts` 仍保留为 Paramiko/SFTP 的兼容缓存，
不是设备级策略和历史的唯一事实源。

## 设备级连接策略

设备资源表是自动信任边界。没有非空设备 ID、没有明确授权，Host Key Manager 不会建立或更新信任。
首次连接的流程是“观察 → SSH 认证/连接成功 → 生效”；失败、超时或取消只保留失败审计，
不会把观察到的指纹登记为当前可信指纹。

| 状态 | AUTO_UPDATE | STRICT |
| --- | --- | --- |
| 无当前指纹 | 记录 pending，连接成功后自动生效 | 同样允许首次 TOFU，连接成功后生效 |
| 指纹一致 | 直接连接，成功后更新最近验证时间 | 直接连接，成功后更新最近验证时间 |
| 指纹变化 | 保存旧/新指纹为 pending，按成功连接后自动更新 | 拒绝连接，保留旧指纹，记录拒绝事件 |
| Key 类型/指纹格式不支持 | 拒绝连接 | 拒绝连接 |

`AUTO_UPDATE` 只表示在已授权、受控目标上按策略接受变化后的 Key；它不能独立证明新 Key
属于原设备，不能仅凭 IP 相同或密码认证成功声称完成身份核验。每次变化都产生可查询的
`HOST_KEY_CHANGED`/`HOST_KEY_AUTO_UPDATED` 事件及历史记录。

pending/effective 分离由 SQLite 事务和 `BEGIN IMMEDIATE` 保护。并发连接对同一设备的不同
pending Key 会 fail-closed；同一 pending token 重复提交是幂等的。更新失败时旧的
`current_fingerprint_sha256`、Key 类型和历史不会被覆盖。

## 兼容 known_hosts

仍使用同一个 managed known_hosts：

`PathResolver.global_known_hosts_path` → 数据根下的 `config/global/security/known_hosts`。

没有设备 ID 的旧调用方继续使用兼容层 `AUTO_REPLACE`，只对精确 `host:port` 做原子缓存更新；
新设备连接路径必须把设备 ID 和授权上下文交给 Host Key Manager，不能把兼容层调用误当作
设备身份独立验证。

兼容层跳板机记录仍按精确 `host:port` 管理。经过转发时，设备级 Host Key Manager 使用原始
目标 `host:port`，不会把 `127.0.0.1:随机端口` 写入 known_hosts。连接路径、设备 UUID、设备名、
`direct/jump`、旧指纹、新指纹和时间写入后台日志；AUTO_UPDATE 的变化是可见诊断/恢复事件，
STRICT 的变化则是预期的安全拒绝。

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
