# Ground Unattended V2 最终稳定性审计（2026-11-07）

## 1. 结论和范围

**PASS_WITH_LIMITATIONS**。在隔离 Fixture、回环 UDP、自动化 Service/API 和源码浏览器范围内，已修复本轮发现的关键问题，未发现仍未解决的 P0/P1。Windows 现场长期稳定运行尚不能确认：原生 DPI、完整 Electron 异常生命周期、隔离安装包和全系统 24 小时验证均未完成。

唯一代码仓库为 `D:\study\NetConsole-Workspace\NetConsole`。Branch=`main`，HEAD=`9031d00017cecf8802f34a96f136bbf01007d862`。原 V2 的 112 个未提交文件全部保留；其中 17 个文件相对审计起始 SHA-256 变化，95 个字节未变。本轮另增 1 个组件压力脚本和 5 份报告，最终共 118 个 dirty 路径。没有 commit、push、PR、merge、release 或正式部署，也未修改 DevStatus。

未访问 Next 产品仓库；未连接真实设备，未读取、复制或写入 Production/Dev 真实数据根。测试使用 Workspace `test-data/NetConsole/<run-id>`；构建使用仓库既定输出目录。未新增业务功能、框架或第三方依赖。

配套交付：

- [112 文件审计台账](./ground-unattended-v2-file-audit-2026-11-07.md)：职责、证据、前后完整哈希及本轮改动归属。
- [缺陷登记](./ground-unattended-v2-defect-register-2026-11-07.md)：位置、触发、影响、修复和回归。
- [Windows 验收](./ground-unattended-v2-windows-validation-2026-11-07.md)：浏览器与原生边界、生命周期、安装包补验。
- [压力测试](./ground-unattended-v2-soak-test-2026-11-07.md)：245 秒组件实测、资源趋势、24 小时启动/停止步骤。

## 2. 验收矩阵

PASS 只表示下表明确列出的验证层；BLOCKED 表示该项完整验收仍缺证据。

| 项目 | 状态 | 实际证据与边界 |
| --- | --- | --- |
| 112 文件变更审计 | PASS | 112/112 存在并分类，逐文件职责/证据/哈希见台账；Electron Main 变更为 0 |
| Python 后端回归 | PASS | FULL 5458 passed、2 skipped；最后 Ground 定向 453 passed、1 skipped |
| Renderer 回归 | PASS | 193 文件/1367 项；typecheck/build；最后 Quick 10 项、图表 1 项和构建 |
| 架构测试 | PASS | 12/12；Soak TEST_ONLY SQL 登记后再验通过 |
| 心跳状态机 | PASS | 双 IP、10 秒、双端交集 120 秒、2 次恢复、采样空窗/身份变更/冲突/重启 |
| 快速 Ping | PASS | 独立 run、默认参数传递、时限/手停/并发/持久化/INTERRUPTED，重复任务与异常目标回归 |
| Syslog | PASS | 原始优先、有界队列/Spool、20k burst、10MiB/gzip、锁/ENOSPC/fsync/重放回归 |
| AC-Mesh-Link | PASS | 30 秒 fresh、120 秒 recent、301 秒 stale，离线隔离，设备/接收时间分离 |
| 深度采集 | PASS | Mock 慢/失败/并发/停止/critical disk 隔离；未进行真实 SSH 互操作 |
| 十个页面 | PASS | 真实源码页面与 API/Service 契约，六浏览器配置 12 项；HTTP mock，非真实 Backend GUI 端到端 |
| Windows DPI | BLOCKED | 原生六配置未操作；浏览器 deviceScaleFactor 不能替代 |
| Electron 生命周期 | BLOCKED | 306 项契约与源码启动/退出 smoke 通过；原生崩溃/强杀/重启/托盘长运行待验 |
| 安装包 | BLOCKED | 无隔离安装机；dirty=false 构建门与本轮禁止提交冲突；未生成/安装本轮包 |
| 24 小时运行 | NOT_RUN | 实际组件运行 245.286 秒；虚拟时钟测试不等于 24 小时实跑 |
| 故障恢复 | BLOCKED | 组件异常/空窗/锁/压缩/磁盘恢复通过；完整 OS/进程异常链待原生补验 |
| 数据完整性 | PASS | Fixture raw/gzip/hash/CRC/索引与 SQLite integrity=ok；不代表断电或真实存储介质验收 |

