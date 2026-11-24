# NetConsole 设备管理界面优化与功能整合验收报告

日期：2026-11-24
版本：v1.5.19
分支：`codex-A/device-management-ui-polish-20261124`
产品 Commit：`f8956b7a9bdd6f672853cd132456d9118b825cc5`
产品 Push：PASS，已推送至 `github/codex-A/device-management-ui-polish-20261124`

## 任务状态

`PARTIAL`

代码、测试、版本同步以及隔离环境下的正式 Installer/Portable 构建已完成；真实设备、GUI 视觉和真实 Windows 安装验收未在本轮完成。

## 已完成内容

- 批量设置厂商、设备大类、设备子类：支持混合值显示、独立字段修改、分类级联、逐设备成功/失败和原因；后端按设备保存点处理，保留 UUID、连接配置、分组、Site 和历史关联。
- 右键菜单收敛为详情、建设阶段、当前工作状态、编辑、复制设备、内置控制台、外部终端、删除；移除原有复制当前单元格、设备名、主/备用地址、系统名、站点、整行和设备信息入口。
- 操作列增加内置控制台快捷入口；设备管理页与控制台路由登记为 singleton/cache，避免切换时销毁会话或重复打开相同工作区，显式关闭仍会关闭。
- 合并“测试连接”和“健康检查”：按设备先连接后健康检查，逐设备展示结果、健康指标、超时和取消状态；该短生命周期操作不写入 Job Center、通知或历史任务记录，保留原有健康检查能力。
- 删除手动“查询”：关键字、分组、厂商、分类、状态、高级筛选和排序统一使用防抖自动刷新，并保留请求代次保护、分页归一化和排序状态。
- 隐藏左侧导航滚动条但保留滚轮、触摸、键盘和可达性滚动能力。
- 更新 v1.5.19 版本身份、Electron/Renderer 标题、双份 changelog 和发布文档。

## 验证结果

| 项目 | 状态 | 证据 |
| --- | --- | --- |
| Python API/Repository/版本测试 | PASS | `128 passed, 17 warnings`（质量门禁 Python 直接套件） |
| Renderer 全量测试 | PASS | 219 files，1596 tests |
| Electron 测试 | PASS | 41 files，324 tests |
| Renderer 生产构建 | PASS | `pnpm run build`，3466 modules transformed |
| Electron typecheck | PASS | `pnpm run typecheck` |
| Ruff | PASS | changed Python files，All checks passed |
| `git diff --check` | PASS | 无 diff 空白错误 |
| 本地质量门禁 | PARTIAL | root-layout/change-impact/ruff/python/renderer/diff PASS；workspace-layout FAIL，原因见下 |
| Full Installer | PASS | 隔离 Worktree 执行 `package_windows.ps1 -Edition full -NoOpenOutput`；NSIS、包级 smoke、release metadata 和 SHA-256 复核通过 |
| Full Portable | PASS | 隔离 Worktree 执行 `pnpm run package:portable`，随后执行 `node scripts/package-smoke.mjs`；构建和包级 smoke 通过 |
| 真实设备连接/健康检查 | NOT_VERIFIED | 未连接现场设备，未将模拟或本地测试结果当作真实验收 |
| 1920x1080/2K GUI 视觉与横向溢出 | NOT_VERIFIED | 本轮未执行人工 Electron 截图验收 |
| Windows 安装/升级/卸载 | NOT_VERIFIED | 已生成 Installer，但本轮未执行真实安装、升级和卸载 |

打包链路已实际完成 Renderer、Electron、PyInstaller Backend、fping/iPerf3 资源、Backend bundle、NSIS Installer 和 Portable ZIP 检查。正式制品位于 `D:\study\NetConsole-Workspace\release\v1.5.19\build-ee2aaa43`。

## 安全与数据影响

```text
PRODUCTION_DATA_MODIFIED=0
DATABASES_REMOVED=0
MAINTENANCE_AUTHORIZED=NO
DEVSTATUS_UPDATED=0
```

- 未读取、复制、同步、覆盖或修改 `D:\NetConsoleData`、`D:\NetConsoleData-dev`。
- 未创建完整数据库、Site 或真实数据根副本。
- 未修改 `D:\study\AGENTS.md`、`D:\study\.git` 或其他一级项目。
- 未更新 NetConsole-DevStatus；本任务明确要求不更新 DevStatus。
- `D:\study\NetConsole-Workspace\NetConsole\build` 是本任务开始前已存在的历史顶层目录；依据项目安全规则未删除、移动或清理。

