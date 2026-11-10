# Portable Build Report

## 构建

- 命令：`pnpm run package:portable`
- 版本：`1.5.13`
- 构建源码提交：`5294f1ea7e1a1829e38d77c167f5e2d088ed0d99`
- `BUILD_DIRTY=false`
- `BUILD_TIME_UTC=2026-11-10T17:27:42Z`
- 构建结果：PASS

制品：

- 文件名：`NetConsole-1.5.13-portable.zip`
- Release 候选路径：`D:\study\NetConsole-Workspace\release\v1.5.13\build-20261111-012953-5294f1ea\NetConsole-1.5.13-portable.zip`
- 构建输出路径：`D:\study\NetConsole-Workspace\NetConsole\dist\electron\NetConsole-1.5.13-portable.zip`
- 大小：`215712396` bytes
- SHA256：`9B74C04FE738E6D3F847C6A616F4354331D859AD77F637FD678F1D86CB30DD51`

Release 候选和 dist 制品大小、SHA256 一致。

## 包内容与运行验证

- 包含 `portable.mode`，未包含 `portable-data-root.json`（新包的正确状态）。
- 未发现 `test-data`、`.venv`、`.git`、`.pytest_cache` 或 `node_modules`。
- 版本扫描确认 Electron、Backend、Renderer 和 changelog 均为 v1.5.13。
- 解压后的 `NetConsole.exe` 在没有 `NETCONSOLE_DATA_ROOT` 覆盖时退出码为 0，并在程序目录创建 `data`。
- 默认运行未生成 Demo/示例业务数据；仅创建运行所需的空配置、数据库和默认空局点结构。
- `portable-data-root.json` 的自定义数据根恢复、不可用根 fail-closed 和 C 盘策略由定向 Electron/Python 测试覆盖。

Portable 包级 smoke 结果见 [DUAL_PACKAGE_SMOKE.md](DUAL_PACKAGE_SMOKE.md)。
