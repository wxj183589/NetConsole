# NetConsole v1.5.17

状态：本地 Full 交付候选（未 Push、未 Tag、未创建 GitHub Release）。

## 本次内容

- 完成 Backend、Renderer、Electron、存储、设备网络、任务中心和 Windows 发布链路的全代码复审。
- 修复生命周期审计脚本默认读取真实开发数据根的 P1 数据边界问题：现在必须显式提供 `--data-root`。
- 当前产品版本统一为 `1.5.17`；历史 v1.5.16 记录保留。
- 生成 Full Installer 与 Full Portable，均绑定本地提交 `d687ba575b27fdbc11a2013b9afc467c1bb4d07c`。

## 验证边界

Renderer/Electron 生产构建、PyInstaller Backend 构建、版本一致性、依赖/许可证检查和包级 smoke 已通过。真实 Windows 安装/升级/卸载、Windows 10 20H2、真实设备、真实 GUI 和 8 小时长稳未执行，继续保持 PARTIAL/NOT VERIFIED。

## 使用注意

Installer 和 Portable 不包含生产数据库、现场 RAR、SSH 凭据、`.git`、node_modules 或 Python venv。Portable 默认使用程序目录 `data`，测试时必须使用独立数据根；不要与安装版同时指向同一数据库。
