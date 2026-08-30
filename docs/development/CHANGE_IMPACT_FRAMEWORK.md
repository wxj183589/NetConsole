# Change Impact Framework

## 目标

NetConsole 的回归验证以“修改了哪个契约、哪些消费者依赖该契约”为入口，不再默认“只改 A 就只测 A”。本框架只约束开发、评审、CI 和合并验证，不改变生产业务行为。

机器可读事实源是 [`config/architecture/change_impact_matrix.json`](../../config/architecture/change_impact_matrix.json)，本文解释长期规则。路径、消费者或验证命令变化时，先更新 Registry，再同步本文和对应 Skill，禁止在多个 Markdown 中维护互相冲突的矩阵。

## 历史回归模式

2026-07-01 以来的主线提交显示，跨模块回归主要来自以下工程模式，而不是单个领域孤立失效：

1. `NcDataTable`、动态图时间轴、Workspace 等 Renderer 共享组件修改后，只验证了当前页面。
2. Task/Job、Worker 协议、Export/Artifact 修改后，业务终态、取消、部分成功或文件落盘消费者没有一起验证。
3. AP Identity、MAC 归一化、revision 或缓存修改后，MESH、Ground、Online/Vehicle MR、Wireless、Trackside 等消费者接管阶段不一致。
4. `api/client.ts` 的请求合并、超时、取消、错误分类或缓存修改影响所有 Renderer API。
5. Feature Registry/Snapshot 修改影响导航、FeatureGate、Full/Customer 交付配置和正式包。
6. PathResolver、DataRoot、SQLite schema/upgrade 修改影响所有局点数据与后台任务。
7. Electron Main/Preload/IPC/Backend 生命周期修改影响全部窗口和本机能力。
8. 长生命周期 worktree 反复合并 `main`，把不属于原任务的共享冲突和其他线程修改带入业务分支。

因此，历史 one-off regression 只能作为证据来源；长期保护应沉淀为共享契约测试、消费者测试和稳定主线 smoke。

## 风险等级

| 等级 | 定义 | 典型范围 | 最低验证 |
| --- | --- | --- | --- |
| L1 LOCAL | 局部展示或不改变公共契约的实现 | 单页面 CSS、文案、Tooltip、只读格式 | 当前模块定向测试、lint/typecheck、`git diff --check` |
| L2 DOMAIN | 单一领域内部业务逻辑 | 单一 Service、Repository、Parser、Router、业务导出 | 领域 unit、API/contract、直接消费者 |
| L3 SHARED | 多领域共享基础设施或公共 DTO/协议 | API client、表格、动态图、Task/Job、Export、AP Identity | Change Impact Audit、Registry 指定 consumer suites、合并后复验 |
| L4 PLATFORM | 平台、数据、安全、生命周期和发布 | Feature Registry、DataRoot、SQLite migration、Electron runtime、构建/安装包 | 全局影响审计、platform contract、关键 smoke、完整支持基线、人工缺口 |

多个路径同时命中时取最高等级。未命中 Registry 的生产代码默认按 L2；纯 Markdown 和单页面局部样式可以是 L1。不能因为改动行数少而降低等级。

## Change Impact Audit

编码前回答并记录：

1. 真正修改的领域和用户行为是什么？
2. 改动文件属于 L1/L2/L3/L4 哪一级？
3. 是否触碰共享事实源或高风险路径？
4. 谁写数据，谁读数据，谁缓存数据？
5. 谁展示、导出或依赖这个状态？
6. 是否存在旧格式、旧 schema、旧数据库或兼容入口？
7. 当前是否有其他 worktree 修改同一共享契约？
8. 分支验证和合并后验证分别需要运行什么？

L3/L4 在完成 Consumer Audit 前不得开始大范围编码。评审入口为 `netconsole-change-review-skill`，再按领域组合专业 Skill。

## Consumer Matrix

下面是第一批长期共享契约。准确路径、消费者 ID 和可执行检查以 Registry 为准。

