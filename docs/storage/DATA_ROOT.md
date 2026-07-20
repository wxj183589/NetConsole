# 全局数据根

`app_root` 是程序/资源位置，`data_root` 是用户持久数据位置，`site_root` 是 `<data_root>/data/sites/<site_id>`。数据根不得是仓库、安装目录、系统临时目录或当前数据根的嵌套目录。

Windows 默认值：

- 开发：`%LOCALAPPDATA%\NetConsole\Development`
- 打包：`%LOCALAPPDATA%\NetConsole`

Electron 在 `app.getPath("userData")/bootstrap.json` 原子保存最小配置：`schema_version`、`data_root`、`active_site_id`。文件损坏时使用默认路径，不保存密码、Token 或设备凭据。

正常开发和打包运行使用 `persistent` 存储模式。Codex、任务窗口冒烟和打包冒烟使用独立的 `isolated_test` 模式，同时隔离 data root 与 Electron `userData`；临时实例禁止局点/数据根写操作，也不会读取或保存正式 bootstrap。持久模式若发现 bootstrap 指向 Temp、`NetConsole-Codex-*`、不存在目录或不完整目录，会备份原文件并拒绝使用该引用，不会因为 Backend/Python 启动失败而创建或切换 demo。

维护命令默认只读且不输出完整数据根或局点名称；`--repair` 先备份、再从已有持久化根和已有局点恢复引用，多局点无法确定时必须使用 `--site-id`，不会删除、移动或初始化业务数据：

```powershell
.\.venv\Scripts\python.exe -m scripts.maintenance.check_desktop_bootstrap
.\.venv\Scripts\python.exe -m scripts.maintenance.check_desktop_bootstrap --repair
```

候选路径必须先由 Electron 原生目录选择器取得，再由 `/api/v1/storage/data-root/validate` 校验。迁移复制到 staging，完成文件与 SQLite 校验后发布；旧数据根保留，Backend 受控重启后才使用新路径。
