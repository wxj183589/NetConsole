# R2.2 测试报告

日期：2026-11-10。最终结论 PARTIAL。测试均使用显式隔离根及合成数据，无现场设备访问。基线 Syslog `b3ccb1bd`；完整 Gate 启动时基线/HEAD `4d50142816bf95f118c9c0d93b12e88f9f37fd48`，运行中保留并行 MESH 提交，定向最终复验所在 HEAD `2be3df15`；工作树含未提交 R2.2 与已有 DataRoot/SiteStorage 修改，不能据此宣称干净集成提交的 Gate PASS。

## 定向证据

| 验证 | 结果 | 日志 / 覆盖 |
| --- | --- | --- |
| resident + Fleet retention 最终定向 | 26 passed，1 warning | `.local-reports/r2-2-resident-final2.log`；无 Run lifespan、重复 start、配置独立/热更新、迁移/清理、Site switch、恢复、故障、400 MR 回调 |
| Ground 全域最终复验 | 435 passed，1 skipped，1 warning | `.local-reports/r2-2-ground-final2.log`；含 Syslog 多批次、所有权与 Ground Run 回归 |
| 基础资料编辑消费者全文件 | 28 passed，2 warnings | `.local-reports/r2-2-base-data-final.log`；三个主备策略用例改为调用独立 HeartbeatSupervisor |
| 库存定向 | 21 passed，1 warning | `.local-reports/r2-2-inventory-final.log` |
| Ground View 最终定向 | 21 passed | `.local-reports/r2-2-view-final.log` |
| 完整 Renderer 最终独立运行 | 209 files / 1526 passed | `.local-reports/r2-2-renderer-final.log` |
| Renderer vue-tsc -b / Vite build | PASS | `.local-reports/r2-2-renderer-build.log`；现有 chunk 大小提示 |
| Electron Main/Preload build | PASS | 构建命令 `pnpm run build:main` |
| 修改范围 Ruff | PASS | `.local-reports/r2-2-ruff-final.log` |
| git diff --check | PASS | 最终提交前再次检查 |
| 实际隔离 Electron | 已列场景 PASS | [GUI 验收](R2_2_GUI_ACCEPTANCE.md)与版本化 PNG/JSON |
| 实际 400 MR/800 IP fping | 短时正确性 PASS | [性能报告](R2_2_PERFORMANCE_REPORT.md)，47 秒观测，容量验收 PARTIAL |

早期 Ground 全域 `1 failed, 429 passed, 1 skipped` 为 retention mock 未配置新恢复查询；已修复 fixture 并修正生产逻辑，避免未采样目标重复读库。早期 resident Mesh 故障测试被生产 poll 节流跳过；仅在测试中重置 poll 时钟强制每轮注入，不改变生产节流。早期库存手动 preview/apply 测试与自动刷新竞争；fixture 固定自动刷新时间，自动库存刷新另有覆盖。早期 Gate Renderer 两个旧控件源码断言失败，已随独立设置契约更新，完整 Renderer 新运行通过。

## L4 完整门禁

执行 `python -m scripts.quality.local_gate --mode full --base-sha 4d50142816bf95f118c9c0d93b12e88f9f37fd48`，日志 `.local-reports/r2-2-full-gate.log`。结果 **FAIL**。Python 阶段为 47 failed、5590 passed、2 skipped、35 warnings；Electron 为 38 files / 306 passed，typecheck/build 通过。root-layout、workspace-layout、main-contract-smoke、ruff-full、git-diff-check 通过。本报告不把定向结果替代为完整 Gate PASS。

失败核对：

- R2.2：两个旧 Renderer 设置断言、retention mock、库存 preview/apply 竞争、三个基础资料消费者测试，以及本领域报告 README/audit 路径登记。已修复并分别复验；完整 Renderer 1526 项、Ground 435 项、基础资料 28 项通过。Gate 运行期间代码继续修改，不能将其视为最终提交的完整重跑。
- 并行 DataRoot：7 个 installer diagnostics 用例仍 monkeypatch 已移除的 `_require_windows_fixed_drive`；1 个 SiteStorage 用例未接纳新增 `disk`/`recommended_data_root` 字段。没有改动这些测试或模块。
- 生产维护测试：29 项报 `CURRENT_HEAD_MISMATCH`，与 Gate 运行期间 HEAD 变化一致；仅记录错误证据，不宣称这些测试在固定 HEAD 一定通过。
- MESH/架构：3 项 Python 架构测试及独立 architecture-guards 命中 `mesh_link_detail_export.py` 的 `display formatting or unit conversion` 审计候选。本任务未修改该文件。
- 文档：最终定向检查 20 passed、2 failed，仅剩两个已跟踪 MESH audit 文件命名和十个 MESH 目录 README 缺口。R2.2 自有链接、路径和目录均通过。
- package-smoke：安装器身份准备因 dirty 工作树拒绝执行；没有规避该发布保护，也未生成正式安装包。

文档门禁会扫描整个并行工作树。R2.2 明确要求的 audit 文件按既有精确 `FIXED_REPORT_PATHS` 模式登记，新增本领域/证据目录 README；没有放宽通用目录规则。MESH 现有报告的命名与 README 缺口归并行工作，不在本任务顺手改动。

## 故障与覆盖限制

- 独立 resident 测试注入 AC、Mesh 查询、UDP start、Syslog replay 异常；Ground 抛错或捕获重放失败时，真实独立 Heartbeat 线程继续累积样本。
- 既有 AC resident 套件覆盖慢 AC、反复 deep scheduler 失败、磁盘临界时暂停深采而保留心跳。fping 异常与意外 stream end 均检查 degraded、至少约 2 秒退避后恢复。
- SQLite 快照失败及事件/summary 写失败保留 dirty 数据，恢复后落库；不等价于真实长时间磁盘耗尽或所有 SQLite 锁竞争场景。
- Renderer 组件轮询/卸载和真实 reload/离页已验证；没有强杀 Renderer 进程。Syslog replay 异常不能替代 Parser 线程实际崩溃。
- 正常重启、旧格式迁移、未闭合丢包/累计计数恢复已有证据；没有断电/进程强杀窗口与真实历史数据库迁移验收。
- 8 小时长稳、长时间高频导航/库存变更、现场设备均 NOT_RUN。打包安装、发布与 main 合并后门禁未执行。
