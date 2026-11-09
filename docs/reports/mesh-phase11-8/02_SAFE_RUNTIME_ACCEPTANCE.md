# 隔离运行验收

运行根 `D:\study\NetConsole-Workspace\test-data\NetConsole\mesh-phase11-8-run-001`，使用仓库启动器支持的隔离测试目录；与任务书示例 `%TEMP%` 不同。Electron 日志记录 `ELECTRON_STORAGE_MODE=isolated_test` 和上述实际数据根，后端记录设备库位于隔离根。

目标 catalog、profile、parsed 数据库和启动所需 devices.db 用 SQLite Backup API 从开发数据只读连接建立快照，目标完整性检查通过。仅复制目标 raw、站点和 MR 元数据；未复制整个数据根或站点。隔离数据库中的历史绝对路径已重定位到隔离根。原始 gzip 大小 2,892,510 字节，复制前及本轮复核 SHA256 均为 `f53990d5448f297ea8cbc6901d87132fcf3f616c61149feaa4e875829a3b0fc7`。

日志证明隔离启动和目标数据读取；尚未完成所有源数据库、WAL、SHM 的前后状态证据及全路径写入审计，不能将原始数据完全未变化作为已证明结论。
