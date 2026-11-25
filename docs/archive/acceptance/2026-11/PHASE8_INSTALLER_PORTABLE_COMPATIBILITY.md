# Phase 8 安装版与便携版兼容性

状态：PARTIAL

静态实现检查确认安装版和便携版共用后端与 Renderer，安装器默认保留 DataRoot，便携版通过标记文件和 `portable-data-root.json` 选择数据根。DataRoot 迁移是复制优先，源目录保留，目标必须为空，失败不切换当前根。

自动化覆盖 DataRoot 路径校验、迁移 staging、SQLite 完整性和 manifest 校验。真实 Windows 安装、覆盖升级、普通卸载、重新安装恢复数据、Portable ZIP 冷启动、程序目录移动和端口/子进程回收：NOT VERIFIED。Phase 7.1 原始安装包未被覆盖。
