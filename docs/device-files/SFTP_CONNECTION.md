# SFTP 连接

连接参数由设备管理记录和后端 Credential Vault 组装。主地址、备用地址、SSH/SFTP 端口和连接超时沿用设备连接 Profile；页面不读取密码，也不拼接设备命令。

连接状态使用 `DISCONNECTED`、`CONNECTING`、`HOST_KEY_CONFIRMATION_REQUIRED`、`CONNECTED` 和 `FAILED` 等结构化状态。未知主机密钥由 API 返回稳定错误码和指纹挑战；前端可选择仅本次信任或信任并保存。

## 自动启用边界

设备侧启用 SFTP 默认关闭。自动启用只属于独立的 `config_write` 操作，不属于目录浏览、刷新或下载。
触发前必须同时满足：

1. 用户在明确的受控确认中授权本次配置写入；
2. SSH 登录已成功；
3. 后端明确确认 SFTP 子系统不可用，认证失败、网络失败、主机密钥失败和未知异常不得触发写操作；
4. 设备厂商、角色、平台和完整软件版本命中精确的 `device.sftp.enable` Profile。

未知厂商、角色、平台或版本必须失败关闭，不得回退到 H3C 命令、旧构造函数或通用命令拼接。
当前只登记 H3C Comware V7 的交换机、无线 AC 和车载 MR 三类精确 Profile；Huawei、ZTE 和未知
版本不执行。Profile 风险为 `controlled_write`，真实设备状态均为 `REAL_DEVICE_PENDING`。

执行链固定为：

```text
用户授权 -> Application Service -> DeviceOperationService -> Task Center -> Command Profile
```

任务只公开安全的任务 ID、状态、耗时和去敏错误；不得返回密码、Token、命令中的敏感凭据或服务器
绝对路径。命令完成后关闭原 SSH 会话并重新建立 SFTP 会话，再允许目录浏览和下载。Profile 不匹配、
任务取消、命令失败或重新连接失败时保持失败/未连接，不得伪造成功。
