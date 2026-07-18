# Web 双轨迁移第一批更新记录

> 历史阶段记录：本文描述当时的双轨边界。当前正式产品方向已改为 Electron-only；SNMP Center、通用 MIB/OID 平台和无线勘测也已在 v1.3.9 后续阶段删除。

更新时间：2026-07-16

## 目标与边界

本批次继续采用 Qt GUI 与 Desktop WebHost/Vue 双轨并存方案。Qt 保留稳定生产入口和故障回退能力；新增 Web 页面必须复用既有 Application Service、Repository、Task、Session、Mapping 和 Artifact，不复制采集器、连接器或业务规则。

本批次不删除、不隐藏 Qt 页面，不连接真实设备、生产 Agent 或真实凭据。SNMP 中心和无线勘测不在当前 Web 替换范围内。

## 指挥中心规则

- 主会话负责任务拆分、独立工作树、模型分配、范围控制、提交审阅、集成接线和最终验收。
- 模块工作树只运行直接相关的后端、前端和架构定向测试。
- 所有模块提交进入集成分支后，才运行完整 pytest、前端测试与构建、Ruff、文档检查，以及受影响时的 Go 测试。
- 中央 API Router、Vue Router、导航、Feature Registry 和总文档由集成阶段统一修改，避免并行冲突。

## 当前任务

| 模块 | 状态 | 当前边界 |
| --- | --- | --- |
| Online MR Agent 远程控制与 Fake E2E | 已完成 | 提交 `a84a130e`；真实设备验收继续冻结 |
| 质量与测试基线 | 已完成 | 提交 `6a7bda2b`；隔离测试数据、移除脆弱数量断言、更新 Web 架构断言、跳过依赖目录文档扫描 |
| 设备管理 Web | 已完成并集成 | 在既有只读页上补齐设备/分组 CRUD、批量刷新、诊断、导入预览与确认、CSV/模板/SecureCRT/OmniPeek 导出；高风险动作默认关闭 |
| 网络工具 Web | 已完成并集成 | 补齐 IPv4/IPv6/VLSM/子网/汇总/反掩码、Ping/fping/TCP 任务、结果分页与导出；无线扫描 Web 默认关闭，等待真实硬件验收 |
| 配置采集中心 Web | 已完成并集成 | 补齐快照对比、删除确认、`save force` 预览确认、报告导出、受控目录动作、Artifact 下载和中断恢复；扩展动作默认关闭 |
| 文件管理 Web | 已完成并集成 | 保留本地白名单浏览/下载，新增默认关闭的设备候选、只读 SFTP 会话、远程导航、下载队列、取消和 Artifact；不提供上传、删除或重命名 |
| AC / 轨道交通补齐 | 已完成并集成 | AP 扩展导入/回滚/导出、轨旁规划只读、本地重算、AC 高风险动作 Fake 计划；车内诊断、MESH 导入、Online MR/MESH 报告与任务恢复均走共享 Task/Export，全部默认关闭等待真实验收 |
| Electron Desktop 基础 | 已完成并集成 | 提交 `d74595e8` 集成安全 main/preload、动态回环 Python、白名单 Native Bridge、统一 Runtime Adapter、受管下载和退出屏障；Qt 继续保留 |
| Web 双轨基础设施 | 已完成 | 提交 `588a941`；统一导航注册、正式路由归属、Feature Gate、响应式 Desktop WebHost、前后端构建身份和 Qt/Web 能力矩阵 |
| Launcher / Core Runtime 第一阶段启动子项 | 已完成 | 四模式、隔离 Qt 能力探测、无 Qt Browser/Server、Core-owned WebHost、普通启动单实例；Server 仅允许回环绑定；Native Bridge、EmbeddedLayout 和 Qt 页面服务容器统一延期 |
| Phase 0.5 D 组合根与静态守卫 | 已集成 | 上游 `8b7a85ac`/`6a097420`，集成 `2843f199`/`1301ff92`；复用现有 `create_app()`，不新增运行容器 |
| Phase 0.5 A Online MR API 边界 | 已集成 | 上游 `7e3487e5`/`143ea3c3`，集成 `9e7d9660`/`58a7a319`；三个 Router 共用无副作用当前局点 Facade，LOCAL/AGENT 生命周期不变 |
| Phase 0.5 B Traffic Web 边界 | 已集成 | 上游 `6c8de0d6`/`73cbf48d`，集成 `b2bea6a1`/`bacab1f9`；执行端、分页、取消与重试进入 Web Application Service |
| Phase 0.5 C 基础资料策略边界 | 已集成 | 上游 `240c5bf1`，集成 `8cdc8435`；复用既有 Import Service 的 `get_import_policy()`，Guard 与写开关不变 |
| Phase 0.5 E 中央接线与债务清零 | 已完成 | 本集成提交；单例 Facade/Web Service 接线、共享 API 错误映射、Traffic presentation helper、正式 Router 静态债务清零；最终 SHA 由集成 Worker 报告给主控 |

