# NetConsole v1.5.12 发布报告

日期：2026-11-08；Agent：codex-A。

## 发布结论

**PASS_WITH_LIMITATIONS / WINDOWS_GUI_INSTALL_PENDING**。

R3.2.1 功能、更新日志和版本升级已通过 PR #105 合并至 main。合并后完整 Release Gate、Full/Customer 正式构建、包内 Electron/冻结 Backend 启停、HTTP 通信、NSIS 身份检查和 SHA256 校验通过。两个安装包均来自已推送的 clean main bd9f931b7d946804eff6027cc93651f9472051df，packaged_dirty=false。

**隔离 Windows GUI 安装、升级和卸载尚未通过验收。** 当前主机未发现 Windows Sandbox、Hyper-V VM 命令/服务或本任务提供的独立 Windows 测试机。没有运行会改写本机机器级 DataRoot 指针的 NSIS 安装流程；不能把解包与 package smoke 视为 GUI 安装成功。制品 manifest 的 real_windows_install_status / server_installation_status 均保留 PENDING，published=false。未创建 GitHub Release、未上传制品。

## R3.2.1 最终功能验收

| 项目 | 验收结果 |
| --- | --- |
| 时间轴 | 独立事件查询，按真实 event_at 排序；device_time、received_at、run_date 独立传递和展示 |
| 启停 | 每次启动/停止保留独立事件和 session 时间戳，不用归档时间覆盖 |
| 每日归档 | 同运行日期复用归档 ID/ZIP；同日多个 session 合并并分别保留起止时间 |
| 完整性与恢复 | 压缩、校验、幂等、失败重试、重启恢复和跨日边界由隔离 Python 回归覆盖 |
| 选择与删除 | 行 Checkbox、全选/取消、选中数量、单条/批量确认、取消删除、刷新和失败反馈通过测试 |
| 数据保护 | 删除仅作用于指定归档包及元数据，原始事件、库存和当前任务保持独立 |
| 页面验收 | Playwright 3/3：十页导航、时间轴筛选分页、每日归档选择/取消/确认删除与独立时间字段 |

详细模型、修改文件和边界见 [R3.2.1 验收报告](ground-unattended-v2-r3.2.1-timeline-archive-correction.md)。Playwright 使用隔离页面/API fixture；源码 Electron 和稳定性证据沿用 [R3.2 集成报告](ground-unattended-v2-r3.2-final-integration-audit.md) 已记载范围，不冒充安装态 GUI 验收。

## 更新日志与版本

- 产品唯一版本源：src/netconsole/core/version.py → v1.5.12。
- Electron：apps/desktop_electron/package.json → 1.5.12，产品名同步。
- Renderer：apps/desktop_renderer/index.html 标题同步；运行时版本/关于页读取产品版本和构建 metadata。内部 workspace package.json 仍为 0.1.0，它不是产品版本源，不需要改锁文件。
- docs/CHANGELOG.md 与打包内 src/netconsole/docs/changelog.md 同步新增 v1.5.12 - 2026-11-08，保留 v1.5.11 及更早记录；package smoke 验证历史顺序。
- 安装器 ProductVersion=1.5.12；manifest FileVersion=1.5.12.0，Build Number=0；Windows Explorer 读取外层 EXE 版本字符串为 1.5.12。
- 活动版本入口已逐项检查旧版本，未替换历史记录/fixture。制品 health、Backend/Frontend/Installer commit 和日志身份一致。

## Release Gate

功能和发布改动按 **L4** 验收；合并后报告因 base=head 自动显示 L1，但显式 --mode full 实际执行全部完整套件，没有降级门禁。

| 门禁 | 合并后 main 实际结果 |
| --- | --- |
| Python 全量 | **5530 passed, 2 skipped, 34 warnings**，1967.13 秒 |
| Renderer 全量 | **198 files / 1397 passed**；vue-tsc、production build PASS |
| Electron 全量 | **38 files / 306 passed**；typecheck、main/preload build PASS |
| 架构 | **12/12 guards PASS** |
| Main contract smoke | **12 passed** |
| Ruff / 文档 | 全量 Ruff PASS；文档路径 **22 passed** |
| 路径 / Git | root-layout、workspace-layout、git diff --check PASS |
| Full / Customer 包级门禁 | 两版 Electron、冻结 Backend、HTTP、Feature Profile、版本与退出握手 PASS |

Ground 定向和共享消费者结果见 R3.2.1 报告。Go Agent 业务源码未改，本次未单独运行全量 Go 套件；打包链已构建所需 native helper。按用户要求未重复 24 小时稳定性或原生 DPI 专项。

