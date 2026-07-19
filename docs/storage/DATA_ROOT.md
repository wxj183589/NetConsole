# 全局数据根

`app_root` 是程序/资源位置，`data_root` 是用户持久数据位置，`site_root` 是 `<data_root>/data/sites/<site_id>`。数据根不得是仓库、安装目录、系统临时目录或当前数据根的嵌套目录。

Windows 默认值：

- 开发：`%LOCALAPPDATA%\NetConsole\Development`
- 打包：`%LOCALAPPDATA%\NetConsole`

Electron 在 `app.getPath("userData")/bootstrap.json` 原子保存最小配置：`schema_version`、`data_root`、`active_site_id`。文件损坏时使用默认路径，不保存密码、Token 或设备凭据。

候选路径必须先由 Electron 原生目录选择器取得，再由 `/api/v1/storage/data-root/validate` 校验。迁移复制到 staging，完成文件与 SQLite 校验后发布；旧数据根保留，Backend 受控重启后才使用新路径。
