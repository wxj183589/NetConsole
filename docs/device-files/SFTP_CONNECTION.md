# SFTP 连接

连接参数由设备管理记录和后端 Credential Vault 组装。主地址、备用地址、SSH/SFTP 端口和连接超时沿用设备连接 Profile；页面不读取密码，也不拼接设备命令。

连接状态使用 `DISCONNECTED`、`CONNECTING`、`HOST_KEY_CONFIRMATION_REQUIRED`、`CONNECTED` 和 `FAILED` 等结构化状态。未知主机密钥由 API 返回稳定错误码和指纹挑战；前端可选择仅本次信任或信任并保存。

设备侧启用 SFTP 默认关闭。只有识别厂商、角色、平台、完整软件版本且命中 `device.sftp.enable` 版本化 Profile 时才允许进入受控写操作；未验证版本拒绝执行。
