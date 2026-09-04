# Tray Site Sync 真实验收记录

本文档用于 Windows 上的人工验收。它验证的是同一个 Backend current site 在 Electron Renderer、系统设置和 Windows Tray 中的真实收敛，不是只检查菜单显示文字。

## 环境

验收前填写以下信息：

| 项目 | 实际值 |
| --- | --- |
| 测试日期/时间 | 2026-09-04 |
| 测试人 | 待填写 |
| Windows 环境 | Windows Electron GUI |
| Repo 根目录 | `D:\study\NetConsole-Workspace\worktrees\tray-site-sync` |
| Branch / Commit | `codex-A/tray-site-sync` / `e3fd5d2d` |
| Backend 运行模式 | `desktop-development` |
| DataRoot | `D:\study\NetConsole-Workspace\test-data\NetConsole\tray-site-sync-gui-20260904-180531` |
| 局点 A / site_id | 杭州地铁10号线 / `hz10` |
| 局点 B / site_id | 宁波地铁12号线 / `nb12` |
| 局点 C / site_id | 宁波地铁10号线 / `nb10` |
| 证据目录 | `D:\study\NetConsole-Workspace\diagnostic\tray-site-sync-live-20260904-180531-retry` |

禁止使用 `D:\NetConsoleData` 做本验收的写入测试。证据目录只保存日志、截图和验收记录，不提交到仓库。

推荐使用 standalone Electron，避免 Vite wrapper 在旧 Electron 退出时结束开发服务，影响真实 `app.relaunch()` 验证：

```powershell
Set-Location <repo-root>\scripts\dev
pwsh -File .\tray_site_sync_e2e.ps1 -BuildRenderer
```

如果 Renderer `dist` 已经由当前 Commit 构建，可省略 `-BuildRenderer`。脚本会启动 `pnpm run start`，并在证据目录生成 `launcher.stdout.log`、`launcher.stderr.log` 和可填写的 `TRAY_SITE_SYNC_E2E_RESULT.md`。脚本结束时不会自动杀掉 NetConsole 进程；验收人员应从 Tray 选择“退出 NetConsole”。

## 启动诊断检查

主窗口 Renderer 进入 interactive 后，Electron 日志和 development stdout 应出现一条包含以下内容的记录：

```text
[TraySync] backend_site_id=<id> renderer_site_id=<id> tray_site_id=<id>
```

三个值都是 `site_id`，不是局点名称、数组位置或缓存值：

- `backend_site_id`：Main 在诊断时重新读取 Backend `/api/v1/sites/active`；
- `renderer_site_id`：Renderer 在报告 interactive 时读取的当前 Backend site snapshot；
- `tray_site_id`：Main 用于重建当前 Tray 菜单的 site snapshot。

任意值为空都不能判定 PASS，应在“实际结果”中记录为空的原因。Backend Offline 时，Tray 必须显示 `Backend Offline`，不能显示上一次局点。

## 人工步骤、预期结果与实际记录

每一步都填写“实际结果”和“失败截图位置”。截图使用证据目录中的相对路径，例如 `step-05-settings-switch-failed.png`；没有失败截图填写“无”。