## 3. Consumer Audit 和兼容性

Change Impact 为 **L4**。Registry 契约命中 `data-root-and-migration`、`export-framework`、`feature-registry`、`history-store-retirement`、`ssh-relay-and-host-key`。19 个消费者：ac_fit_ap、agent、config_collection、data_platform、devices、electron_runtime、export、feature_delivery、file_management、ground_unattended、mesh、network_tools、online_mr、rail_base、release_engineering、renderer_platform、system_settings、task_job、trackside_ap。命中表示需要消费者回归，不表示本轮改动了全部消费者。

| 边界 | 审核内容及证据 |
| --- | --- |
| Writer | Fleet/Heartbeat、Quick、Syslog 各自采样与原始输出；Quick 不修改心跳；采样回调不执行 SQLite 事件写入 |
| Repository | 同一 site/run 隔离；心跳快照、Quick run/stats/events、raw 注册及稳定去重；锁竞争保留待写事件 |
| API/缓存 | 当前心跳过滤已移除 MR/train；历史 run 事实保留；分页、筛选、DTO、Feature/capability gate |
| Vue | 十页复用 Service API；Abort/generation/在途保护；离开页面仅停 UI 轮询；图表卸载释放实例 |
| Export | 复用 Export Process/Artifact 和固定动作；历史 CSV 与分页同筛选排序，公式转义；不重建保存系统 |
| 旧格式 | active raw、gzip、READY ZIP 查询兼容和索引恢复回归；不改写历史 raw、不自动迁移/删除旧目录 |
| 历史架构 | Current + Recent10 和仍保留的 bounded history；未恢复 Legacy HistoryStore runtime/fallback |
| 并行/合并 | 本轮收尾无活动并行代理；主仓库仅一个 worktree；未 merge，无最终集成 commit 结果 |

依赖审计覆盖 **13** 份 manifest/lock/constraints，全部与 HEAD 等价：两套 package.json/pnpm-lock、Go mod/sum、pyproject、5 份 requirements 和 constraints.txt。完整哈希见文件台账及 `.local/ground-v2-final-audit/dependency-audit.json`。原有工具链 typecheck/build 均通过。

V2 已有数据库增量是 Ground index.sqlite 中心跳状态及 Quick runs/stats/events 四表和索引，基础资料备用策略仍用 site_meta，AC 新增时间/新鲜度字段；本轮没有再增加数据库 schema。Soak 的直接 SQL 仅用于独占测试 SQLite integrity 检查，已登记 TEST_ONLY。

## 4. 核心规则核验

心跳默认 1000ms/4000ms/64 Bytes 已从 Profile/Fleet 传到 fping runner；每 IP 分别采样，MR 任意合资格地址成功即有在线证据。备用 MONITOR 参与，FAILOVER_ONLY/DISABLED 不自动参与。全失败证据连续 10 秒才确认 MR 离线，继续探测，2 次连续成功恢复；不是简单累计 10 次失败。双端不可达交集达 120 秒才确认整车离线，不是 10+120 秒，一端恢复即重置。CT_ONLY=仅 CT 可达，CW_ONLY=仅 CW 可达；单端不伪造双端离线。

地址/身份变更清 live 状态；重复 IP 失败关闭；采样缺口、引擎退出和重启显示 UNKNOWN/DEGRADED，空窗不累计设备失联时间。离线告警在缺口后保持待恢复，不能因引擎中断产生假恢复。已从初次失败复现修复为回归通过。

心跳事件改为有界 4096 待写队列、256 条批次，采样锁外持久化，失败保留重试、dedup key 保持稳定。队列饱和明确健康错误/失败关闭，不能外推为永久数据库故障下仍无限保留所有事件。

Quick 默认 200ms/1000ms/64 Bytes/无限、默认最多 4 活动 run；在途与发包率校验、recent 256、有界缓存、分段持久化及重启 INTERRUPTED 有回归。重复同目标同参数活动任务返回 409，非请求 IP 样本拒绝；不使用 Quick 成功结果判定列车在线。

Syslog 配置仅本地验证 `system-view` → `info-center enable` → `info-center loghost <server> port <udp-port>` → `return`；UDP/Informational，不加 Debugging/Trap/TCP/save/旧配置清理。Receiver→Raw Writer→原始文件→Parser 链路独立；未知模块/解析错误保留原文。10MiB 分段、后台 gzip 校验/登记、重试和原始保留有定向测试。元数据有序有界，SQLite busy/locked 最多 3 次重试；持久故障暴露 health 并保留原始证据，不承诺无限自动修复。live/replay 均保留 device_time/received_at。

