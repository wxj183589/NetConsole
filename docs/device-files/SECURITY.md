# 安全边界

- Vue 不导入 Paramiko，不访问设备凭据或本地文件系统。
- FastAPI Router 不创建 SFTP client、不读写 known_hosts、不执行设备命令。
- Electron Main 只处理受控本地目录动作和固定 WinSCP 白名单动作。
- 设备文件浏览保持只读；SFTP enable 是单独、版本化、可审计的 `device.sftp.enable` controlled-write
  Profile。
- Host Key 使用一个 managed known_hosts：unknown 自动保存，match 继续，mismatch 精确替换后继续。
  这不等于关闭 Host Key 读取，也不使用未持久化的 `AutoAddPolicy`。变化记录后台日志，现场无需确认。
- 自动启用只在 SSH authentication 成功且 subsystem 明确不可用时触发。认证、网络、Host Key 持久化
  或未知设备事实失败时不会触发写命令。
- 只允许已知 H3C Comware V7/V9 与支持角色的 Profile；V9 使用显式 `family_compatible` controlled-write
  Profile，不复用或假设 V7 selector；软件版本为空时先由设备 `display version` 确认 V7/V9。
  Huawei、ZTE、未知厂商/平台/角色和无法确认 major 均 fail closed。
- 任务、DTO、事件和日志不得包含密码、Token、密钥字节或未脱敏命令回显。

真实交换机已有受控启用和 SFTP 读取证据；AC、MR、现场 Host Key 轮换及其它未连接的真实设备范围
继续标记为 `REAL_DEVICE_PENDING`。
