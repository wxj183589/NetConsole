# 设备文件下载

设备文件下载是 Electron/Vue 的只读 SFTP 页面。当前在同一“设备文件下载”模块下还挂载配置采集中心与设备诊断下载入口；业务链路为 `Vue -> FastAPI Router -> FileManagementApplicationService -> FileTransferService`，下载使用现有 Task Center，不创建第二套下载数据库。

## 当前边界

- 设备侧只允许连接、断开、目录浏览、刷新、选择和下载。
- 不提供上传、远程删除、重命名、移动、覆盖配置或远程建目录。
- 本地下载目录由 `PathResolver` 管理；目录和文件操作使用 opaque 引用，下载队列只在专用 DTO 中展示受控真实目标路径。
- SFTP 凭据来自设备管理，密码不进入 DTO、日志、任务快照或 localStorage。
- 连接候选固定为主用直连、备用直连、第一跳到主用/备用、第二跳到主用/备用；空地址跳过、相同主备地址去重，隧道主机存在即视为启用。
- 每条 SFTP 候选路径的 TCP、SSH banner 和认证等待上限为 5 秒，失败后自动尝试下一路径；该限制不影响其他业务连接。
- 跳板机与目标设备分别使用 NetConsole 管理的 `known_hosts` 严格校验；未知密钥进入受控确认，密钥变化直接阻止。

页面初始化分成两阶段：首阶段只读取当前局点和能力状态，随后分别加载本地目录、设备列表和最近
20 条下载任务；设备与队列使用独立 loading，不再用整页遮罩等待历史恢复。活动下载始终优先返回。
`status`、本地目录和下载列表请求均不递归扫描磁盘；宿主 `start()` 只在后台清理超过 24 小时的
`.part`，单次最多检查 1000 个匹配项，失败不阻断页面，也不处理非 `.part`、正式下载或派生/导出文件。

设备文件管理的远程侧严格保持只读。用户只需点击一次“连接 SFTP”；SSH 登录成功且后端明确
确认 SFTP 子系统不可用时，页面首次显示受控确认。用户确认后，同一次连接流程提交独立的
`config_write` 设备操作、等待任务结束、重新建立 SSH/SFTP 会话并读取根目录，不要求返回页面再次连接。
只有设备命中精确的 `device.sftp.enable` 版本化 Command Profile 时，才允许提交该操作。
未知厂商、角色、平台或软件版本必须失败关闭，不得猜测命令或回退到兼容入口。

受控执行链固定为：

```text
Application Service -> DeviceOperationService -> Task Center -> Command Profile
```

启用操作独立记录授权、Profile、任务终态和去敏结果；成功后重新建立 SFTP 会话，失败或取消不得
把设备文件页面误报为已连接。一台 H3C Comware V7 交换机已完成受控启用、SFTP 重连、根目录
读取和 WinSCP Console 独立读取。2026-07-28 已增加真实 Paramiko 跳板机、`direct-tcpip` 与 SFTP
目标的本地集成拓扑，覆盖备用地址、目录读取、大文件校验、会话生命周期和双端主机密钥；该证据不替代
真实 MR 现场闭环，AC、MR 和首次现场主机密钥确认仍为 `REAL_DEVICE_PENDING`。

WinSCP 动作只允许 Renderer 提交 60 秒有效、一次性消费的 `action_ref`。Python 主进程消费动作后
重新读取设备凭据，并默认把 URL 编码后的 SSH 密码交给固定 WinSCP 可执行文件；密码、argv 和认证 URL
不进入 Web DTO 或 Electron IPC，安全命令同时遮蔽原始密码与编码后密码。设备未配置 SSH 密码时拒绝
启动并给出明确说明。若受控 SFTP 已连接，WinSCP 复用实际成功的主用、备用或隧道目标。

本地目录、下载结果和所在目录继续只允许 Renderer 提交一次性 `action_ref`。Backend 消费动作并校验
目标仍位于受控数据根后，把目标交给 Electron Main；实际打开统一使用 `shell.openPath`。打开前主窗口
主动释放焦点，成功后若 Windows 仍让 NetConsole 保持前台则最小化主窗口，避免资源管理器只在任务栏
闪烁；打开失败时不最小化，并恢复动作前的置顶状态。Renderer 不接收本机路径，也不执行系统命令。

“MESH 日志”只勾选当前远程目录中的 `meshlog.log`、`meshlog.log.gz` 和
`YYYY_MM_DD_Nmeshlog.log.gz`，不会创建任务；所有文件统一由“下载选中”提交，且只下载当前明确勾选项。
车载 MR 的这些日志下载只准备 MR Profile 身份、catalog 与 raw/parsed/export
目录，不打开或初始化可重建的 MESH 派生 SQLite。旧派生 schema 不再阻断原始日志下载；下载任务完成后，
自动导入若遇到旧 schema，会把文件保留在 raw 并直接复用内部派生数据维护服务完成备份、重建和校验。
修复完成后会继续原导入，不把数据库维护问题显示为普通日志解析失败，也不要求用户执行 Python 命令或退出软件。

车载 MR 的 raw 文件在下载任务完成并通过大小/SHA-256 校验后，直接以受管 raw 路径登记为
`device_download` 来源并提交既有 MESH 导入服务，不复制第二份文件。下载状态与分析状态分离：下载保持
`COMPLETED`，导入可独立处于 `pending`、`completed`、`duplicate`、`failed` 或 `repair_failed`；导入失败仍保留 raw，
可在队列中重新导入。MESH 分析页的“扫描本地日志”是补偿机制，只扫描当前局点
`rail_transit/mr_raw_mesh/**/raw/**`，递归识别 `.log`、`.log.gz`、`.zip`，按文件大小、mtime 和 SHA-256
增量去重并复用同一导入服务，不访问其他局点。

## 状态

页面和下载队列已接入 Electron。普通文件直接写入设备专属目录或当前受控子目录；精确属于“车载-MR”分组且已关联 MR Profile 的 MESH 日志强制写入对应 `raw` 并自动导入。完成任务不再提供浏览器式“保存”，而是直接刷新左侧列表并提供受控“打开/所在目录”。真实交换机 SFTP 已有单设备现场证据；2026-07-28 的真实 MR 只读尝试在备用直连和两个跳板入口均因网络超时停止，未进入 SFTP 或文件落盘。其余角色与主机密钥场景仍需现场验收，不能仅凭本地集成测试标记为 `COMPLETE`。

专题说明：

- [SFTP 连接](./SFTP_CONNECTION.md)
- [主机密钥信任](./HOST_KEY_TRUST.md)
- [下载流程](./DOWNLOAD_WORKFLOW.md)
- [安全边界](./SECURITY.md)
- [2026-07-28 隧道回归验收记录](./ACCEPTANCE-2026-07-28.md)
