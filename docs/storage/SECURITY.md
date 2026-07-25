# 存储安全边界

- Renderer 不读写文件系统，不解压、不复制、不修改 bootstrap。
- Electron Main 仅处理目录/包/导出路径选择、受控路径打开和 Backend 重启；不执行迁移、SQLite、压缩或业务目录扫描。
- `/api/v1` 路径操作是本机 Desktop Internal API；普通响应不返回 Token、密码或不必要的服务器绝对路径。
- ZIP 项目拒绝 `..`、绝对路径、UNC、符号链接和压缩炸弹；导入包必须有 manifest 和 checksum。
- 所有复制、压缩、解压、校验和迁移使用 Task Center Worker；取消后清理本次临时文件，保留源数据和正式报告。

## 跨电脑凭据边界

- `full_migration` 是无需迁移密码的未加密普通 ZIP，包含完整局点数据库和真实设备凭据。它依赖 manifest、逐文件 SHA-256、ZIP 路径/大小限制和 SQLite 完整性校验防止损坏或被篡改，但不提供机密性；只能保存在可信磁盘并通过受控渠道传递，任何能读取文件的人都可能取得其中的用户名、密码、SNMP community 和隧道凭据。
- `sanitized_share`、现场包和回传包只传递设备资料和非秘密凭据状态，密码、SNMP community 与隧道密码全部清空。
- 普通列表、详情和编辑资料 API 不返回秘密；本机 Electron 编辑页只有在用户点击对应眼睛按钮后，才可经 Desktop/`127.0.0.1`/短期会话三重保护读取单个已保存字段。关闭编辑器会清除 Renderer 中本次读取值，本机 Repository 仍是运行时凭据事实源。
- `needs_reentry` 不是凭据，也不能被解析为空密码；连接任务必须在创建前失败关闭，并提示用户在当前电脑重新录入。
- 密码输入留空表示保留，清除只能通过显式动作；重录后的秘密仍只进入既有本机 Repository。除受保护的单字段 reveal 响应外，Job 参数、`tasks.db`、事件、普通 API 响应和日志不得包含秘密。
