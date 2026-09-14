# SFTP 连接

设备文件连接由 `Vue → FastAPI Router → FileManagementApplicationService → FileTransferService` 完成。
密码只由后端 Credential Vault 组装，Renderer 不读取密码；SFTP、普通设备 SSH、设备详情采集和 SSH
Relay 共用 managed known_hosts。

连接层自动处理 Host Key：首次自动登记、相同继续、变化原子替换后继续。Host Key 变化会记录
`HOST_KEY_AUTO_UPDATED` 和旧/新指纹，不进入确认状态机，也不把原来的目录刷新、下载或设备采集
标记为失败。只有 Host Key 事实源无法更新时才返回 `DEVICE_FILE_HOST_KEY_UPDATE_FAILED`。

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

已知 H3C Comware V7 的 `switch`、`wireless_controller`、`mobile_router` 使用对应的 family Profile；
`wireless_ac`、`wlan_controller`、`controller`、`ac` 在 H3C Comware 上统一规范为
`wireless_controller`。Release 字符串如 `RxxxxPxx` 或版本格式差异不阻断已确认的 V7 family。
软件版本为空时，Worker 先在设备 CLI 执行 `display version`，只有确认 Comware V7 才执行写命令。
Huawei、ZTE、未知厂商/平台/角色或无法确认 major 不会执行 H3C 命令。

当前 H3C V7 SFTP enable Profile 的受控命令为：

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

从设备文件页面启动 WinSCP 时，后端先沿用相同的 Jump/Target managed Host Key 策略完成短 SSH 预连接，
再把当前指纹通过 WinSCP `/hostkey` 参数传入。WinSCP 不再单独弹出 NetConsole 的 Host Key challenge；
预连接失败会返回稳定错误，密码仍只在后端生成。

网络、跳板、认证和目标失败分别返回稳定的 `*_UNREACHABLE`、`*_AUTH_FAILED` 或
`*_FORWARD_OPEN_FAILED`；SFTP 协商失败使用 `DEVICE_FILE_SFTP_NEGOTIATION_FAILED`，Profile 不可用
使用 `DEVICE_FILE_SFTP_ENABLE_PROFILE_UNRESOLVED`，配置/重连失败使用对应的
`DEVICE_FILE_SFTP_ENABLE_FAILED`、`DEVICE_FILE_SFTP_RECONNECT_FAILED`。页面不显示 Paramiko、socket、
密码或原始命令回显。

真实设备上的 AC、MR 和 Host Key 轮换仍标记为 `REAL_DEVICE_PENDING`，本地测试和协议拓扑不能替代
现场验证。
