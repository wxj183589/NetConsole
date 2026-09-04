# 开发与本地 smoke 脚本

本目录提供 Mesh-Link 导出基准和本地 fping v5 检查等开发辅助脚本，不是产品运行入口，也不保存正式报告或运行数据库。

`run_fping_v5_smoke.py` 是一次性的本地 smoke 检查入口；输出默认写入 `.local/runtime/smoke/fping_v5/`，可通过 `--output-dir` 指定其他临时目录。它不属于 pytest 测试收集，也不应改名为 `test_*.py`。

`tray_site_sync_e2e.ps1` 启动 standalone Electron 并交互式记录 Windows Tray Site Sync 人工验收。它默认使用 `D:\NetConsoleData-dev`，证据写入 `NetConsole-Workspace/diagnostic/`，不会复制或修改生产数据；步骤说明见 [TRAY_SITE_SYNC_E2E](../../docs/testing/TRAY_SITE_SYNC_E2E.md)。

运行前使用项目虚拟环境并准备脱敏样本；输出写入临时目录或 `.local/`。修改后执行脚本对应的定向测试，确认不依赖当前工作目录。