| 步骤 | 操作 | 预期结果 | 实际结果填写位置 | 失败截图位置 |
| --- | --- | --- | --- | --- |
| 1. Electron 启动 | 启动 Electron，确认主窗口和 Tray 图标出现。 | 主窗口打开，Tray 图标出现，无启动致命错误。 | `TRAY_SITE_SYNC_E2E_RESULT.md` 步骤 1；记录时间。 | 待填写：`step-01-*.png` / 无 |
| 2. Backend Online | 等待并确认 Backend Online。 | Backend 在线；若 Backend 未启动，Tray 进入 Offline，不显示旧局点。 | 记录 Backend 状态和 stdout/log 路径。 | 待填写：`step-02-*.png` / 无 |
| 3. 当前局点读取 | 记录 Backend 当前 `site_id`，核对 Renderer 顶部和系统设置。 | 三处为同一 `site_id`；名称只用于展示。 | 记录 `backend_site_id=`、Renderer `site_id=`、名称。 | 待填写：`step-03-*.png` / 无 |
| 4. Tray 显示 | 右键 Tray，查看“当前局点”和快速切换列表。 | 当前名称正确；checked 项由当前 `site_id` 决定，与列表排序无关。 | 记录 Tray 名称、checked `site_id`、列表顺序。 | 待填写：`step-04-*.png` / 无 |
| 5. Renderer 切换局点 | 在系统设置将局点 A 切换为 B。 | 先 Backend 成功，再更新 Renderer；成功后顶部和系统设置为 B，失败保持 A。 | 记录 A/B `site_id`、成功/失败、切换时间。 | 待填写：`step-05-*.png` / 无 |
| 6. Tray 同步 | 重新打开 Tray 菜单检查当前局点和 checked。 | Tray 当前名称和 checked 与 Backend/Renderer 都为 B。 | 记录 Tray 当前 `site_id` 和 checked。 | 待填写：`step-06-*.png` / 无 |
| 7. Tray 切换局点 | 在 Tray 快速切换将 B 切换为 C；可额外快速点击 A → B → C。 | 点击传递 `site_id`；失败保持旧 checked；多次点击最终收敛到最后成功的 C。 | 记录点击序列、Backend 最终 `site_id`、切换结果。 | 待填写：`step-07-*.png` / 无 |
| 8. Renderer 同步 | 回到 Renderer 页面检查顶部和系统设置。 | Renderer 顶部、系统设置与 Backend/Tray 都为 C。 | 记录两个 Renderer 位置的 `site_id` 和名称。 | 待填写：`step-08-*.png` / 无 |
| 9. Tray 重启软件 | 点击 Tray →“重启软件”。观察旧 Electron 进程退出、新进程启动。 | 是真实应用重启（`app.relaunch()` + 当前进程退出），不是 Renderer `reload`；窗口和 Tray 重新出现。 | 记录旧/新进程时间、日志中的启动记录。 | 待填写：`step-09-*.png` / 无 |
| 10. 重启后状态恢复 | 等待 Backend Online，重新读取当前局点并核对 Renderer、系统设置和 Tray。 | 重启后从 Backend 重新读取；四方 `site_id` 都为重启前成功的 C，Tray checked 正确。 | 记录重启后 `[TraySync]` 三个 ID 和四处 UI 结果。 | 待填写：`step-10-*.png` / 无 |

## 失败记录规则

出现以下任一情况，步骤标记为 `FAIL` 或 `BLOCKED`，不得只改截图中的显示文字后判定通过：

- Backend、Renderer、系统设置和 Tray 的 `site_id` 不一致；
- Backend Offline 时 Tray 仍展示旧局点或允许使用旧列表切换；
- 切换失败后出现 Renderer 已切换、Tray 已 checked 但 Backend 未切换；
- A → B → C 快速点击后最终三方不是 C；
- 局点列表排序变化导致 checked 跟随数组位置变化；
- “重启软件”只刷新窗口，没有旧 Electron 进程退出和新进程启动证据；
- 重启后相信旧缓存，未重新读取 Backend，或四方状态不一致。

失败时至少保存：

1. 失败步骤的 Tray/Renderer 截图；
2. 失败前后 `[TraySync]` 日志行；
3. Backend Online/切换请求结果和发生时间；
4. 证据目录路径。

日志和截图应脱敏，不要保存 session token、密码或其他凭据。

## 验收结论

只有步骤 1–10 全部 PASS，且启动/重启日志和截图可追溯，才能填写：

```text
结论：PASS
backend_site_id=____
renderer_site_id=____
tray_site_id=____
重启前 site_id=____
重启后 site_id=____
```

源码 typecheck、Vitest 或 Electron smoke 只能作为自动化辅助，不能替代本文件的 Windows 真实右键菜单、Renderer 页面和跨进程重启验收。

## GUI Acceptance Result

- 日期：2026-09-04
- 环境：Windows Electron GUI
- 启动方式：`pnpm run start`
- Electron Main PID：`64152`
- Backend PID：`82620`
- Renderer PID：`73620`
- 结果：`PASS`
- 启动验证：PASS
- Tray 创建：PASS（`ELECTRON_TRAY_READY`）
- Backend current site 同步：PASS
- Renderer current site 同步：PASS
- Tray current site 同步：PASS
- 初始诊断：`backend_site_id=hz10`、`renderer_site_id=hz10`、`tray_site_id=hz10`
- 当前局点：杭州地铁10号线
- 人工验收：通过

本次验收使用 Workspace 隔离测试数据根，未使用 `D:\NetConsoleData`、`D:\NetConsoleData-dev` 或 `D:\study\fping`；未修改功能代码。
