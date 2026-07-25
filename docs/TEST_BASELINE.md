# 测试基线

NetConsole 开发默认先跑与改动直接相关的定向测试，所有待合并提交完成并完成代码审阅后，再运行全量测试。这样可以更快定位模块问题，同时保留最终集成回归门槛。

开发机处于低干扰或限 CPU 阶段时，只运行能够直接证明当前切片的单文件/单模块测试、静态检查和 `git diff --check`；不得让多个并行任务重复执行全量 pytest、完整 Vitest、生产构建或 Package Smoke。必要的全量门延后到用户解除资源限制后的最终代码组合，延后项必须在交付记录中明确列出，不能写成已通过。

## 数据隔离

- pytest 在收集测试模块前创建独立的临时 `NETCONSOLE_DATA_ROOT`。
- 测试不得读取或写入 `D:\NetConsoleData`、正式局点数据库、真实会话和报告；必须使用 `D:\NetConsoleTestData\<run-id>`。
- `RuntimeMode.TEST` 未显式给出测试根时必须失败，且测试配置解析不得读取 `HKLM\Software\NetConsole\DataRoot`。
- PyInstaller Backend 的发布 smoke、release contract 与最终 Electron Package Smoke 都必须自行在 `D:\NetConsoleTestData\<run-id>` 创建并清理唯一根，显式传入 `RuntimeMode.TEST` 和 `isolated_test`；不得复用构建机的业务数据根或系统 Temp。
- 需要特定数据布局时使用 `tmp_path`、测试 fixture 或 Fake 服务；不得依赖当前机器已有 Task、Session 或设备数量。
- 独立工作树的虚拟环境若未执行 editable 安装，运行会启动 Python 子进程的测试时应显式设置 `PYTHONPATH=src`；不能把 `ModuleNotFoundError: netconsole` 误判为 Worker 业务失败。

## 开发阶段

每个模块至少运行：

1. 新增或修改的后端 Service、Repository、Router 测试。
2. 直接受影响的 Application Service、永久 Adapter 或历史行为契约测试；不得重新引入 Qt 测试运行时。
3. 对应 Vue 组件、API client 或 Store 的 Vitest。
4. 前端 `pnpm build`，以及适用的 Ruff、Go 或文档链接检查。

`pnpm build` 属于受影响前端切片完成后的集成门。开发机明确处于低干扰模式时，先运行对应 Vitest 文件和 `vue-tsc --noEmit`（如本切片需要），将完整生产构建记录为待补，不以牺牲用户前台工作负载换取重复验证。

Electron 改动还需在 `apps/desktop_electron` 运行 `pnpm test`、`pnpm run typecheck` 和 `pnpm run build:main`；触及启动链、preload 或 Vue runtime adapter 时运行 `pnpm smoke:dev`。工作区、窗口生命周期或托盘改动还需运行 `pnpm smoke:workspace-tray`，覆盖附加工作区窗口、主窗口隐藏后 Backend 保持 ready、恢复窗口和明确退出回收。该冒烟覆盖源码图形环境，不替代 Windows 安装包、签名、升级、通知区域交互、图标缩放或目标系统实机验收。

触及本机 Codex/浏览器调试链时，额外运行 `pnpm exec node scripts/dev.mjs --codex --smoke`，并确认 `127.0.0.1:5173`、`127.0.0.1:8000` 和受管子进程均已回收。开发状态接口必须覆盖：显式开关、回环来源、Session 鉴权、路径/令牌脱敏，以及生产运行时路由不存在。Playwright 浏览器/Electron E2E 只有在对应脚本和断言实际落地后才能计入门禁；普通 Vitest、API TestClient 和启动 smoke 不等同于 E2E。

测试断言应验证必要能力和业务契约，不硬编码会随正常扩展变化的全局任务总数或路由总数。

近期高风险功能的定向验收至少覆盖：

