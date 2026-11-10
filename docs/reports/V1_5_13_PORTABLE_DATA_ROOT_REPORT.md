# v1.5.13 免安装版数据根补充验收

日期：2026-11-10  
产品代码提交：`06a2114d557360858c730c324fb1d330a4f87078`  
分支：`codex-A/v1-5-13-full-portable`

## 结论

本轮补充要求已在代码、单元测试、Backend 构建和免安装包级 smoke 中闭环。免安装版默认数据根、用户自定义数据根、C 盘允许、失败时不回退、同根排他锁和无 Demo 首次初始化均已实现。

正式安装器仍保留原有 clean/upstream 保护。本轮未 Push、未 Merge、未创建正式 Release，也未对 `D:\NetConsoleData` 或 `D:\NetConsoleData-dev` 做写入验收。

## 实现证据

- 便携模式由程序目录旁的 `portable.mode` 明确选择；默认根是 `<程序实际目录>\data`，不依赖当前工作目录。
- `portable-data-root.json` 仅保存用户明确选择的绝对路径；配置损坏、默认根不可用或自定义根不可用时 fail-closed，不创建替代数据库、不自动迁移旧根。
- 默认根不可写时 Electron 弹出目录选择；取消后退出。便携程序目录中的配置保存失败也不会静默切换。
- Backend 只在真正空的便携根创建元数据和必要目录；首次业务初始化使用 `default` 空局点，不创建 Demo 局点、设备或模拟数据。
- C 盘不再被数据根校验拒绝；安装器和界面仍提示优先使用非系统盘。
- `runtime/locks/netconsole-backend.lock` 继续作为同一数据根的排他锁，阻止多个实例同时写入。
- 安装版与免安装版复用同一 `PathResolver`、Schema、启动元数据和 Backend。

## 自动化验证

| 项目 | 结果 | 证据 |
| --- | --- | --- |
| Electron 数据根定向测试 | PASS | `vitest`: 4 files / 56 tests |
| Electron 全量测试 | PASS | `vitest`: 38 files / 313 tests（最终代码前的同一功能集；最终变更后 packaging 定向 27/27） |
| Electron 类型检查 | PASS | `pnpm typecheck` |
| Python 数据根/SiteStorage/Schema/API | PASS | 130 passed，含便携空根、无 Demo、C 盘和更新日志 API |
| Renderer 性能回归 | PASS | `tracksideSeriesColors.test.ts`: 5 passed；全量 Gate 首次有 1 次阈值抖动，单测重跑通过 |
| Backend PyInstaller | PASS | `APP_VERSION=v1.5.13`、`BUILD_DIRTY=false`、依赖闭包 71 distributions、工具/NOTICE/SBOM 校验通过 |
| 免安装目录构建 | PASS | Electron Builder `win-unpacked`，x64，包含 Backend、Renderer、fping、iperf3 |
| 免安装 ZIP | PASS | `D:\study\NetConsole-Workspace\worktrees\v1-5-13-full-portable\dist\electron\NetConsole-1.5.13-portable.zip` |
| 包级 smoke | PASS | 冻结 Backend、迁移/list HTTP 200、Ground Unattended、MESH 幂等、Worker 中文协议、无 Qt、NOTICE/SBOM |

## 免安装制品

制品由代码提交 `06a2114d557360858c730c324fb1d330a4f87078` 构建：

```text
文件：NetConsole-1.5.13-portable.zip
大小：215,694,564 bytes
SHA-256：BAE693E60785EEA28078A79E323D1C6FCC2DC2AFDE8DD5FE5160CF024D93F6C7
目录：dist/electron/win-unpacked
主程序：NetConsole.exe
便携标记：portable.mode = NetConsole portable mode
```

包级 smoke 输出确认 Backend、Frontend、Electron 和 self-check 使用同一提交，`PACKAGED_DIRTY=false`，版本一致为 `1.5.13`。

## Full Gate 与未完成项

本地 Full Gate 的结果为 `PARTIAL`，不是本轮数据根定向测试失败：Renderer 全量首次出现 1 个性能阈值抖动（单测复跑通过）；Python 全量为 5626 passed / 37 failed / 2 skipped，失败集中在既有 Production Database Maintenance、Storage Validation、Mesh/架构审计和文档治理门禁，上一轮已记录基线为 5625 passed / 38 failed / 2 skipped。另有既有 docs README/临时报告命名、架构 guard 未分类项和候选 worktree 缺少本地 `.venv` 等门禁问题；本轮没有把它们改写成通过。

以下验收未完成或未执行：

- 正式安装器构建：`NOT_RUN`。当前分支未设置 upstream；正式入口明确要求已提交且已推送并与 upstream 对齐，本轮按要求不 Push，未绕过保护。
- 真实安装、升级、卸载和安装版 GUI：`NOT_RUN`。
- 免安装真实 Electron GUI、截图、版本替换和跨目录移动后的人工启动：`NOT_RUN`；已完成包级 smoke 和代码/单测验证。
- `D:\NetConsoleData` 真实数据根：未读取、未写入；D 盘路径兼容性以隔离 fixture、路径解析和包级测试验证。
- 现场设备或现场局点验收：`NOT_AVAILABLE`。

## 数据影响

未复制、移动、覆盖、删除或迁移任何 Production/Dev Authority 数据。构建和 smoke 只使用 `D:\study\NetConsole-Workspace\test-data\NetConsole` 下的隔离临时根；构建输出位于候选 worktree 的可再生 `dist`，不进入正式 `release`。