| 契约 | 风险 | 主要消费者 | 关键不变量 |
| --- | --- | --- | --- |
| Renderer API Client | L3 | Devices、AC、Config、Files、Rail Base、Trackside、MESH、Online MR、Ground、Network Tools、System、Feature | request coalescing、timeout、Abort、retry、错误体、Session header、Backend restart |
| NcDataTable | L3 | Devices、AC/FIT-AP、Trackside、MESH、Online MR、Ground、Tasks、Config、Files、Network Tools | table/route/column key、偏好、选择、筛选、分页、列宽、格式 |
| Dynamic Chart/Timeline | L3 | MESH RSSI、Online MR、fping RTT/loss、iPerf、Channel Busy、接口速率 | metricId、unit、axis、tooltip、null gap、DataZoom、selected/cursor time、Resize/KeepAlive |
| AP Identity | L3 | MESH、Ground、Online/Vehicle MR、Wireless、Trackside、AC/FIT-AP、报告 | exact alias、station scope、matched/unresolved/ambiguous、revision、批量快照 |
| Task/Job | L3 | Devices、AC、Config、Files、MESH、Online MR、Ground、Trackside Optical、Network Tools、Export | 七状态、唯一终态、partial success、progress、Worker protocol、restart/cancel、Artifact |
| Export Process | L3 | Devices、FIT-AP、Trackside、MESH、Online MR、Config、Network Tools | 用户目标、取消、临时文件、SHA-256、原子替换、Artifact、历史另存 |
| Feature Registry/Snapshot | L4 | 全部导航、FeatureGate、Full/Customer、Settings、Electron runtime、Packaging | fresh generation、stale request、coalescing、visible/enabled、requires、delivery_requires |
| DataRoot/SQLite | L4 | 启动、Site、Devices、Task、Agent、MESH、Online MR、Ground、升级/修复 | 唯一数据根、TEST 隔离、事务、WAL、备份、迁移、回滚 |
| Electron Native Runtime | L4 | 全部窗口、Renderer、Backend、Native Bridge、通知、文件授权、外部终端 | Main/Preload 双端 IPC、来源校验、单实例、生命周期、窗口/托盘、最小白名单 |
| Build/Release/CI | L4 | PR、main、Full/Customer、Backend/Renderer/Electron 制品 | 同一 Git HEAD、锁定依赖、离线工具、Package Smoke、制品身份 |

AP Identity 当前不是“全部 shadow”，也不是“全部消费者已接管”。统一 Identity 基础设施已进入生产；MESH、Ground、Online/Vehicle MR、Wireless 和部分 Trackside 链路已经使用统一批量查询，AC Mesh-Link、基础资料、其他报告和部分拓扑消费者仍按审计矩阵收敛。

## 机器识别与 Guard

从仓库根运行：

```powershell
.\.venv\Scripts\python.exe -m scripts.quality.check_change_impact --base-sha <base> --head-sha <head>
```

本地未提交改动可以显式传入路径：

```powershell
.\.venv\Scripts\python.exe -m scripts.quality.check_change_impact --paths apps/desktop_renderer/src/api/client.ts
```

本地质量门是开发验证的主要事实源，统一执行 Change Impact、定向检查、消费者套件和最终 FULL Gate：

```powershell
.\.venv\Scripts\python.exe -m scripts.quality.local_gate --mode auto
.\.venv\Scripts\python.exe -m scripts.quality.local_gate --mode fast
.\.venv\Scripts\python.exe -m scripts.quality.local_gate --mode consumer
.\.venv\Scripts\python.exe -m scripts.quality.local_gate --mode full
```

Gate 强制使用 `RuntimeMode.TEST` 与唯一 `D:/study/NetConsole-Workspace/test-data/NetConsole/<run-id>`，报告写入 `.local-reports/`。GitHub Actions 已退役；后续验证以主机/副机本地定向测试、主机集成验证、必要的真实 `D:\NetConsoleData-dev` 验收和 Release Gate 为准，也不得把未执行的 GUI、设备、安装包或长时运行验收写成通过。

输出必须稳定列出：

- 最高风险等级；
- 命中的共享契约；
- 影响消费者；
- 最低 consumer suites；
- 是否要求合并后复验。

Registry/Guard 必须失败关闭以下错误：L3/L4 无 owner/consumer/check、未知 consumer/check、关键路径降级、精确路径不存在或检查引用失效。新公共目录只能提示人工登记，不能凭目录名猜测所有消费者。