- AC/FIT-AP：动作计划/确认/执行/审计、`confirm_token` 不进入页面和日志、AC resource key 互斥、当前 AC 范围的 OmniPeek 预览与 `.nam` 导出；
- 车内通信：无快照/过期/双端离线仍可按有效点表启动，点表缺失/无效/无可执行节点必须拒绝，AC 查询失败后继续 SSH/Ping/跨 TC；
- 设备文件：SSH 成功但 SFTP 子系统不可用、主机密钥确认后恢复原连接意图、最近 20 条活动优先、24 小时 `.part` 后台清理边界；
- Job Center：fatal Worker 协议错误立即失败并有界终止不主动退出的进程，Runtime/资源锁/临时文件释放且终态唯一；文本完整性 schema v2 覆盖当前、历史、未知和正常来源，列表与详情一致，列表查询不扫描 100000 条事件历史，列表刷新不覆盖详情。`PARTIAL_SUCCESS/WARNING` 的列表颜色和顶部警告计数仍是已知缺口，不得在本轮报告为通过；
- 配置采集：两条勾选快照、跨设备左右选择、空/相同/不同文件、裁剪、差异导航和导出；
- 轨道交通基础资料：设备来源只读预览必须只读取“车站”分组的 `devices.station`，覆盖空 station、不使用设备名/系统名、200 条以上不截断、停车场/车辆段特殊节点、MAIN 默认值且不覆盖明确结构、多轨道设施与中心里程往返、四工作表/旧模板兼容、真实 Electron XLSX 保存与 openpyxl 打开、导入预览不写库、双向及端点区间生成、稳定生成标识、人工区间保护、过期区间默认保留、AP 统计忽略模板值、`validate`/`changes` 统一保存和 revision 冲突；
- MESH/Online MR/Agent：旧日志/缺 Peer Name、按来源独立报告、参数快照、正常/partial/failed 包、LOCAL/AGENT 停止与恢复、真实 fping 与 TCP connect probe 区分。
- 地面无人值守：默认/修改/跨午夜窗口、结构化正线排除、AC stale 宽限、同 AP 静止恢复、多目标动态分片、小时轮转、每日首轮覆盖优先级、可复现随机队列、人工 MR 互斥、ZIP 成功后清理/失败保留和重启恢复；真实 AC/MR、长时 fping、托盘隐藏与进程残留仍为人工门禁。
- 正式包跨电脑交付：生产 Feature 必要集合、`client_package=false` 不作为运行时拒绝、internal/development 仍关闭；v4 完整迁移包无需密码、无 `payload.enc`、ZIP 内 SQLite 可复读真实 SSH/SNMP/隧道凭据、导入后不设 `needs_reentry`、manifest/checksum/SQLite 校验失败零发布和替换失败回滚；脱敏分享包秘密清洗与 `needs_reentry`、密码留空保留/显式清除、本机桌面显式 reveal/关闭清理、Server/远端/未认证拒绝、空凭据创建 Job 前阻断；ASCII JSON bytes 不依赖 CP936/locale、受管 Backend 中文启动失败以 ASCII JSON Unicode 转义逐字恢复、strict UTF-8 汉字任意 chunk/1-byte 分块、非法协议不落库、Backend `text_integrity`、冻结 Worker、统一 Git HEAD/UTC/dirty 构建元数据、`win-unpacked/NetConsole.exe` 受管 Backend 的 REST/任务日志中文探针，以及 WebSocket 中文探针和环境自检。

Windows 图形人工验收必须单独记录在[正式包功能矩阵](PACKAGED_FEATURE_MATRIX.md)：NSIS 安装/卸载、程序目录与数据目录分离、系统盘拒绝、现有根复用、含无冲突普通文件目录复用、必需路径冲突拒绝、升级/修复/迁移和卸载保留数据、全新普通用户、空 AppData、无开发工具、中文路径、跨电脑完整包无需密码恢复凭据、脱敏包凭据重新录入、本机显式查看已保存密码、真实或仿真 H3C SSH、中文任务标题/消息/progress/log/finished。未执行的项目标为 `PENDING`，不得由单元测试或 package smoke 推断为通过。

