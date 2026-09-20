# SFTP 连接

设备文件连接由 `Vue → FastAPI Router → FileManagementApplicationService → FileTransferService` 完成。
密码只由后端 Credential Vault 组装，Renderer 不读取密码；SFTP、普通设备 SSH、设备详情采集和 SSH
Relay 共用 managed known_hosts。Relay ON 时文件列表、SFTP 连接、下载和 SCP
fallback 都通过当前局点 Jump Host 的 `direct-tcpip` 到达目标；不会再创建
第二套 per-device 隧道，也不会把 `127.0.0.1:随机端口` 当作目标身份。Relay OFF
继续使用原有直连、备份和 legacy per-device tunnel 回退。

连接层自动处理 Host Key：`UNKNOWN → AUTO ADD`、`MATCH → 继续`、`MISMATCH → AUTO REPLACE`
后继续。变化会记录 `HOST_KEY_AUTO_UPDATED` 和旧/新指纹，不进入确认状态机，也不把原来的目录刷新、
下载或设备采集标记为失败。只有 Host Key 事实源无法更新时才返回
`DEVICE_FILE_HOST_KEY_UPDATE_FAILED`。

## 自动启用 SFTP

用户只需点击一次“连接 SFTP”。流程是：

```text
SSH 登录 → 探测 SFTP subsystem
       ├─ 可用 → 读取根目录
       └─ 不可用 → 解析已验证 Profile → Task Center → 等待成功
                  → 关闭旧 SSH → 重建 SSH/SFTP → 读取根目录
```

已经可用时不会执行配置。只有 SSH authentication 已成功且 SFTP subsystem 被明确拒绝，才会提交
`device.sftp.enable`；密码错误、跳板/目标不可达、认证失败、Host Key 写入失败和未知异常不会触发
设备配置。

已知 H3C Comware V7/V9 的 `switch`、`wireless_controller`、`mobile_router` 使用对应的 family Profile；
`wireless_ac`、`wlan_controller`、`controller`、`ac` 在 H3C Comware 上统一规范为
`wireless_controller`。Release 字符串如 `RxxxxPxx` 或版本格式差异不阻断已确认的 V7/V9 family；
V9 使用 `family_compatible` controlled-write Profile，不假设 V7 命令兼容性。
软件版本为空时，Worker 先在设备 CLI 执行 `display version`，只有确认 Comware V7 或 V9 才执行写命令。
Huawei、ZTE、未知厂商/平台/角色或无法确认 major 不会执行 H3C 命令。

当前 H3C Comware V7/V9 SFTP enable Profile 的受控命令模板为：

```text
system-view
sftp server enable
ssh user {username} service-type all authentication-type any
return
quit
```

命令由 `DeviceOperationService` 创建 `device_sftp_enable` Task，Worker 重新校验设备、平台、角色、
Profile ID/version，再通过统一 `DeviceSSHConnectionFactory` 执行。任务成功后由 Application Service
立即重建 SFTP 并继续原始连接意图，不要求用户再次点击。

从设备文件页面启动 WinSCP 时仍可使用其已有的直连或 legacy 临时隧道路径；WinSCP
Site Relay 本轮未完成，不能把 `WINSCP_SITE_RELAY` 记为 PASS。SecureCRT、Xshell、PuTTY
和独立 Agent 同样不在 Backend Site Relay 范围内。

网络、跳板、认证和目标失败分别返回稳定的 `*_UNREACHABLE`、`*_AUTH_FAILED` 或
`*_FORWARD_OPEN_FAILED`；SFTP 协商失败使用 `DEVICE_FILE_SFTP_NEGOTIATION_FAILED`，Profile 不可用
使用 `DEVICE_FILE_SFTP_ENABLE_PROFILE_UNRESOLVED`，配置/重连失败使用对应的
`DEVICE_FILE_SFTP_ENABLE_FAILED`、`DEVICE_FILE_SFTP_RECONNECT_FAILED`。页面不显示 Paramiko、socket、
密码或原始命令回显。

当前验收状态按能力拆分：H3C WX3540X / Comware V9 的 SFTP controlled-write 与 reconnect
已有限定范围真实证据；真实 MR 文件链路和目标 Host Key 轮换仍为 `PENDING_REAL_DEVICE`；
Site Relay 的真实 Jump Host 环境不存在，标记为 `PENDING_NO_ENV`；WinSCP Site Relay
保持 `NOT_COMPLETED`。本地测试和协议拓扑不能替代对应现场验证，完整矩阵见
[真实设备能力矩阵](../development/REAL_DEVICE_CAPABILITY_MATRIX_20260920.md)。
