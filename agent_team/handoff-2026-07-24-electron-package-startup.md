# Electron 正式包启动修复交接

- 日期：2026-07-24
- 分支：main
- 修改前修订：4f9e5fa8
- 功能提交修订：e80ac079
- 推送结果：按用户要求暂不推送

## 修改内容

- Electron Builder 新增 `build.win.executableName=NetConsole`，正式目录包固定生成 `dist/electron/win-unpacked/NetConsole.exe`。
- `package-smoke.mjs` 改为从当前 `package.json` 解析 Windows EXE 名称；配置缺失时立即报告构建契约错误。
- 冻结后的 `NetConsoleBackend.exe` 无参数运行时不再进入源码 Electron 开发链，改为写运行日志、输出错误、显示 Windows 原生消息框并返回退出码 `2`；`--electron-backend` 和 smoke 环境变量保持原行为。
- 将现有品牌 ICO 重建为包含最高 256px 的多分辨率图标，解决 electron-builder 拒绝 64px 图标的问题；未改变品牌设计。
- 同步构建发布文档与 Python/Electron 定向测试。

## 测试结果

- `.venv/Scripts/python.exe -m pytest tests/test_launcher.py tests/test_project_docs_layout.py -q`：33 passed。
- `.venv/Scripts/python.exe -m ruff check src/netconsole/entrypoint.py tests/test_launcher.py`：通过。
- `pnpm install --frozen-lockfile`：依赖已是锁定状态。
- `pnpm test`：21 个测试文件、145 个测试通过。
- `pnpm run typecheck`：通过。
- `pnpm smoke:package`：通过；真实启动目录包，Backend 握手、`/api/health`、资源/合规检查和退出回收通过。
- `pnpm package`：通过；生成 `dist/electron/NetConsole-1.4.2-x64-setup.exe`。
- 安装包构建后的 `node scripts/package-smoke.mjs`：再次通过，结束后无 `NetConsole` 或 `NetConsoleBackend` 残留进程。

## 影响与遗留

- 未修改数据库、数据目录、导出任务或 Job Center 行为。
- 尚未执行安装器人工点击验收；开始菜单/桌面快捷方式、实际安装/卸载、直接双击受管 Backend 的消息框外观仍需人工确认。
- 清理前的未跟踪旧构建产物移动到系统临时目录 `NetConsole-Codex-package-rebuild-6dc4752ccb174bfe9712324dd3004d4f`，可恢复且未触碰用户数据。
- 工作区仍有其他会话的未提交修改，本任务提交未包含这些文件。
