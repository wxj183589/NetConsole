# 设备文件下载

设备文件下载是 Electron/Vue 的只读 SFTP 页面。业务链路为 `Vue -> FastAPI Router -> FileManagementApplicationService -> FileTransferService`，下载使用现有 Task Center，不创建第二套下载数据库。

## 当前边界

- 设备侧只允许连接、断开、目录浏览、刷新、选择和下载。
- 不提供上传、远程删除、重命名、移动、覆盖配置或远程建目录。
- 本地下载目录由 `PathResolver` 管理；目录和文件操作使用 opaque 引用，下载队列只在专用 DTO 中展示受控真实目标路径。
- SFTP 凭据来自设备管理，密码不进入 DTO、日志、任务快照或 localStorage。

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
读取和 WinSCP Console 独立读取；AC、MR、首次主机密钥和大文件异常仍为 `REAL_DEVICE_PENDING`。

WinSCP 动作只允许 Renderer 提交 60 秒有效、一次性消费的 `action_ref`。Python 主进程消费动作后
重新读取设备凭据，并默认把 URL 编码后的 SSH 密码交给固定 WinSCP 可执行文件；密码、argv 和认证 URL
不进入 Web DTO 或 Electron IPC，安全命令同时遮蔽原始密码与编码后密码。设备未配置 SSH 密码时拒绝
启动并给出明确说明。若受控 SFTP 已连接，WinSCP 复用实际成功的主用、备用或隧道目标。

“MESH 日志”只勾选当前远程目录中的 `meshlog.log`、`meshlog.log.gz` 和
`YYYY_MM_DD_Nmeshlog.log.gz`，不会创建任务；所有文件统一由“下载选中”提交，且只下载当前明确勾选项。
车载 MR 的这些日志下载只准备 MR Profile 身份、catalog 与 raw/parsed/export
目录，不打开或初始化可重建的 MESH 派生 SQLite。旧派生 schema 不再阻断原始日志下载；下载任务完成后，
自动导入若遇到旧 schema，会单独记录 `MESH_SCHEMA_REBUILD_REQUIRED` / `rebuild_required`，由 MESH 分析页或
任务中心的 `mesh_schema_rebuild` Job 从受保护 raw 日志重建。

## 状态

页面和下载队列已接入 Electron。普通文件直接写入设备专属目录或当前受控子目录；精确属于“车载-MR”分组且已关联 MR Profile 的 MESH 日志强制写入对应 `raw` 并自动导入。完成任务不再提供浏览器式“保存”，而是直接刷新左侧列表并提供受控“打开/所在目录”。真实交换机 SFTP 已有单设备现场证据；其余角色、主机密钥和大文件异常仍需现场验收，不能仅凭 Fake 测试标记为 `COMPLETE`。

专题说明：

- [SFTP 连接](SFTP_CONNECTION.md)
- [主机密钥信任](HOST_KEY_TRUST.md)
- [下载流程](DOWNLOAD_WORKFLOW.md)
- [安全边界](SECURITY.md)