AC 独立、不得覆盖心跳和资格。既有 freshness 契约为 30 秒 FRESH、120 秒 RECENT、301 秒 STALE；测试覆盖延迟和完全离线，不能把所有 120 秒数据强行标为 STALE。深采继续复用原连接库和受管会话，Mock 失败/慢操作/停止/磁盘临界不停止心跳，没有扩大并发。

## 5. 实际测试与证据

证据目录为仓库忽略目录 `.local/ground-v2-final-audit/`，不是版本化制品。应保留到本轮审阅完成；跨机复验需重新执行命令，不应依赖忽略文件存在。

| 验证 | 实际结果 | 证据文件 |
| --- | --- | --- |
| 本轮统一 FULL Gate | 10/10 PASS，L4，exit 0 | full-gate.log、full-gate/local-gate.json、local-gate.md |
| Python full | 5458 passed、2 skipped、34 warnings；1826.97s | full-gate.log |
| Renderer full | 193 文件/1367 passed；typecheck/build PASS | full-gate.log |
| Electron full | 38 文件/306 passed；typecheck/build PASS | full-gate.log |
| 架构门 | 12/12 PASS | architecture-fixed.log、full-gate.log |
| Main contract smoke | 12 passed；15.92s | full-gate.log |
| Ruff / docs guards | All checks passed / 22 passed | full-gate.log |
| 核心基线 / 事件回归 | 64 passed / 68 passed | baseline-core-tests.log、event-regression-2.log |
| 最后边界回归 | 11 passed；1.90s | final-boundary-tests.log |
| 最后 Ground+关联消费者 | 453 passed、1 skipped、2 warnings；259.16s | final-ground-regression.log |
| 最后 Syslog | 32 passed、1 warning；70.69s | final-syslog-regression.log |
| 最后 Quick / chart | 2 文件/10 passed；图表 1 passed | quick-final-regression.log、chart-fixed.log |
| 最后 Renderer build | PASS；已有大 chunk 提示 | renderer-fixed-build.log |
| Electron 生命周期契约 | 完整 38 文件/306 passed；12.59s | electron-lifecycle-tests.log |
| Electron 源码 smoke | Vite/backend ready、TraySync 一致、受管退出完成 | electron-smoke.log |
| 浏览器六配置 | 12 passed；约 1.6min | browser-visual-fixed.log、browser-visual-fixed/ |
| 组件压力 | 245.286 秒 PASS、73,500 心跳样本、UDP 12,700 无应用丢弃 | soak-verified.log、独占 run summary.json |
| Skip 核验 | 两指定节点均跳过，原因明确；0.76s | skip-reasons.log |

FULL Gate 时间：UTC `2026-11-06T20:39:10.233623+00:00` 至 `2026-11-06T21:13:31.371031+00:00`，本地 11 月 7 日 04:39–05:13。**Gate 启动后仍有收尾修复，因此这是 FULL 通过加最后改动定向回归通过，不是最终冻结快照完整 FULL。** HEAD 未变化也不能将 dirty 工作树视为可复验 commit。未来用户授权提交/集成后，须对最终 commit 重跑 Registry FULL Gate。

两项 skip：500k query 需显式 `NETCONSOLE_RUN_SCALE_TESTS=1`（常规 50k 已执行）；SNMP device smoke 未配置 `NETCONSOLE_SNMP_SMOKE_CONFIG`，符合本轮禁止真实设备要求。Starlette/httpx/422 弃用提示和构建 chunk 提示未导致失败；未为消除提示升级依赖。

五份报告生成后补验：docs path guards **22 passed（0.81s）**，Workspace layout PASS，`git diff --check HEAD` PASS；五报告本地 Markdown 链接 **11/11 有效**。原112文件仍完整、17个本轮变动、最终118个dirty路径；最终核对摘要保存在 `.local/ground-v2-final-audit/final-verification.json`。

## 6. 命令与重放

默认 cwd 为主仓库，Python 使用 `.venv`。FULL wrapper 从起始 112 清单传入 paths，`base_sha=head_sha=HEAD`，真实执行工作树；只为 Renderer 限制 maxWorkers=2。它建立独占隔离测试根，报告证据保留，结束后退役自有测试运行根。