安装器数据根探测还必须覆盖：目录枚举早于任何写入探测且探测后不再按非空拒绝、Windows 空目录不会被 `*.*` 误判、尚不存在的 D/E 盘路径由 `GetFullPathNameW` 规范化但不创建、空根直接使用所选路径且不追加 `NetConsoleData`、注册表发布前生成可解析且根一致的 manifest、损坏 manifest 不覆盖、含普通文件目录保留原文件并成功初始化、六个必需目录路径和 manifest 的真实类型冲突、含 manifest/SQLite/采集文件的既有根、`GetDriveTypeW` 使用 `E:\` 根路径、C 盘安装器临时目录、不可写目录、旧固定探测残留、唯一名称冲突、失败清理、中文路径、尾随反斜杠、非法路径和系统盘拒绝、取消/失败回滚和重复安装。规范化测试必须实际编译并运行 Unicode NSIS，而非只做源码断言。验证需比较所选目录及既有业务文件在探测和失败前后的存在状态、内容哈希、大小和修改时间，并扫描 `.netconsole-install-probe-*` 残留；禁止用删除、改名或迁移真实数据根换取通过。

最终安装器门禁必须直接针对本轮唯一名称的 `setup.exe`，不能只检查源码、`win-unpacked` 或 Backend/Web metadata。自动检查至少验证：构建前固定名和唯一名制品均不存在；最终文件名包含当前 Git short commit；PE Installer 身份与 `HEAD` 一致；外层为 `NSIS-3 Unicode`；从最终 EXE 提取的 installer manifest 与数据根 include 等于本轮输入；允许普通文件的新文案存在，旧“非空且不是已识别数据根 / 请选择空目录 / 不会创建嵌套目录”文案均不存在；Backend/Frontend commit 与 Installer commit 一致且非 dirty；最终 EXE 两次 SHA-256 一致。发布清单中的 `real_windows_install_status` 在真实隔离 Windows 验收前必须保持 `PENDING`。

Netmiko 当前既有定向基线为 `20 passed, 2 failed`，失败位于 `tests/test_netmiko_connection.py:280` 与 `tests/test_netmiko_connection.py:301`。该两项不属于本轮发布生命周期修复范围，交付时必须如实列出，不能用其他测试结果覆盖。

## 合并前

所有并行分支进入同一集成分支后运行：

1. 完整 pytest。
2. 完整前端测试与构建。
3. Ruff 与文档链接检查。
4. Agent 代码受影响时运行 Go 测试和对应构建检查。
5. Electron-only 最终组合运行 [架构一致性审计](ARCHITECTURE_COMPLIANCE.md)定义的九个架构门：分层边界、禁用依赖、直接 SQL、设备命令、UI 业务逻辑、移除功能、运行路径、孤儿模块和迁移映射。

全量测试只在合并后的真实代码组合上作为最终门槛；单个并行任务不重复执行全量套件。

架构 Guard 必须在 Qt 删除和非 Qt 全量测试之后再次执行。启发式命中需要人工分类和证据；不得用目录级忽略、删除测试或无到期时间的例外换取通过。P0/P1 架构问题为零是 Electron-only 发布门。

## 架构九门

统一入口为：

```powershell
.\.venv\Scripts\python.exe scripts\architecture\run_all.py
```

九个门也可按改动范围定向运行：

```text
check_architecture_boundaries.py
check_forbidden_imports.py
check_direct_sql_access.py
check_device_command_hardcoding.py
check_ui_business_logic.py
check_removed_features.py
check_runtime_paths.py
check_orphan_modules.py
check_migration_map.py
```

开发阶段优先运行直接受影响的单门；统一入口只在架构配置发生交叉变化或最终组合门执行。当前基线与精确例外见 [E10B 归档](archive/migrations/electron-only/2026-07-18-E10B-architecture-guards-and-remediation.md)。

## 主题验证门

主题改动至少定向覆盖：

- Vue：`light / dark / auto` 解析、系统设置失败回落、侧栏与 Shell Token、Element Plus 映射、ECharts 重绘订阅；
- Electron：初始背景色、只接受 `resolvedTheme: light|dark` 的单向严格 IPC、受信 Renderer 校验和运行期背景更新；
- Guard：侧栏基础色、页面状态色、Element Plus 基础变量和图表系列色均来自 Design Token；
- 人工：Electron 中的浅色、深色、跟随系统，以及 1280×720、1920×1080、2560×1440 和 100%/125%/150% 缩放。

自动测试只能证明 Token、事件和 IPC 契约，不能替代 Electron 视觉验收。当前全局主题代码和页面状态色语义 Token 已接入，`WEB_STATUS_COLOR_TOKEN` 例外为 0；Guard 已收窄普通文本 Token 的误报并有单元测试。最终 Electron 多尺寸、多缩放和 Windows 跟随系统视觉验收仍为 `PENDING`。
