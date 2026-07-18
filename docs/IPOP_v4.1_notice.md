# IPOP v4.1 可选外部工具说明

IPOP v4.1 为第三方可选外部工具，不随 NetConsole 分发。NetConsole 仅启动用户自行取得并在“系统设置 → 外部工具”中配置的本地程序；相关软件的著作权及其他权利归其权利人所有。

仓库没有可核验的 IPOP LICENSE、NOTICE、来源授权书或再分发许可，因此不声明其属于 MIT、GPL 或 NetConsole 的授权范围，也不声明项目已经取得官方授权。

## 运行边界

- 用户配置存储在现有设置文件的 `external_tools/ipop_path` 键。
- 有效用户配置优先；未配置时可检查用户手动放置的 `tools/windows-x64/ipop/IPOP.EXE`。
- NetConsole 不下载、复制、解压、修改、嵌入或后台获取 IPOP。
- IPOP 由 `DesktopActionService` 经 Electron 白名单本机动作以 `shell=False` 启动；NetConsole 不传递凭据、不等待或接管其生命周期，主程序退出不会结束它。

## 发布边界

PyInstaller Backend、Electron 内部版、客户版和工程师版均不得包含 `IPOP.EXE` 或 `tools/windows-x64/ipop` 目录。构建脚本仅白名单复制 `fping` 和 `iperf3`；最终目录或 ZIP 检测到 IPOP 时会中止构建，但不会删除开发机或用户磁盘上的文件。
