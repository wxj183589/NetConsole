# 设备文件下载

设备文件下载是 Electron/Vue 的只读 SFTP 页面。业务链路为 `Vue -> FastAPI Router -> FileManagementApplicationService -> FileTransferService -> SftpTransport`，下载使用现有 Task Center，不创建第二套下载数据库。

## 当前边界

- 设备侧只允许连接、断开、目录浏览、刷新、选择和下载。
- 不提供上传、远程删除、重命名、移动、覆盖配置或远程建目录。
- 本地下载目录由 `PathResolver` 管理；Renderer 只接收 opaque 引用。
- SFTP 凭据来自设备管理，密码不进入 DTO、日志、任务快照或 localStorage。

## 状态

页面和下载队列已接入 Electron，但真实设备 SFTP、主机密钥和大文件异常仍需现场验收，不能仅凭 Fake 测试标记为 `COMPLETE`。

专题说明：

- [SFTP 连接](SFTP_CONNECTION.md)
- [主机密钥信任](HOST_KEY_TRUST.md)
- [下载流程](DOWNLOAD_WORKFLOW.md)
- [安全边界](SECURITY.md)
