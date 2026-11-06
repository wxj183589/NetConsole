# Ground Unattended V2 Windows 验收（2026-11-07）

## 1. 结论和环境

原生 DPI：**BLOCKED**；完整 Electron 生命周期：**BLOCKED**（自动契约和源码 smoke PASS）；本轮安装包：**BLOCKED**。这些缺口使整体保持 PASS_WITH_LIMITATIONS。

证据 `.local/ground-v2-final-audit/windows-environment.json`：时间 `2026-11-07T04:39:47+08:00`，Windows NT 10.0.26200，系统 DPI=96（100%），屏幕 2560×1440，workarea 2560×1392。当前确为 Windows，但没有完成系统设置切换后的六配置原生交互。未擅自修改用户系统 DPI、安装目录或机器级数据指针。

## 2. DPI 和浏览器证据

| 分辨率 | DPI | 原生验收 | Playwright |
| --- | --- | --- | --- |
| 1920×1080 | 100% | BLOCKED | 2 项 PASS |
| 1920×1080 | 125% | BLOCKED | 2 项 PASS |
| 1920×1080 | 150% | BLOCKED | 2 项 PASS |
| 2560×1440 | 100% | BLOCKED | 2 项 PASS |
| 2560×1440 | 125% | BLOCKED | 2 项 PASS |
| 2560×1440 | 150% | BLOCKED | 2 项 PASS |

浏览器最终 12 passed，见 `browser-visual-fixed.log`。执行的是十个真实 Vue 页面，HTTP mock 提供数据；覆盖导航、双 IP MR 抽屉→Quick、默认参数、启停、canvas、Syslog/Timeline 服务端筛选分页、footer 可见和外层无溢出。不能据此声称真实 Backend GUI 端到端、原生 DPI、字体清晰或任务栏交互验收。

已人工查看最终截图：1920×1080@125% 的 `ground-quick-stopped.png` 和 2560×1440@125% 的 `ground-syslog.png`，位于 `browser-visual-fixed/` 对应测试子目录。图表双轴、终态停止禁用、表格内滚动及分页可见正常。首轮 6 项 ECharts grid 兼容警告失败，局部 options 修复后 12 项通过；不修改共享图表基础设施。

重放命令（cwd=`apps/desktop_renderer`）：

```powershell
pnpm exec playwright test -c playwright.config.ts ground-unattended.visual.spec.ts --project='1920x1080@100%' --project='1920x1080@125%' --project='1920x1080@150%' --project='2560x1440@100%' --project='2560x1440@125%' --project='2560x1440@150%' --workers=1 --output=../../.local/ground-v2-final-audit/browser-visual-fixed
```

原生补验需隔离 Windows 桌面：建立唯一 `Workspace\test-data\NetConsole\<run-id>` 并显式测试模式，使用模拟库存/服务；按系统“显示设置”逐次切分辨率和缩放，必要时注销后重登，再启动 Electron。对六配置逐页记录截图/操作结果，重点 125%，检查任务栏、弹窗、抽屉、图表 resize、表格双向滚动、字体和十页功能。恢复原系统设置后核对环境。浏览器截图只作辅助证据。

## 3. Electron 生命周期

| 项目 | 结果 | 边界 |
| --- | --- | --- |
| Main/Preload 自动契约 | PASS | 完整 38 文件/306 项，typecheck/build；本轮无 Main 源码改动 |
| 源码正常启动 | PASS | Vite/backend ready；TraySync backend/renderer/tray site=demo |
| 源码正常退出 | PASS | SHUTDOWN_STARTED→DOWNLOADS_STOPPED→BACKEND_STOPPED→EXIT_REQUESTED→EXIT_RETURNED |
| Renderer 崩溃不影响采集 | BLOCKED | 契约测试不能代替真实强杀与后端连续采样观察 |
| Backend 异常退出/恢复 | BLOCKED | 组件恢复有回归，未强杀实际 Backend 验证恢复 |
| Windows 重启/托盘长运行 | BLOCKED | 未重启主机、未做托盘长时观察 |
| 实际 fping 孤儿/端口/重复 Backend | BLOCKED | Soak 无 fping/Backend 子进程；smoke 不证明故障后的完整释放 |

证据 `electron-lifecycle-tests.log`、`electron-smoke.log` 及 FULL Gate。前者因 pnpm 参数转发实际执行完整套件，不能描述为只执行了三个定向文件。

重放（cwd=`apps/desktop_electron`，必须沿用隔离测试运行环境）：

```powershell
pnpm exec vitest run
pnpm exec tsc --noEmit -p tsconfig.json
node scripts/build.mjs
node scripts/dev.mjs --smoke
```

原生补验先记录本轮进程 PID、command line、端口和启动时间，只对本轮自有 PID 注入故障。分别关闭 Renderer、终止 Backend、停止无人值守、退出 Electron；观察原版恢复/停止策略，不预设 Backend 一定自动重启。记录采样空窗为 UNKNOWN/DEGRADED、无假离线；Quick 恢复为 INTERRUPTED；raw/Spool 可恢复。核对自有子进程/端口释放和无重复 Backend。Windows 重启仅在隔离机进行，重登后核验运行恢复和停机空窗不累计离线。

## 4. 安装包阻塞及可复现流程

本轮没有生成、安装或卸载 V2 安装包。缺少独立 VM/专用安装环境，不能覆盖现有安装或改写 HKLM 数据指针；当前 112 文件尚未提交，本轮又禁止 commit，与 [构建发布规范](../release/BUILD_AND_RELEASE.md) 的 `packaged_dirty=false` 和各层 commit 一致要求冲突。不使用旧 v1.5.11 包冒充当前候选。

后续需用户授权独立候选构建和隔离 VM，完成以下步骤：

1. 固化本轮源码 commit，确认干净工作树，完成最终 FULL Gate，记录版本、build、SHA、edition。
2. 使用 canonical `scripts/build/package_local.ps1`；其实际参数仅 Edition（full/customer/both/preflight）及 NoOpenOutput，不使用不存在的临时发布参数。遵循规范将正式候选留在 Workspace release，禁止覆盖现有候选。
3. 可先执行以下既有 preflight；真正构建需后续授权，**以下本轮未执行**：

   ```powershell
   .\scripts\build\package_local.ps1 -Edition preflight -NoOpenOutput
   # 授权后在隔离构建环境：
   .\scripts\build\package_local.ps1 -Edition both -NoOpenOutput
   ```

4. 校验安装器 SHA-256、manifest、Frontend/Backend/Installer commit 和 dirty=false。隔离 VM 禁止映射生产数据盘；安装目录使用 `D:\study\NetConsole-Workspace\temp\installer-test\<run-id>`，数据目录使用 `D:\study\NetConsole-Workspace\test-data\NetConsole\<run-id>`，记录本 VM 指针，不改宿主指针。
5. 分别验证 Full/Customer 安装、启动、Backend readiness、十页资源、配置/日志路径、模拟收集、正常退出、重开、卸载。核验普通卸载保留隔离业务数据和数据指针；不测试删除用户数据选项。
6. 保存本轮截图、安装日志、进程/端口及隔离 SQLite/raw 完整性记录。清理仅限确认归属的自有 VM/制品，不清理任何原有安装或数据。

## 5. 关联结论

代码和自动化结论见[主报告](./ground-unattended-v2-final-stability-audit-2026-11-07.md)。这些原生缺口是验收限制，不能将自动化 PASS 提升为 Windows 现场长期稳定 PASS。
