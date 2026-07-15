# Web 双轨迁移第一批更新记录

更新时间：2026-07-15

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
| 设备管理 Web | 已集成 | 提交 `02c6bda4`；列表、筛选、详情、后台连接测试、受控编辑预览，不暴露凭据 |
| 网络工具 Web | 已集成 | 提交 `267d5a1b`；复用 Traffic Run、fping/iPerf，补充本地/Agent TCP 端口测试 |
| 配置采集中心 Web | 已集成 | 提交 `b480c8c4`；复用 Config Lifecycle、Snapshot、既有 diff/load Job 与受控 Artifact，仅新增一个只读 fetch 薄 handler |
| 文件管理 Web | 已集成 | 提交 `8925b7ad`；局点本地文件分类与受控下载，不做设备远程文件、删除、上传或重命名 |
| Web 双轨基础设施 | 已完成 | 提交 `588a941`；统一导航注册、正式路由归属、Feature Gate、响应式 Desktop WebHost、前后端构建身份和 Qt/Web 能力矩阵 |

## 已完成验证

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

## 当前安全与功能限制

- 设备管理不返回凭据，不提供浏览器终端；编辑仅生成预览，尚不落库。
- 网络工具沿用现有 Traffic Run；Agent 旧 `ping_probe` 只提供终态，尚无结构化逐样本结果。
- 配置中心不提供 `save force`、远程删除或任意路径读取；任务消息、错误和结果会递归遮蔽路径与凭据值。
- 文件管理首版只浏览和下载局点本地文件；下载任务验证并审计原文件，不复制永久副本；`parsed/cache/tmp/runtime`、SQLite/DB/WAL/SHM/journal 和未知格式不进入索引。
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