## 已完成验证

- 2026-07-16 最终集成定向回归：后端 183 项、Web 39 个文件/107 项、Electron 10 个文件/56 项通过；Web 与 Electron main/preload 生产构建通过。
- Python 全量收集 2391 项；六个稳定分片与两个按测试文件隔离重跑分片共同覆盖全部用例，2389 项通过、2 项按既有条件跳过。分片宿主发生的 `KeyboardInterrupt`/Qt native abort 已通过 40 个文件逐文件重跑全部通过，未记录为业务失败。
- 文档结构与相对链接 4 项通过；安全只读复审关闭任务 DTO 路径/凭据、下载取消、Feature Gate 自洽、文件远程设备候选和组合根生命周期问题，最终无 P1/P2。
- 修改范围 Ruff 通过；全仓 Ruff 为 140 个既有错误，相比合入前 `main` 的 141 个未增加。本轮不为清零旧基线扩展到无关旧模块。

- Phase 0.5 A-D/E 直接相关与中央接线定向测试：16 个测试文件、107 项通过；静态 Router 边界债务为零。
- `src/netconsole/backend/api/` 全部正式 `*_router.py` 搜索确认无 `sqlite3` import/catch；共享错误映射保留原数据库/I/O HTTP 状态和消息。
- Phase 0.5 本轮修改 Python 文件 Ruff、`py_compile`、`compileall` 通过；`pip check` 无破损依赖，`git diff --check` 通过。
- 文档结构与相对链接测试：4 项通过；`docs/README.md` 已索引 Traffic Web 边界文档。
- 前端源码未改，仍完成全量 Vitest：30 个文件、74 项通过；`vue-tsc -b` 与 Vite 生产构建通过，临时 `node_modules` 联接和 `dist` 已清理。
- Python 单进程全量在 57% 无失败摘要退出，复现既有 Qt 累计状态基线；按排序测试文件稳定拆成 8 个独立进程，`2267 collected` 全部核对：2264 项通过、2 项按既有条件跳过，1 项真实 PyInstaller 发布验收按本任务明确非目标未运行。发布数据清单项在临时前端构建存在时已单独复验通过，未把 PyInstaller 项记录为通过。
- 受影响 Go 文件为 0，因此未运行 Go 测试；本批次未修改 Go Agent、Traffic 协议或构建发布代码。
- 对 `29624b2c..HEAD` 及任务 E 工作区执行最终只读架构复核，覆盖 Router 构造、当前局点、导入策略、Agent 能力、取消/重试、重复实例、跨局点、Online MR 恢复/生命周期、Traffic 协议、基础资料写保护、凭据/绝对路径和兼容写法；未发现 P1/P2。

