# 安全边界

- Vue 不导入 SFTP/Paramiko，不访问设备凭据或本地文件系统。
- FastAPI Router 不创建 SFTP client、不读写 known_hosts、不执行设备命令。
- Electron Main 只处理本地目录选择、打开文件/目录和固定 WinSCP 白名单动作。
- 设备端保持只读；启用 SFTP 是单独的、版本化、可审计的设备操作。
- 外部终端密码传递默认关闭，启用时必须经过 `SECURITY` 类型全局确认。