## 验证层级

### FAST

适用于 L1/L2 和开发中快速反馈：直接 unit/domain/API、定向 Vitest/Electron test、修改范围 Ruff/typecheck、相关 Guard。

### CONSUMER

适用于 L3。由 Registry 选择共享契约及现有 consumer contract；必须覆盖不止当前目标模块，但不要求无差别执行所有现场、安装包或真实设备测试。

### FULL

适用于 L4、发布和新的 `main` baseline：完整受支持 Python/Renderer/Electron/Agent 基线、架构门和适用构建检查。真实设备、Windows GUI、签名、升级、正式安装包仍单独记录，不能由自动测试替代。

## 主线 Smoke Matrix

主线 smoke 用一个稳定 happy-path/contract 发现整模块入口失效，不替代领域测试。

| 入口 | 最小契约 | 当前自动证据 |
| --- | --- | --- |
| Desktop startup | Electron 启动配置和受管 Backend 契约存在 | Electron `bootstrap` / `main-window-startup`，Python `test_electron_runtime.py` |
| Site/DataRoot | TEST 根、局点读取和路径解析 | `test_sites.py`、`test_electron_runtime.py` |
| Devices | 设备列表 API 可组合并返回稳定 DTO | `test_device_management_web_api.py` |
| AC/FIT-AP | AC/FIT-AP Router 与应用服务可组合 | `test_ac_management_web_api.py` |
| Rail Base | 基础资料查看 API 可用 | `test_rail_transit_base_data_web_api.py` |
| Trackside AP | 轨旁业务快照/查询契约可用 | Trackside business query/API 定向测试 |
| MESH | MESH 分析 Router/查询契约可用 | `test_mesh_analysis_web_api.py` |
| Online MR | Application Service 的会话关键路径可用 | `test_online_mr_application_service.py` |
| Ground | Ground Router 的基础状态/查询可用 | `test_ground_unattended_api.py` |
| Task Center | Task 创建、列表、详情和状态契约可用 | `test_job_center_web_api.py` |
| Export | Export Process/Artifact 基础契约可用 | `test_export_process_framework.py` |
| System Settings | 设置 API 读取/更新契约可用 | `test_system_settings_web_api.py` |

只有脚本和断言真实存在时才把该项计为自动 smoke；表中“定向测试”在固定入口收敛前仍由 Consumer Matrix 选择，不得伪装成端到端桌面验收。

## Worktree 与合并规则

- 普通功能分支尽量在 1 到 2 天内完成。超过该周期且已明显落后 `main` 时，优先从最新 `main` 建新分支并移植本任务提交。
- 业务分支同步 `main` 时遇到不属于当前领域的共享文件冲突，标记 `out-of-scope conflict`，停止顺手解决；重新评估风险等级，必要时重建分支。
- 同一时间最多保持一个大型共享基础设施重构。不同业务功能可以并行，但不得同时重设计多个 L3/L4 契约。
- 分支旧测试结果在合并后不能证明最终组合。L3/L4 必须在最终合并 commit 上重新执行 Registry 指定消费者回归；L4 还执行完整支持基线和适用 platform/package gate。
- 合并前后都检查同一共享高风险路径是否有并行 worktree 修改，并在交付中明确列出。

## 共享层冻结

仓库进入收敛期时，可以宣布 1 到 2 个开发轮次的共享层冻结。冻结期间 `api/client`、NcDataTable、Task/Job、AP Identity、Feature Registry、Path/DataRoot、Electron runtime 和构建发布只接受已证明必要的 Bug/安全修复；普通业务需求不得借机重构这些契约。解除冻结需基于新的 main baseline，而不是日历自然到期。

## 交付格式

修改高风险文件时，最终报告必须包含：

```text
Change Impact
Risk: L3/L4
Contracts: ...
Consumers: ...
Regression: PASS / FAIL / NOT RUN
Parallel modifications: none / details
Post-merge verification: command and result
Manual gaps: GUI / device / packaging / long-run
```

任何 `NOT RUN` 都必须说明原因和剩余风险，不能写成通过。
