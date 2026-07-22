# 安全边界

- Vue 不导入 SFTP/Paramiko，不访问设备凭据或本地文件系统。
- FastAPI Router 不创建 SFTP client、不读写 known_hosts、不执行设备命令。
- Electron Main 只处理本地目录选择、打开文件/目录和固定 WinSCP 白名单动作。
- 设备端保持只读；启用 SFTP 是单独的、版本化、可审计的设备操作。
- 页面不提供常驻自动配置开关；自动启用只在用户首次明确确认、SSH 登录成功且明确确认 SFTP 子系统不可用时触发，并在同一次连接流程继续。认证、网络、主机密钥或未知错误均失败关闭。
- 自动启用必须由 Application Service 经 `DeviceOperationService` 提交到现有 Task Center，并由精确匹配的 `device.sftp.enable` Profile 执行；未知厂商、角色、平台和版本不得猜测或回退。
- 任务参数、普通 DTO、事件和日志不得包含密码、Token 或未脱敏命令回显；用户名只按已验证 Profile 的安全规则绑定。下载队列按业务要求在专用 DTO 显示真实受控目标路径，但打开/定位仍必须使用一次性 opaque 桌面动作，Renderer 不能提交任意路径。
- 当前受控启用的真实设备状态为 `REAL_DEVICE_PENDING`，Fake/fixture 通过不等于现场配置成功。
- 通用外部终端密码传递仍按其独立设置控制；设备文件页面的固定 WinSCP 动作默认自动登录。Renderer
  只提交一次性 `action_ref`，Python 主进程消费后重新读取设备并生成认证参数，密码、argv 和完整 URL
  不进入 Web DTO、Electron IPC、localStorage 或日志；安全命令同时遮蔽原始密码和 URL 编码密码。
