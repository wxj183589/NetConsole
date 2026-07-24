# 存储安全边界

- Renderer 不读写文件系统，不解压、不复制、不修改 bootstrap。
- Electron Main 仅处理目录/包/导出路径选择、受控路径打开和 Backend 重启；不执行迁移、SQLite、压缩或业务目录扫描。
- `/api/v1` 路径操作是本机 Desktop Internal API；普通响应不返回 Token、密码或不必要的服务器绝对路径。
- ZIP 项目拒绝 `..`、绝对路径、UNC、符号链接和压缩炸弹；导入包必须有 manifest 和 checksum。
- 所有复制、压缩、解压、校验和迁移使用 Task Center Worker；取消后清理本次临时文件，保留源数据和正式报告。

## 跨电脑凭据边界

- 本次不增加 DPAPI、主密钥或其他凭据加密方案，现有本机设备凭据存储格式保持不变。
- 普通 `.ncsite` / 现场包只传递设备资料和非秘密凭据状态，密码、SNMP community 与隧道密码全部清空。
- `needs_reentry` 不是凭据，也不能被解析为空密码；连接任务必须在创建前失败关闭，并提示用户在当前电脑重新录入。
- 重录后的秘密仍只进入既有本机 Repository；Job 参数、`tasks.db`、事件、API 响应和日志不得包含秘密。