- 质量基线相关 pytest：50 项通过。
- 质量基线修改文件 Ruff：通过。
- Qt 配置采集页定向测试包含在上述验证中。
- 先前设备采集与刷新相关 Qt 定向测试：19 项通过，未复现“Qt mock 返回值错误”。
- 四模块中央接线后的组合后端定向测试：180 项通过，只有 1 条既有 Starlette TestClient 弃用警告。
- 四模块新增 Vue 页面/API 定向测试：5 个文件、12 项通过；生产构建通过。
- 本批次新增/修改 Python 文件 Ruff：通过。
- 独立只读评审发现 3 项 P1、2 项 P2；已完成 Feature Gate 强制执行、设备动态局点、文件类型白名单、重复任务复用和共享进程适配器收口。
- 评审修复定向后端测试：24 项通过；对应 Vue Feature/页面测试：7 个文件、16 项通过；前端生产构建和修改文件 Ruff 通过。
- 第一批所有改动测试文件组合复跑：144 项通过。首次未设置源码路径时有 8 个 Worker 子进程导入失败；确认是工作树虚拟环境未 editable 安装，显式使用 `PYTHONPATH=src` 后全部通过。
- 第二轮独立复核确认 P1 已全部关闭，指出 3 项 P2：并发幂等竞态、`raw/imports` 未知格式旁路、关闭总预算不一致；均已修复。
- P2 修复专项测试：并发幂等、文件白名单、总关闭预算和并行 lifespan 共 40 项通过；Job Center、Traffic、AC Mesh-Link 与 WebHost 受影响回归 39 项通过。
- 最终复核指出取消派发计时点仍在 deadline 之外；现已改为入口建 deadline、后台取消派发和受预算约束的最终收口，相关 LocalProcessAdapter、Job Center、Traffic 与 lifespan 回归 52 项通过。
- 关闭边界复核进一步发现慢 `prepare/Popen` 持有状态锁；现已把阻塞启动步骤移出状态锁，关闭开始后完成的启动会被拒绝登记并立即回收，不遗留 Worker；相关关闭、Job Center、Traffic 与 lifespan 回归 53 项通过。
- 最终独立只读复核结论：没有 P1/P2 阻断项。
- 前端全量测试：28 个文件、62 项通过；生产构建通过。
- 后端单进程全量两次分别在约 55% 和 58% 无 pytest 失败摘要退出，已完成用例均通过；退出前最后一项单独运行通过，判定为 Qt 长进程累计状态基线，不作为业务用例失败处理。
- 后端按 8 个独立 pytest 进程覆盖全部 2187 项：2185 项通过、2 项按既有条件跳过。分片过程中发现 1 个 Qt 测试仍把 `OnlineMrCollectorWorker.start()` mock 为返回 `None`；按正式任务快照契约修正后，相关 2 项定向测试和所在分片 400 项均通过。
- 全仓 Ruff 仍有 142 个既有错误，均位于本批次未修改的旧模块；本批次生产代码变更范围 Ruff 通过，未为清零旧基线扩大修改范围。
- Web 双轨基础设施定向回归：受影响后端 64 项通过；前端 30 个文件、74 项通过；Vue 类型检查和生产构建通过。
- Web 双轨基础设施独立只读评审发现 1 项 P1 和 1 项 P2：共享 Task API 误归属于 Job Center、Feature 状态加载失败时前端路由放行；均已修复并补回归测试，复核后无遗留 P1/P2 阻断项。
- 本轮最终 Python 全量按 8 个独立进程加完整发布烟测执行：2207 项通过、2 项按既有条件跳过；真实 PyInstaller 构建、发布目录白名单、内嵌 Web metadata 与 EXE 启动烟测通过。
- Agent `go test ./...` 全部通过；修改范围 Ruff、`compileall`、`git diff --check` 和文档结构检查通过。
- Launcher/Core Runtime 组合定向回归：127 项通过；补充真实健康端点启动/停止、浏览器失败保持 Core、CLI 帮助和提权子进程兼容后，Launcher 专项通过；FastAPI 启停失败隔离专项 3 项通过。
- Launcher/Core Runtime 最终合并门禁：当前 2240 项 Python 用例全部覆盖，2238 项通过、2 项按既有条件跳过；原生 Qt 文件采用独立 Python 进程隔离，真实 PyInstaller 构建、EXE smoke、源码/冻结包 Widgets 与 WebEngine probe 均通过。前端 30 个文件、74 项通过并完成生产构建，Agent `go test ./...` 通过。
- Launcher/Core Runtime 独立只读评审发现非回环无鉴权绑定 P1 和 Qt probe 导入链污染 P2；现已限制 Server 仅绑定 loopback、拆出轻量 probe 并补发布 import graph 断言，复核后无遗留 P1/P2。修改范围 Ruff、全量 `compileall`、`git diff --check` 通过；全仓 Ruff 仍有 141 个既有错误，未扩大本阶段范围处理。

