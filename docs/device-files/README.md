# 设备文件下载

设备文件下载是 Electron/Vue 的只读 SFTP 页面。业务链路为 `Vue -> FastAPI Router -> FileManagementApplicationService -> FileTransferService`，下载使用现有 Task Center，不创建第二套下载数据库。

## 当前边界

- 设备侧只允许连接、断开、目录浏览、刷新、选择和下载。
- 不提供上传、远程删除、重命名、移动、覆盖配置或远程建目录。
- 本地下载目录由 `PathResolver` 管理；Renderer 只接收 opaque 引用。
- SFTP 凭据来自设备管理，密码不进入 DTO、日志、任务快照或 localStorage。

设备文件管理的远程侧严格保持只读。自动启用 SFTP 不是文件浏览器的隐式副作用，而是独立的
`config_write` 设备操作。只有用户明确授权、SSH 登录成功、后端明确确认 SFTP 子系统不可用，
并且设备命中精确的 `device.sftp.enable` 版本化 Command Profile 时，才允许提交该操作。
未知厂商、角色、平台或软件版本必须失败关闭，不得猜测命令或回退到兼容入口。

受控执行链固定为：

```text
Application Service -> DeviceOperationService -> Task Center -> Command Profile
```

启用操作独立记录授权、Profile、任务终态和去敏结果；成功后重新建立 SFTP 会话，失败或取消不得
把设备文件页面误报为已连接。当前自动启用和真实设备执行状态仍为 `REAL_DEVICE_PENDING`。

车载 MR 的 `meshlog.log` 和 `YYYY_MM_DD_Nmeshlog.log.gz` 下载只准备 MR Profile 身份、catalog 与 raw/parsed/export
目录，不打开或初始化可重建的 MESH 派生 SQLite。旧派生 schema 不再阻断原始日志下载；下载任务完成后，
自动导入若遇到旧 schema，会单独记录 `MESH_SCHEMA_REBUILD_REQUIRED` / `rebuild_required`，由 MESH 分析页或
任务中心的 `mesh_schema_rebuild` Job 从受保护 raw 日志重建。

## 状态

页面和下载队列已接入 Electron，车载 MR 已提供“下载并传入 MESH 分析”的批量动作；自动启用、真实设备 SFTP、主机密钥和大文件异常仍需现场验收，不能仅凭 Fake 测试标记为 `COMPLETE`。

专题说明：

- [SFTP 连接](SFTP_CONNECTION.md)
- [主机密钥信任](HOST_KEY_TRUST.md)
- [下载流程](DOWNLOAD_WORKFLOW.md)
- [安全边界](SECURITY.md)
