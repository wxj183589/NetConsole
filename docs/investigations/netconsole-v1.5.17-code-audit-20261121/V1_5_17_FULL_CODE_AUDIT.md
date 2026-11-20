# NetConsole v1.5.17 全代码复审

日期：2026-11-21  
基线：`github/main@0b8fa04cf3d634703ae231f4ecf9a211c64b1d51`  
分支：`codex/netconsole-v1.5.17-maintenance-20261121`

## 复审范围

本轮使用干净 worktree 对产品源码、构建脚本、配置和资源做了静态覆盖审查。按文件类型统计：Backend `663` 个 Python 文件、Desktop Renderer `487` 个 TypeScript/Vue 文件、Electron `38` 个 TypeScript/JavaScript 文件、构建脚本 `21` 个、配置 `19` 个、资源 `39` 个，共 `1267` 个产品相关文件。统计命令为：

```powershell
Get-ChildItem src/netconsole -Recurse -File -Include *.py
Get-ChildItem apps/desktop_renderer/src -Recurse -File | Where Extension -in .ts,.vue
Get-ChildItem apps/desktop_electron/src -Recurse -File -Include *.ts,*.mjs,*.cjs
```

覆盖 Backend API Router/DTO、Application Service、Repository/SQLite、任务和调度、H3C/SSH/Telnet、文件与报表、Ground Unattended、Site/Storage；Renderer 页面、Store、API、生命周期和图表；Electron Main/Preload/IPC、Backend 管理、Portable 数据根、日志和窗口生命周期；以及 PyInstaller、Electron Builder、Installer、Portable 和依赖清单。

## 方法与证据

- 读取项目 AGENTS、Workspace layout、发布文档和 Full-only 交付约束。
- 运行仓库根布局、目录 README、Change Impact、禁止导入、退役功能、运行路径、直接 SQL、动态图表稳定性和设备命令硬编码检查；均为 PASS。
- 对 `src` 与 `scripts` 执行 Python `compileall`；PASS。
- 对修改的 Python/Ground Unattended 范围执行 Ruff；PASS。
- 运行定向 pytest：版本身份、Heartbeat 状态/常驻监督、Syslog 人工 JOIN、Raw lifecycle、Electron runtime，共 `102 passed`。
- 未运行 Python/Renderer/Electron 全量套件、全量 Architecture/L3 Gate、8 小时长稳、真实 GUI、真实设备或 Windows 10 实机验收。

## 重点维护项复核

上一轮 15 项维护的实现入口仍存在，Syslog 的检查/JOIN/EXIT 路径由 Ground Unattended Service、Router 和定向测试共同覆盖；未发现新增写配置命令或跨 Loghost 影响的证据。Heartbeat 默认关闭、列车选择、AP/站点关联、MR 动态监控、V5 兼容、站序和存储管理均完成源码/契约复核，但真实环境证据不足的六项仍保持 PARTIAL，不能由本次静态审查升级为 PASS。

## 结论

除已修复的维护脚本数据边界问题外，本轮未确认新的 P0/P1 业务缺陷。发布仍属于本地候选交付：真实设备、真实 GUI、Win10 20H2 和 8 小时长稳验收未完成；本地安装包/Portable/ZIP 的结果必须以后续实际构建和包级冒烟证据为准。
