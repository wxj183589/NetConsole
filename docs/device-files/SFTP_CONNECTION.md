# SFTP 连接

连接参数由设备管理记录和后端 Credential Vault 组装。主地址、备用地址和 SSH/SFTP 端口沿用设备
连接 Profile；设备文件 SFTP 的每条候选路径将 TCP、SSH banner 和认证等待上限固定为 5 秒，
失败后自动尝试下一路径。该限制不改变设备采集、Online MR 等其他连接场景的默认超时。页面不读取
密码，也不拼接设备命令。

连接状态机为 `INITIAL_CONNECT -> HOST_KEY_CONFIRM -> SFTP_UNAVAILABLE -> SFTP_ENABLE_CONFIRM ->
SFTP_ENABLING -> SFTP_RECONNECTING -> CONNECTED|FAILED`。未知主机密钥由 API 返回稳定错误码和指纹
挑战；前端可选择仅本次信任或信任并保存。即使挑战发生在用户已经确认启用 SFTP 之后，确认主机
密钥也只继续重连，不会丢失原意图或再次提交启用命令。

连接错误固定分类为 `DEVICE_FILE_DIRECT_UNREACHABLE`、`DEVICE_FILE_JUMP_HOST_UNREACHABLE`、
`DEVICE_FILE_JUMP_HOST_AUTH_FAILED`、`DEVICE_FILE_JUMP_HOST_KEY_UNKNOWN`、
`DEVICE_FILE_JUMP_HOST_KEY_MISMATCH`、`DEVICE_FILE_FORWARD_OPEN_FAILED`、
`DEVICE_FILE_TARGET_UNREACHABLE_VIA_TUNNEL`、`DEVICE_FILE_TARGET_AUTH_FAILED`、
`DEVICE_FILE_TARGET_HOST_KEY_UNKNOWN`、`DEVICE_FILE_TARGET_HOST_KEY_MISMATCH`、
`DEVICE_FILE_SFTP_UNAVAILABLE`、`DEVICE_FILE_SFTP_NEGOTIATION_FAILED`、
`DEVICE_FILE_SFTP_ENABLE_UNSUPPORTED`、`DEVICE_FILE_SFTP_ENABLE_PROFILE_UNRESOLVED`、
`DEVICE_FILE_SFTP_ENABLE_PENDING`、`DEVICE_FILE_SFTP_ENABLE_FAILED`、
`DEVICE_FILE_SFTP_RECONNECT_FAILED`、`DEVICE_FILE_REMOTE_ROOT_NOT_FOUND` 和
`DEVICE_FILE_DOWNLOAD_FAILED`。远程会话中途失效使用 `DEVICE_FILE_SESSION_DISCONNECTED`。
页面不显示 Paramiko、socket 或通道原始异常。

## 自动启用边界

页面不提供“允许自动配置”常驻开关。用户点击一次连接后，先按统一连接策略尝试 SSH/SFTP；只有
`Channel closed`、认证后 `EOF`、子系统请求被拒绝、子系统不可用、管理策略禁止或明确的 SFTP
disabled/not enabled 等稳定分类才进入恢复分支。H3C 拒绝子系统时可能同时关闭 Channel 或整个
SSH Transport，因此 `transport_active` 只记录诊断，不能否决已认证 `open_sftp` 阶段的子系统拒绝。
无法明确归类的认证后 `open_sftp` 异常固定返回 `DEVICE_FILE_SFTP_NEGOTIATION_FAILED`，不得回落为
网络不可达；原始 Paramiko 异常不得返回页面。自动启用只属于独立的
`config_write` 操作，不属于目录浏览、刷新或下载。触发前必须同时满足：

1. 用户在明确的受控确认中授权本次配置写入；
2. SSH 登录已成功；
3. 后端明确确认 SFTP 子系统不可用，认证失败、网络失败、主机密钥失败和未知异常不得触发写操作；
4. 设备厂商、角色、平台和完整软件版本命中精确的 `device.sftp.enable` Profile。

未知厂商、角色、平台或版本必须失败关闭，不得回退到 H3C 命令、旧构造函数或通用命令拼接。
当前只登记 H3C Comware V7 的交换机、无线 AC 和车载 MR 三类精确 Profile；Huawei、ZTE 和未知
版本不执行。缺少可信软件版本时返回 `DEVICE_FILE_SFTP_ENABLE_PROFILE_UNRESOLVED`，不执行配置命令。
Profile 风险为 `controlled_write`，真实设备状态均为 `REAL_DEVICE_PENDING`。

2026-07-23 已在一台 H3C Comware V7 交换机上完成“识别子系统拒绝 -> 用户确认 -> 5 个受控
步骤 -> 新建 SFTP 会话 -> 根目录读取 -> WinSCP Console 独立读取”的现场闭环。该证据只覆盖交换机
角色的一台设备，AC、MR、首次主机密钥确认和大文件异常仍未覆盖，因此 Profile 目录状态不整体提升。

执行链固定为：

```text
一次连接 -> 用户首次确认 -> Application Service -> DeviceOperationService -> Task Center -> Command Profile
         -> 等待终态 -> 重建 SSH/SFTP -> 读取根目录
```

任务只公开安全的任务 ID、状态、耗时和去敏错误；不得返回密码、Token 或命令中的敏感凭据。
命令完成后关闭原 SSH 会话并重新建立 SFTP 会话，再允许目录浏览和下载。Profile 不匹配、
任务取消、命令失败或重新连接失败时保持失败/未连接，不得伪造成功。

每次连接按统一目标策略依次尝试 `primary_direct`、`backup_direct`、`tunnel1_primary`、
`tunnel1_backup`、`tunnel2_primary`、`tunnel2_backup`。空地址不生成目标，主备地址相同时去重；
第一跳和第二跳是可替代入口，不构成级联二跳。表单和导入保存均以隧道主机存在作为启用事实，
不依赖页面中不存在的启用开关。

连接成功 DTO 返回原始目标地址、主备角色、隧道入口和已尝试路径，不返回本地
`127.0.0.1` 随机转发端口。页面据此显示实际链路；连接失败时展示逐路径的稳定、脱敏摘要。
同设备的 WinSCP 动作继续复用实际成功目标，避免内置 SFTP 与 WinSCP 选择不同地址。

隧道 SFTP 会话在目录读取和下载期间持有跳板 SSH Client、`direct-tcpip` Channel、转发 Server、
目标 SSH Client 与 SFTP Client。断开时先关闭 SFTP，再关闭目标 SSH，最后释放转发和跳板连接；
取消、失败和重复关闭均保持幂等。下载失败清理 `.part` 并返回 `DEVICE_FILE_DOWNLOAD_FAILED`。

目录刷新、进入目录或下载提交前会再次检查会话。会话失效后服务端销毁 `connection_id`，页面清空
远程列表和选择，并只显示“设备文件会话已断开，请重新连接”。