## 当前安全与功能限制

- Phase 0.5 A-D/E 未连接真实 AC、MR、Agent 或生产数据；只使用 `tmp_path`、Fake 和本地测试链路，不把定向/全量结果解释为现场验收。
- Phase 0.5 A-D/E 本身未修改 Vue、Go Agent、设备命令、Traffic 协议或基础资料写入开关；后续 Web 对等收尾已修改 Vue 和 Electron 锁文件。受影响 Go 文件仍为 0，因此未重复运行 Go 测试。

- 设备管理不返回凭据；正式 CRUD、导入导出、诊断和桌面联动均有独立 Feature Gate，扩展动作默认不进入客户包。
- 网络工具沿用现有 Traffic/Task/Export；Agent 旧 `ping_probe` 只提供终态，尚无结构化逐样本结果。无线扫描 Web 仅完成 Fake，未做真实网卡验收。
- 配置中心的删除、`save force`、导出和目录动作均默认关闭并要求确认或受控目录映射；任务消息、错误和结果会递归遮蔽路径与凭据值。
- 文件管理本地索引继续排除 `parsed/cache/tmp/runtime`、SQLite/DB/WAL/SHM/journal 和未知格式；远程模块只读 SFTP，不提供上传、删除、重命名或 WinSCP 任意启动。
- 四个新 Web 页面及其受控动作同时在 Vue 导航/按钮和 FastAPI 路由执行 Feature Gate；后端禁用时直接返回 404，不能靠直连 URL 绕过。
- 设备管理在每次请求时读取当前局点，Qt 切换局点后无需重启 WebHost；设备连接测试和配置采集对同设备活动任务幂等复用。
- 活动任务的“查询并启动”由服务级锁形成原子临界区；并发请求只启动一个 Worker。`raw` 仅接受日志、结构化文本和抓包后缀，`imports` 仅接受已识别归档格式。
- `LocalProcessAdapter.shutdown(timeout_seconds)` 的参数是包含取消派发、协作等待、terminate、kill 和最终状态收口的总预算；取消持久化使用受 deadline 约束的后台派发，FastAPI lifespan 并行关闭本地 Adapter、AC 刷新和 Traffic，默认总预算不超过 WebHost 的等待窗口。

## 延期与取消

- CentOS 7 Agent 兼容包：延期，等待可用环境后再单独立项。
- Windows Legacy Agent 兼容包：取消；当前 Agent 已在 Windows Server 2012 验证可用。
- 两个旧兼容包工作树中的草稿保持原样，本批次不继续修改或删除。

## 合并前门槛

1. 四个模块均有本地提交、定向测试结果和中央接线清单。
2. 指挥中心逐提交审阅安全边界、数据路径、任务恢复和 Qt 回归风险。
3. 集成路由、导航与 Feature Registry 后运行模块组合测试。
4. 最后运行全量测试；失败必须定位到代码、环境或既有基线，不以跳过测试代替修复。
