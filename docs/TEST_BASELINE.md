# 测试基线

NetConsole 开发默认先跑与改动直接相关的定向测试，所有待合并提交完成并完成代码审阅后，再运行全量测试。这样可以更快定位模块问题，同时保留最终集成回归门槛。

开发机处于低干扰或限 CPU 阶段时，只运行能够直接证明当前切片的单文件/单模块测试、静态检查和 `git diff --check`；不得让多个并行任务重复执行全量 pytest、完整 Vitest、生产构建或 Package Smoke。必要的全量门延后到用户解除资源限制后的最终代码组合，延后项必须在交付记录中明确列出，不能写成已通过。

## 数据隔离

- pytest 在收集测试模块前创建独立的临时 `NETCONSOLE_DATA_ROOT`。
- 测试不得读取或写入开发态 `.local/data`、正式局点数据库、真实会话和报告。
- 需要特定数据布局时使用 `tmp_path`、测试 fixture 或 Fake 服务；不得依赖当前机器已有 Task、Session 或设备数量。
- 独立工作树的虚拟环境若未执行 editable 安装，运行会启动 Python 子进程的测试时应显式设置 `PYTHONPATH=src`；不能把 `ModuleNotFoundError: netconsole` 误判为 Worker 业务失败。

## 开发阶段

每个模块至少运行：

1. 新增或修改的后端 Service、Repository、Router 测试。
2. 直接受影响的 Application Service、永久 Adapter 或历史行为契约测试；不得重新引入 Qt 测试运行时。
3. 对应 Vue 组件、API client 或 Store 的 Vitest。
4. 前端 `pnpm build`，以及适用的 Ruff、Go 或文档链接检查。

`pnpm build` 属于受影响前端切片完成后的集成门。开发机明确处于低干扰模式时，先运行对应 Vitest 文件和 `vue-tsc --noEmit`（如本切片需要），将完整生产构建记录为待补，不以牺牲用户前台工作负载换取重复验证。

Electron 改动还需在 `apps/desktop_electron` 运行 `pnpm test`、`pnpm run typecheck` 和 `pnpm run build:main`；触及启动链、preload 或 Vue runtime adapter 时运行 `pnpm smoke:dev`。该冒烟覆盖源码图形环境，不替代 Windows 安装包、签名、升级或目标系统实机验收。

触及本机 Codex/浏览器调试链时，额外运行 `pnpm exec node scripts/dev.mjs --codex --smoke`，并确认 `127.0.0.1:5173`、`127.0.0.1:8000` 和受管子进程均已回收。开发状态接口必须覆盖：显式开关、回环来源、Session 鉴权、路径/令牌脱敏，以及生产运行时路由不存在。Playwright 浏览器/Electron E2E 只有在对应脚本和断言实际落地后才能计入门禁；普通 Vitest、API TestClient 和启动 smoke 不等同于 E2E。

测试断言应验证必要能力和业务契约，不硬编码会随正常扩展变化的全局任务总数或路由总数。

近期高风险功能的定向验收至少覆盖：

- AC/FIT-AP：动作计划/确认/执行/审计、`confirm_token` 不进入页面和日志、AC resource key 互斥、当前 AC 范围的 OmniPeek 预览与 `.nam` 导出；
- 车内通信：无快照/过期/双端离线仍可按有效点表启动，点表缺失/无效/无可执行节点必须拒绝，AC 查询失败后继续 SSH/Ping/跨 TC；
- 设备文件：SSH 成功但 SFTP 子系统不可用、主机密钥确认后恢复原连接意图、最近 20 条活动优先、24 小时 `.part` 后台清理边界；
- Job Center：调度 `COMPLETED` 与业务 `PARTIAL_SUCCESS/WARNING` 分离，列表、详情、筛选、顶部计数和页面 toast 一致；
- 配置采集：两条勾选快照、跨设备左右选择、空/相同/不同文件、裁剪、差异导航和导出；
- 轨道交通基础资料：设备来源只读预览必须只读取“车站”分组的 `devices.station`，覆盖空 station、不使用设备名/系统名、200 条以上不截断、停车场/车辆段特殊节点、模板 XLSX 预览/导出、来源 stale、人工字段不被来源确认覆盖、`validate`/`changes` 统一保存和 revision 冲突；
- MESH/Online MR/Agent：旧日志/缺 Peer Name、按来源独立报告、参数快照、正常/partial/failed 包、LOCAL/AGENT 停止与恢复、真实 fping 与 TCP connect probe 区分。

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
