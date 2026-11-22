# Transport Adapters

| Transport | 实现 | 自动测试 | 真实设备 |
| --- | --- | --- | --- |
| SSH | Paramiko `SSHClient.invoke_shell(term, width, height)`、实时 recv/send、PTY resize | ISOLATED_SERVER_VERIFIED | NOT_VERIFIED |
| Telnet | 独立 Socket、登录提示、IAC、TTYPE、NAWS；不使用 Site SSH Relay | ISOLATED_SERVER_VERIFIED | NOT_VERIFIED |
| SFTP | 独立 Paramiko SSH client + `open_sftp()`；不复用终端 Shell Channel | ISOLATED_SERVER_VERIFIED | NOT_VERIFIED |
| Site SSH Relay | SSH/SFTP 复用 Site relay 配置，但各自建立活动连接 | CODE_VERIFIED | NOT_VERIFIED |
| Serial/COM | 未发现旧版已纳入本专项的硬件能力 | NOT_IMPLEMENTED | NOT_VERIFIED |

## 已知边界

- SSH、Telnet 和 SFTP 已分别通过本机隔离 server 验证登录、交互或文件操作；现场设备、断网恢复、厂商分页和编码仍待授权验证。
- 控制台连接不调用 Netmiko `ConnectHandler` 或 `send_command`。自动化仍统一走共享 Netmiko 适配层。
- PTY resize 直接调用 Paramiko channel `resize_pty`；Telnet resize 发送 NAWS。
