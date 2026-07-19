# 存储安全边界

- Renderer 不读写文件系统，不解压、不复制、不修改 bootstrap。
- Electron Main 仅处理目录/包/导出路径选择、受控路径打开和 Backend 重启；不执行迁移、SQLite、压缩或业务目录扫描。
- `/api/v1` 路径操作是本机 Desktop Internal API；普通响应不返回 Token、密码或不必要的服务器绝对路径。
- ZIP 项目拒绝 `..`、绝对路径、UNC、符号链接和压缩炸弹；导入包必须有 manifest 和 checksum。
- 所有复制、压缩、解压、校验和迁移使用 Task Center Worker；取消后清理本次临时文件，保留源数据和正式报告。
