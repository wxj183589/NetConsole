---
name: netconsole-release-packaging-skill
description: "NetConsole Python 依赖分层/constraints、PyInstaller Backend、Electron Builder、NSIS、安装数据根、Full/Customer 版本、package smoke、版本元数据、SBOM/许可证或 Windows 发布门禁任务时使用。普通业务功能、SQLite 业务迁移或单个本地报告导出不使用本 Skill。"
---

# 目标

维护可复现、可追溯、数据安全的 Windows Electron 发布链，使最终安装包身份、内层 Backend/Renderer、功能模板和实际 Git 提交一致。

# 触发与反例

触发示例：

- “修改 requirements/constraints、PyInstaller 或 Electron 打包。”
- “调整 NSIS 数据根、安装/升级/卸载或 package smoke。”
- “构建 Full/Customer 包、SBOM、许可证或发布制品。”

不应触发：

- “实现一个普通业务页面或 Service。”
- “修改业务 SQLite schema 或导出一个 XLSX 报告。”

# 输入与输出

- 输入：目标 edition、最终 Git 提交、依赖/构建/安装变更、数据根策略、自动门禁与人工验收范围。
- 输出：构建脚本/元数据/安装器/门禁的最小修改、制品身份与哈希、数据安全和验证报告。
- 允许修改生产代码：允许，限构建、安装、发布配置和必要 runtime bootstrap；不得借打包任务改业务行为或删除用户数据。

# 开始前读取

- `docs/release/BUILD_AND_RELEASE.md`、`docs/release/FULL_AND_CUSTOMER_PACKAGING.md`、`docs/release/PACKAGED_FEATURE_MATRIX.md`。
- `docs/storage/DATA_LAYOUT.md`、`docs/storage/README.md`、`docs/architecture/DESKTOP.md`。
- `requirements-*.txt`、`constraints.txt`、`pyproject.toml`、`src/netconsole/core/version.py`、`src/netconsole/core/feature_registry.py`。
- `scripts/build/`、`apps/desktop_electron/package.json`、`apps/desktop_electron/scripts/`、`apps/desktop_electron/build/installer-data-root.nsh`。
- `config/profiles/features/full.json`、`config/profiles/features/customer.json` 和相关 build/package tests。

# 当前架构事实

- 正式桌面产品只有 Electron + 唯一 Vue Renderer + PyInstaller `NetConsoleBackend.exe`；客户机不依赖源码、系统 Python、Node、pnpm、Git 或 Go。
- Full 和 Customer 复用同一源码，区别来自经门禁校验的功能模板和发布元数据，不复制客户版工程。
- 业务数据根由 `HKLM\Software\NetConsole\DataRoot` 持久化；无合法持久根时停止启动，不回退 LocalAppData、用户目录、仓库、程序目录或 Temp。
- 自动 package smoke 只使用 `RuntimeMode.TEST` 和 `D:\study\NetConsole-Workspace\test-data\NetConsole\<run-id>`；不得读取机器级指针或真实数据根。
- Windows Server 2012 x64 只有 `USER_FIELD_CONFIRMED` 现场事实，自动化 VM 为 `AUTOMATION_NOT_RECORDED`；正式 GUI 安装状态仍独立记录。

# 工作流程

本领域变更属于 L4；编码前先组合 `netconsole-change-review-skill`，列出构建、运行时、数据根、Feature/edition、制品和 CI 消费者及合并后回归。

1. 先分类为依赖、Backend 冻结、Electron 构建、NSIS、edition、package smoke、许可证/SBOM 或发布操作，明确最终制品和不可变事实源。
2. 依赖按 runtime/test/build/dev 分层并由 `constraints.txt` 精确锁定；不随意升级，不把构建/测试工具复制进运行时。
3. 正式候选只从已提交、工作区 clean、HEAD 已推送且与 upstream 一致的提交构建；构建前冻结 Git/版本/UTC/dirty 身份，所有层复用同一快照。
4. 构建顺序保持 Renderer -> PyInstaller Backend -> Electron Main/Preload/native helper -> electron-builder/NSIS -> package smoke/final gate；任一门失败停止发布。
5. NSIS 分离程序目录和数据根，候选目录先做零写入识别，再做可写/重命名/SQLite/空间验证；迁移或初始化成功后才更新 HKLM 指针。
6. Full/Customer 模板通过 Registry status、parent、`requires`、`delivery_requires`、internal/development 泄漏门禁；维护密码只在构建进程内存在，不进入仓库、日志或明文制品。
7. 对最终 setup.exe、内层 Backend/Frontend commit、dirty、PE/NSIS 身份、manifest、策略 hash、SHA-256、Notice/SBOM 和包内 Qt 残留执行实际制品检查。
8. 将源码测试、unpacked/package smoke、NSIS 构建、干净安装/升级/卸载、真实设备和跨电脑验收分别记录；自动成功只写 `PENDING` 的人工状态。
9. 日常开发以 `python -m scripts.quality.local_gate --mode auto` 为主要验证入口；只有 release/package 路径受影响时才由 FULL Gate 追加 Package Smoke。GitHub Actions 仅作可选远端复核。

# 禁止模式与不变量

- 不从脏工作区、未推送提交或与 upstream 不一致的 HEAD 生成正式候选，不覆盖同名旧制品。
- 不跳过失败门禁、不伪造 package/GUI/设备验证，不把 `package:dir` 当正式 NSIS 结果。
- 不删除、移动或回退用户数据根、bootstrap 或 HKLM 指针；普通卸载保留业务数据和指针。
- 不引入 Qt/PySide/PyQt/QFluentWidgets 运行时，不把 `.venv` 或构建机工具当客户依赖。
- 不把维护密码、Token、凭据、真实数据、绝对敏感路径或生产数据库写入日志、元数据或制品。

# 验证与失败报告

- 依变更运行 build/runtime dependency guard、相关 pytest、Renderer tests/build、Electron tests/typecheck/build 和适用 Go tests。
- 正式打包使用当前仓库入口 `scripts/build/package_windows.ps1` 或 `apps/desktop_electron` 的 edition 命令，并保留实际 package smoke/final gate 输出。
- 数据根测试覆盖不存在、空、含普通文件、合法旧根、冲突、损坏 manifest、迁移失败回滚和卸载保留，全部只用隔离目标。
- 报告最终 Git/版本/edition、制品名称/大小/SHA-256、内层身份、门禁、数据根影响、推送状态和未执行的 Windows GUI/跨电脑/真实设备验收。

# 相关 Skills

- L4 影响审计：`netconsole-change-review-skill`。
- Electron runtime：`netconsole-electron-desktop-skill`。
- DataRoot/SQLite：`netconsole-data-safety-skill`。
- Feature/文档同步：`netconsole-project-docs-skill`。
