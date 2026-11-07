# NetConsole v1.5.12 发布报告

日期：2026-11-08
目标版本：`1.5.12`
功能分支：`codex-A/ground-unattended-v2-20261107`
目标分支：`main`

## 发布状态

当前状态：**PENDING_PACKAGE_AND_MERGE**。

R3.2.1 的时间轴/历史归档功能已完成自动化验收，版本源已更新为 `v1.5.12`。正式 Full/Customer 安装包、安装包 SHA256/Manifest、main 合并后的最终回归和 Windows GUI 安装验收在本报告生成时尚未完成，不能将本报告视为已发布证明。

## 版本事实源

- Python：`src/netconsole/core/version.py` -> `v1.5.12`
- Electron：`apps/desktop_electron/package.json` -> `1.5.12`
- Electron 产品名：`NetConsole v1.5.12 by wxj`
- Renderer HTML 标题：`NetConsole v1.5.12 by wxj`
- 更新日志：`docs/CHANGELOG.md` 的 `v1.5.12 - 2026-11-08`

## R3.2.1 验收

结论：**PASS_WITH_LIMITATIONS**。Python 归档/历史/API 定向测试 98 passed、1 warning；Ground 全模块 396 passed、1 skipped、1 warning；Renderer 定向测试 55 passed；最终 `local_gate --mode auto` 通过（Python 5526 passed、2 skipped，Renderer 198 files/1397 passed，Electron 38 files/306 passed，架构、主契约、Ruff、文档门禁通过）。真实设备、真实业务数据根、跨机器 Windows 安装和现场长稳未执行。

## 制品记录

正式制品目录：`D:\study\NetConsole-Workspace\release\v1.5.12`。

| 项目 | 结果 |
| --- | --- |
| Full installer | PENDING |
| Customer installer | PENDING |
| `.exe.release.json` | PENDING |
| `SHA256SUMS.txt` / manifest | PENDING |
| Package smoke | PENDING |
| Windows GUI install/upgrade/uninstall | PENDING |

构建必须从 clean、已推送且与 upstream 一致的最终 main 提交开始，自动构建的 `real_windows_install_status` 保持 `PENDING`，不得用自动化结果替代人工安装验收。

## 合并与分支

- PR #105：发布前需更新并重新检查状态与门禁。
- main 合并：PENDING。
- 本地功能分支回收：PENDING，只有在确认已合并、clean 且无活动 worktree 后执行。

## 数据影响与风险

本轮仅使用隔离测试 fixture；未读取、复制或修改 `D:\NetConsoleData`、`D:\NetConsoleData-dev`，未连接真实设备。剩余风险是正式安装器/升级卸载、跨机器 GUI、长时 Backend/Electron 生命周期和现场设备互操作未验收。
