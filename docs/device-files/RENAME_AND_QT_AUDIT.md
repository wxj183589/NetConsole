# 页面更名与 Qt 历史取证

## Qt 事实源

Git 历史提交 `81ab0ee6` 首次引入 `netconsole/ui/pages/file_management_page.py`、`netconsole/services/file_transfer_service.py` 和对应测试；后续 `67db439a` 调整了对话框样式，`1e905b94` 收口目录。Qt 页面使用后台线程连接 SFTP、浏览远程目录、写入受控下载目录、校验下载并支持 WinSCP 联动。

## Electron 对照

| 能力 | Qt 历史行为 | Electron 当前实现 |
| --- | --- | --- |
| 凭据 | 读取设备连接配置 | 后端读取设备管理 Credential Vault |
| 地址与端口 | 主/备用 SSH 目标，默认 SSH 端口 | 复用 `connection_targets` |
| 远程根目录 | 探测 `flash:/` 等设备根 | SFTP 会话内 opaque 条目 |
| 下载目录 | 局点受控文件下载目录 | `PathResolver.file_downloads_root` |
| 文件冲突 | 自动重命名并保留扩展名 | `.part` + 自动重命名 |
| 下载后打开 | 桌面动作打开文件/目录 | Electron Main 白名单 path reference |
| WinSCP | 固定程序联动 | 受控桌面动作，参数不含密码 |
| 主机密钥 | 依赖 Paramiko/系统 known_hosts | NetConsole 数据根管理的 known_hosts；未知密钥应用内确认 |
| 设备写操作 | 旧流程可尝试启用 SFTP | 仅命中版本化 `device.sftp.enable` Profile 时允许 |

Qt 源码仅作为行为事实源保留在 Git 历史中，不恢复 Qt UI、QThread、Signal 或 PySide6 依赖。
