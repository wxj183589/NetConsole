# 安全边界

- Vue 不导入 SFTP/Paramiko，不访问设备凭据或本地文件系统。
- FastAPI Router 不创建 SFTP client、不读写 known_hosts、不执行设备命令。
- Electron Main 只处理本地目录选择、打开文件/目录和固定 WinSCP 白名单动作。
- 设备端保持只读；启用 SFTP 是单独的、版本化、可审计的设备操作。
- 自动启用只在用户明确授权、SSH 登录成功且明确确认 SFTP 子系统不可用时触发；认证、网络、主机密钥或未知错误均失败关闭。
- 自动启用必须由 Application Service 经 `DeviceOperationService` 提交到现有 Task Center，并由精确匹配的 `device.sftp.enable` Profile 执行；未知厂商、角色、平台和版本不得猜测或回退。
- 任务参数、DTO、事件和日志不得包含密码、Token、服务器绝对路径或未脱敏命令回显；用户名只按已验证 Profile 的安全规则绑定。
- 当前受控启用的真实设备状态为 `REAL_DEVICE_PENDING`，Fake/fixture 通过不等于现场配置成功。
- 外部终端密码传递默认关闭，启用时必须经过 `SECURITY` 类型全局确认。