保留失败证据：先前全量为 1 failed / 5529 passed / 2 skipped，原因是 AC 目标富化回归测试遗留工作线程；修复只隔离该测试网络启动，保留业务断言及全局停止检查。顺序复验、分支完整门禁和合并后完整门禁通过。main 首次复验还遇到临时诊断测试文件被 pytest 收集；移除该临时入口后重新完整执行，以上 5530/2 为最终结果，未删除产品测试或降低标准。

## 构建与制品

入口：scripts/build/package_local.ps1 -Edition both -NoOpenOutput，沿用 pnpm、PyInstaller、electron-builder/NSIS。构建时间：2026-11-08 09:56:20 至 10:01:48（Asia/Shanghai），327.619 秒。

正式制品目录：D:\study\NetConsole-Workspace\release\v1.5.12\build-0-bd9f931b

| Edition | 文件 | 字节数 | SHA256 |
| --- | --- | ---: | --- |
| Full | NetConsole-Full-1.5.12.0-bd9f931b-x64-setup.exe | 158046957 | 958486ad24d7c408243bcc35d52419acbcb300a107aa10ca5f107dfff9bf79e4 |
| Customer | NetConsole-Customer-1.5.12.0-bd9f931b-x64-setup.exe | 158047161 | 5cd751d62d53098a4db4ef77e89738a0680ec2c4e298e0080442a2323f29b127 |

同目录包含两个 .exe.release.json、SHA256SUMS.txt、BUILD_SUMMARY.json 和 BUILD_SUMMARY.md。交付收口重新计算 EXE 大小/哈希/PE 版本，与清单一致；未覆盖 v1.5.11。

两版 Installer/Backend/Frontend commit 均为 bd9f931b7d946804eff6027cc93651f9472051df，packaged_dirty=false、NSIS-3 Unicode、Feature Profile/edition 相符。Gate 对最终 setup.exe 解包并核验内嵌 manifest、安装策略源码哈希及提示文本。Package smoke 在 Workspace 唯一 TEST 根运行冻结 Backend/Electron，完成设备迁移/HTTP 200、Full Ground HTTP 200、Customer 功能策略、MESH、Worker 中文协议、NOTICE/SBOM、无 Qt 残留及正常退出，随后清理测试根。包内不含真实业务数据或测试数据库。

## Git 与本地分支回收

- 功能/版本 commit：c8ba6d6c0c0cb23bac6b6c2e00db56ed4ecf66c1。
- 评审修复：d8c24002（持久化与关联边界）、cd0b1243（页面切换/取消删除和浏览器验收）、68cb100d（测试线程隔离）。
- [PR #105](https://github.com/wxj183589/NetConsole/pull/105)：MERGED，2026-11-08 09:19:38（Asia/Shanghai）；8 个 GitHub 检查全部 SUCCESS，未绕过保护或强推。
- Merge commit / 最终产品 main HEAD：bd9f931b7d946804eff6027cc93651f9472051df；本地 main 与 github/main 一致后执行全量回归和双版本构建。
- Annotated tag v1.5.12 指向该产品/构建 commit，已推送；tag 注明 GUI 安装仍待验收。
- 原本地功能分支 codex-A/ground-unattended-v2-20261107 已按安全 -d 回收，提交全部进入 main。无本任务遗留 worktree；远端功能分支保留。
- 本报告收口使用 codex-A/v1512-release-report 文档分支。报告合并后的 main HEAD、文档 PR 和分支回收终态记录在 DevStatus 与最终交付信息；制品/tag 固定于 bd9f931b，不改写为后续文档 commit。

## 证据、数据与剩余问题

证据根：D:\study\NetConsole-Workspace\reports\tests\ground-r3.2-final-20261108

- v1512-merged-main-full-gate.json/.md/.log：最终 main 完整门禁。
- v1512-premerge-fixed-full-gate.*、v1512-review-full-gate-failed.*：修复前后证据。
- v1512-playwright-accepted.log、archive-screenshot/：浏览器验收和归档/时间轴截图。
- v1512-main-package-both.log：构建摘要；详细日志 NetConsole/dist/package-logs/package-20261108-095620.log。

仅使用隔离 fixture、TEST 根和回环请求；未读取、复制或修改 D:\NetConsoleData / D:\NetConsoleData-dev，未连接真实设备。未触碰独立 fping、NetConsole-Next 或其它开发分支/工作树。DevStatus 原有未提交历史增量和未推送 Next 提交独立保留，不随本轮发布推送。

未完成：独立 Windows/VM 的 GUI 安装、升级/修复/卸载、四类数据目录选择和注册表指针验收，以及跨机器/Server 安装与现场设备互操作。下一步按 [正式构建与安装验收规范](../release/BUILD_AND_RELEASE.md) 在独立 Windows 环境验证后，才能更新 GUI 安装状态；当前不能宣称全面发布验收 PASS。
