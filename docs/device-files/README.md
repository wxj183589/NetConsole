# 设备文件下载

设备文件下载是只读 SFTP 页面，链路为 `Vue → FastAPI Router → FileManagementApplicationService →
FileTransferService`，下载任务继续使用现有 Task Center。

## 产品边界

- 设备侧只允许连接、断开、目录浏览、刷新、选择和下载；不提供上传、删除、重命名或覆盖配置。
- 凭据来自后端 Credential Vault，密码不进入 DTO、日志、任务快照、Renderer 或 localStorage。
- 主用/备用直连和跳板候选路径由后端自动尝试，失败后按稳定错误分类继续候选路径。
- 所有 SSH/SFTP consumer 共用数据根 `config/global/security/known_hosts`，Host Key unknown 自动登记、
  match 继续、mismatch 自动替换并继续；不提供信任挑战或确认 UI。
- 系统设置 → SSH 中转的“重新获取指纹/删除指纹”只作用于当前 `jump_host + jump_port`，用于现场排障。

## 一次点击连接

用户点击“连接 SFTP”后，后端先探测 subsystem。已开启则直接进入根目录；明确确认 subsystem 不可用
时，自动解析已验证的 H3C Comware SFTP enable Profile，创建 Task Center 任务，等待成功，关闭旧 SSH
并重建 SFTP。启用成功后继续同一次连接意图，不需要手工开 CLI、不需要手工选择 Profile、不需要再次点击。
页面启动 WinSCP 前也会先用同一 managed Host Key 事实源完成 SSH 预连接，并把当前指纹传给 WinSCP，
避免外部进程再次要求现场人员处理 NetConsole 的 Host Key 信任。

支持的 H3C 角色包括 `switch`、`wireless_controller` 和 `mobile_router`；历史角色别名在 H3C Comware
上下文中统一归一化。未知厂商、未知平台、无法确认 Comware V7 或认证/网络失败均不会执行 H3C 命令。

## 安全与可恢复性

Host Key 更新是后台 warning/recovery event，不是正常业务失败；只有事实源写入失败、认证失败、设备
明确拒绝配置、命令错误或 SFTP 重连失败才结束为失败。known_hosts 使用锁和原子替换；损坏时尽量恢复
有效行并记录诊断，不影响其它设备记录。系统不要求维护 `%USERPROFILE%\\.ssh\\known_hosts`。

真实设备的 H3C AC/MR 闭环和现场 Host Key 轮换仍为 `REAL_DEVICE_PENDING`。

专题说明：

- [SFTP 连接](./SFTP_CONNECTION.md)
- [主机密钥管理](./HOST_KEY_TRUST.md)
- [下载流程](./DOWNLOAD_WORKFLOW.md)
- [安全边界](./SECURITY.md)