```powershell
.\.venv\Scripts\python.exe .local/ground-v2-final-audit/run_gate.py
# 跨机或最终提交后的 canonical 入口：
.\.venv\Scripts\python.exe -m scripts.quality.local_gate --mode full
.\.venv\Scripts\python.exe scripts/architecture/run_all.py
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m scripts.check_workspace_layout
git diff --check HEAD
```

FULL 内部实际 argv 清单逐条保存在 `full-gate.log` 尾部，文件台账附录同时固化这些命令。Python 为 `-m pytest -q --tb=short --basetemp <unique-run>/pytest-python-full`；Renderer 为 Vitest run --maxWorkers=2、vue-tsc -b、vite build；Electron 为 Vitest run、tsc --noEmit -p tsconfig.json、node scripts/build.mjs。本轮未改 Go，未另跑 Go build/test。

最后 Ground 命令原文保存在 `final-ground-regression.log` 首行，可等价重放为：

```powershell
$groundTests = (Get-ChildItem -LiteralPath tests -Filter 'test_ground_unattended_*.py').FullName
.\.venv\Scripts\python.exe -m pytest @groundTests tests/test_udp_syslog_reliable_spool.py tests/test_ac_mesh_link_query_service.py tests/test_ac_mesh_link_refresh_service.py tests/test_vehicle_mr_online.py tests/test_rail_transit_base_data_edit_api.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_udp_syslog_reliable_spool.py tests/test_ground_unattended_syslog_v2_stress.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_ground_unattended_heartbeat_state.py tests/test_ground_unattended_quick_ping.py tests/test_ground_unattended_ac_resident.py tests/test_ground_unattended_api.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_project_docs_layout.py tests/quality/test_directory_readmes.py -q
# 指定 skip 核验前显式清空以下变量，避免访问设备/执行 opt-in 规模任务：
$env:NETCONSOLE_SNMP_SMOKE_CONFIG=''
$env:NETCONSOLE_RUN_SCALE_TESTS=''
.\.venv\Scripts\python.exe -m pytest tests/test_ground_unattended_query_scale.py::test_active_query_streams_500000_ping_samples_within_query_budget tests/smoke/snmp/test_snmp_device_smoke.py::test_configured_device_snmp_v1_v2c_basic_identification -q -rs
```

Renderer cwd=`apps/desktop_renderer`：

```powershell
pnpm exec vitest run src/views/rail-transit/QuickPingPage.test.ts src/components/ground-unattended/quickPingChartOptions.test.ts --maxWorkers=2
pnpm exec vue-tsc -b
pnpm exec vite build
pnpm exec playwright test -c playwright.config.ts ground-unattended.visual.spec.ts --project='1920x1080@100%' --project='1920x1080@125%' --project='1920x1080@150%' --project='2560x1440@100%' --project='2560x1440@125%' --project='2560x1440@150%' --workers=1 --output=../../.local/ground-v2-final-audit/browser-visual-fixed
```

Electron cwd=`apps/desktop_electron`：

```powershell
pnpm exec vitest run
pnpm exec tsc --noEmit -p tsconfig.json
node scripts/build.mjs
node scripts/dev.mjs --smoke
```

压力测试命令、停止方法和原生补验操作见对应报告。首轮失败并未隐藏：4 项核心失败、当前 API 残留失败、事件锁失败、SQL guard 失败及 6 项 ECharts 警告失败均有日志，对应修复后证据见缺陷台账。重放修复后的命令不会再次得到修复前失败。

## 7. 剩余风险和下一步

1. 原生六分辨率/DPI，尤其 125%，须逐页真实操作并验证任务栏/抽屉/图表。
2. 在隔离 Windows 环境补 Renderer 崩溃、Backend 强杀/恢复、Windows 重启、托盘与残留进程/端口检查。
3. 获用户后续授权、形成干净且版本一致的候选后，按 canonical 打包并在隔离机安装/启动/卸载。
4. 全系统 24 小时仍 NOT_RUN。已有脚本只覆盖组件；还需真实 Backend/Electron/fping 进程与 AC/deep 模拟链路和独立进程指标。
5. 本轮证据审阅前保留；不清理原有 112 文件、原始数据或历史目录。未来最终集成 commit 重跑 FULL。

本报告不授权发布。当前等待用户下一步指令。
