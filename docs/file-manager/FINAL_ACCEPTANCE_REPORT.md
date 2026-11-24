# 文件管理验收

状态为 **PARTIAL**。已交付独立文件管理页面、设备与终端联动、局点受管目录和真实 SFTP 双向传输。现场设备、Electron 分辨率和制品结果以本版本集成验收记录为准。

## 已交付

- 文件管理页位于 `/file-manager`。设备管理列表、设备详情和 SSH 控制台可携当前设备进入。局点切换清除页面路径、设备和文件选择。
- 左侧显示当前局点的受管下载目录，支持新建目录、进入子目录、分页、名称过滤、排序和多选。右侧按设备分 Tab，复用控制台的 SFTP 路径导航、过滤、排序、右键菜单、文件夹与文件上传、远程文件操作和传输队列。
- 上传左侧选中文件时，前端只发送不透明文件引用，Python 按会话所属局点解析，并按原队列分块暂存、校验和上传。覆盖需要确认。系统文件选择器与原生拖放可处理受管目录外由用户选择的文件。
- 下载到左侧目录使用局点目录引用。后端校验 SHA-256 后发布，同名自动保留副本，目录下载沿用 ZIP。另存仍走控制台 SFTP 的原生 Save As。
- 设备文件下载和 MESH 导入保留原入口、任务状态及落盘规则。文件管理沿用控制台 SFTP 的后台调度、任务台账、失败重试、下载断点恢复、速度与 ETA、传输日志、SSH Relay 和凭据获取。

## 安全与兼容

- 受管上传和下载使用 Backend 颁发的局点文件、目录引用。目标目录必须解析至当前局点的受管下载目录。
- 队列显示当前局点、当前工作区任务，兼容旧传输记录。清除操作按工作区筛选。
- 继续使用 Paramiko、NetConsole 既有凭据库、managed Host Key 和 Relay 路由。文件管理改动没有增加运行时依赖，组件许可沿用 [第三方依赖清单](../release/THIRD_PARTY_DEPENDENCIES.md)。

## 验收证据

| 项目 | 状态 | 证据 |
| --- | --- | --- |
| SFTP、受管下载和设备文件回归 | PASS | `test_terminal_sftp.py`、`test_file_management_page.py`、`test_file_management_service.py`，58 项。 |
| 真实协议双向传输 | PASS | 本地隔离 Paramiko SSH/SFTP 服务验证受管上传、受管下载和同名保全。 |
| Renderer | PASS | 文件管理、旧设备文件下载、控制台 SFTP、设备联动及 API 定向测试，59 项。 |
| Site Relay | PASS | `test_file_transfer_tunnel_integration.py` 验证真实隔离 SSH Jump 和目标 SFTP，包含 Jump/目标 Host Key 登记及变化。测试进程退出时曾报告 Paramiko 转发线程 EOF。 |
| 现场 SFTP 与设备权限 | NOT VERIFIED | 本实现验证使用专用本地 SFTP 测试服务。 |
| Electron UI、三种目标分辨率与安装包 | NOT VERIFIED | 文件管理专项报告无对应验收证据。 |

## 仍未交付

- 任意本地目录浏览，本地复制、移动、重命名、删除。
- 双向目录同步和冲突预览、内置远程编辑、权限修改、路径收藏、递归搜索和脚本化批量传输。
- 文件管理中心的 SCP、FTP/FTPS、WebDAV 和 S3 Adapter，以及断点上传。
- 单次选择向多个设备分发，以及完整的设备配置备份浏览和文件操作审计报告。

变更集中在 `FileManagerWorkspaceView.vue`、`TerminalSftpPanel.vue`、终端 API、`TerminalSftpManager`、`FileManagementApplicationService` 和相关测试。Git 和制品信息由同一功能分支的最终集成记录提供。