## 后续动作

后续只剩真实设备连接、人工 GUI 视觉验收以及 Windows 安装/升级/卸载验收；这些不由本次构建 Smoke 代替。本报告不把未执行的现场验收视为已完成。

## v1.5.19 打包治理与正式客户端构建

日期：2026-11-24

### 状态字段

```text
BUILD_GATE_ROOT_CAUSE=PASS
SAFE_BUILD_ENVIRONMENT=PASS
INSTALLER_BUILD=PASS
PORTABLE_BUILD=PASS
INSTALLER_PACKAGE_SMOKE=PASS
PORTABLE_PACKAGE_SMOKE=PASS
VERSION_CONTRACT=PASS
COMMIT_IDENTITY=PASS
SHA256_VERIFICATION=PASS
RELEASE_ARTIFACTS=PASS
TEMP_WORKTREE_CLEANUP=PASS
REPORT_UPDATE=PASS
REMOTE_PUSH=PASS
```

### 根因与安全构建环境

原始仓库的 `D:\study\NetConsole-Workspace\NetConsole\build` 是历史遗留、未跟踪且被 `.gitignore` 忽略的 setuptools 输出，共 683 个文件、13625491 bytes。`scripts/build/build_release.py` 在 package prepare 前会拒绝项目根 `build`，因此原始工作树不能直接打包。该目录未被删除、移动或覆盖。

本轮使用独立 Git Worktree 构建：

- Installer：`D:\study\NetConsole-Workspace\worktrees\v1.5.19-installer`
- Portable：`D:\study\NetConsole-Workspace\worktrees\v1.5.19-portable`
- 两个 Worktree 均通过 `python -m scripts.check_workspace_layout`。
- 构建来源 Commit：`ee2aaa433926dfde57cb50e898d4dcba56aca8af`（短 SHA `ee2aaa43`）；功能实现 Commit 仍为 `f8956b7a9bdd6f672853cd132456d9118b825cc5`。

### 构建与包级验收

- Full Installer：`scripts\build\package_windows.ps1 -Edition full -NoOpenOutput`；Web 219 files/1596 tests、Electron 41 files/324 tests、Renderer、PyInstaller、NSIS 和 Installer packaged smoke 均 PASS。
- Portable：`pnpm run package:portable`；Renderer、主进程、PyInstaller、Electron unpacked packaging 和独立 `node scripts/package-smoke.mjs` 均 PASS。
- 初次 Portable 执行仅因隔离 Worktree 尚未安装 Renderer 依赖和 Electron 分发目录停止；按锁定依赖补齐后从原命令重跑成功，未修改源码、原始仓库或真实数据。
- `VERSION_CONSISTENCY=PASS (1.5.19)`，前后端 Commit、Health build ID、changelog 链均一致。

### 正式制品

输出目录：`D:\study\NetConsole-Workspace\release\v1.5.19\build-ee2aaa43`

| 制品 | 大小（bytes） | SHA-256 |
| --- | ---: | --- |
| `NetConsole-Full-1.5.19.0-ee2aaa43-x64-setup.exe` | 158551975 | `731b475894a1289cfa5e49324dc9b3400d6bb6699646ac77885a74b403056fb5` |
| `NetConsole-1.5.19-portable.zip` | 216038606 | `f661bb240509334adb242424a832bb8ef823c3cec15c5dd9cfe3ca43c167d506` |

同目录包含 Installer `.release.json`、`SHA256SUMS.txt`、`PACKAGE_MANIFEST.json` 和 `BUILD_REPORT.md`。

### 数据与验收边界

```text
PRODUCTION_DATA_MODIFIED=0
DEV_REAL_DATA_MODIFIED=0
DATABASES_REMOVED=0
DEVSTATUS_UPDATED=0
REAL_WINDOWS_INSTALL=NOT_VERIFIED
GUI_ACCEPTANCE=NOT_VERIFIED
```

原始仓库历史 `build` 复核值保持为 683 files、13625491 bytes，目录 LastWriteTime 为 `2026-11-23T05:19:45.8514674+08:00`。真实 Windows 安装、升级、卸载和人工 GUI 验收仍须另行执行；构建 Smoke 不等同于这些验收。
