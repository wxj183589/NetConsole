# AP Identity 阶段 8.2 Job 详情宿主接入评审

## 1. 背景

阶段 8.1 已新增纯 Python `DiagnosticsSummaryViewModel`。它只消费 `identity_shadow`、`detail_identity_shadow` 和 `export_identity_diagnostics`，执行严格聚合字段允许列表、风险提示和安全状态转换；默认开关关闭，不保留原始 result 引用。

阶段 8.2 只评估未来只读 UI 应挂接到哪里。本阶段不实现 Qt widget/dialog，不修改 Job Center、业务页面、feature flag、resolver、数据库、导出、报告、parser 或生产结果。

评审问题不是“哪个业务页面最容易加一块区域”，而是：当前是否存在能够安全持有单次终态 event、提供显式详情入口并在关闭后释放结果的统一宿主。

## 2. 当前 Job / Export UI 宿主现状

### 2.1 Job Center Manager

`src/netconsole/ui/job_process_manager.py::BackgroundProcessManager` 是迁移期 Qt QProcess 生命周期 Adapter，不是任务列表或详情模型：

- 运行中只在 `_jobs` 保存 `job/process/job_path/cancel_path` 和临时 JSONL 缓冲。
- `finished/failed/cancelled` 以完整 event 发给调用方。
- 终态后立即从 `_jobs` 移除状态、清理 Job/取消文件并释放 QProcess。
- 不保存历史终态、result metadata、任务标题、页面来源或权限上下文。
- 原 `services/background_process_manager.py` 兼容重导出已删除，避免永久 Service 反向依赖 Qt Adapter。

因此它不能直接充当 UI 宿主，也不应为了 AP Identity 在服务层导入 UI 或保存完整 result。

### 2.2 普通后台任务 helper

`ui/job_action_helper.py::submit_background_job()` 创建非模态 `QProgressDialog` 和临时 `BackgroundJobController`：

- progress 只更新进度值和标签。
- finished 时显示成功 InfoBar/消息，随后关闭 progress dialog。
- 终态 callback 可以收到完整 event，但 controller 随后从 parent 列表移除并 `deleteLater()`。
- `QProgressDialog` 没有 result/metadata 区、详情按钮或任务历史。

该 helper 具备正确的 parent、取消和单终态生命周期，但当前承载的是“执行进度”，不是“任务详情”。多数已有 AP Identity shadow 任务也没有通过此 helper 提交。

### 2.3 Export helper

`ui/export_action_helper.py::submit_export_task()` 同样使用非模态 `QProgressDialog`：

- Export Process 的完整 finished event 可以到达 `on_finished`。
- Mesh 链路明细的 `payload.result.export_identity_diagnostics` 会经过该回调边界。
- helper 在完成时先关闭 progress dialog，再显示只含输出路径的成功 InfoBar/消息。
- controller 终态后释放，不保留 result；现有 Mesh 页面回调只读取输出路径。

它是当前最接近真实 diagnostics metadata 的公共入口，但“导出完成提示”不是统一 Job 详情，默认追加摘要会打扰普通用户，也无法覆盖 Background Job。

### 2.4 Dialog、页面和诊断目录

静态搜索未发现以下统一能力：

```text
Job 详情页
任务历史页
任务详情弹窗
统一后台任务结果面板
统一 progress dialog result area
通用诊断中心
```

`ui/dialogs/` 中的详情和历史弹窗均属于具体业务对象。`ui/diagnostics/` 当前只有纯 Python ViewModel，没有 Qt 宿主。各页面自行创建 manager、维护 job id/context 并在终态回调中刷新本页。

结论：**当前没有统一 Job 详情宿主，不建议强行接入业务页面。**

## 3. 任务结果流转路径

统一 JSONL finished event 的关键结构为：

```text
Worker result
  -> finished event.result
  -> BackgroundProcessManager / ExportProcessManager signal
  -> helper callback 或业务页面 slot
  -> 提取业务字段刷新页面
  -> 原始 event/result 引用结束
```

当前七类路径如下：

| 类型 | UI 接收位置 | result 如何使用 | 是否保留完整 result/metadata | 终态 UI | 当前能否安全展示摘要 |
| --- | --- | --- | --- | --- | --- |
| 普通 Background Job | manager signal；使用 helper 时进入 `BackgroundJobController` callback | 调用方自行提取 | 否；manager 和 helper 均在终态清理 | helper progress dialog 立即关闭；直接 manager 由页面更新状态 | 无统一入口；仅 callback 瞬时可见 |
| Export Job | `ExportProcessManager.finished`，使用 helper 时进入 `ExportTaskController.on_finished` | helper显示输出路径，页面可读取 payload | 否；Mesh diagnostics 只在 callback 边界短暂存在 | progress dialog 关闭，显示成功 InfoBar/消息 | 单次 Mesh export 技术上可转换，但不是统一 Job 详情 |
| Online MR 长任务 | `OnlineMrCollectorWorker` 内部 manager | 只提取 status/session_id，页面收到 completed(session_id) | 否；完整终态 result 不再向页面传播 | 页面更新实时状态，无公共 dialog | 不适合；长任务结果被兼容 facade 有意收窄 |
| AC 资源刷新 | `AcManagementPage._background_finished` | 本地变量提取 summary/resources/collection 后更新表格和状态 | 否；该任务当前不附加 identity diagnostics，业务 result 也不整体保留 | 页面状态标签和按钮恢复，无公共 dialog | 不应为展示改 AC 页面 |
| AC 光衰刷新 | 同一 AC 页面终态 slot | 提取 resources/optical_rows/collection | 否；`identity_shadow` 随局部 result 结束 | 页面状态标签和按钮恢复 | 不应改光衰表或业务判断 |
| 轨旁 AP 刷新/详情 | AC 页面聚合刷新；轨旁 service 页详情 manager | 聚合只取 rows；详情只取 matches 并打开既有对象详情 | 否；`identity_shadow/detail_identity_shadow` 均未消费 | 页面状态或业务详情弹窗 | 详情 shadow 尤其不能混入现有 AP 详情 |
| MR/Mesh 导入与解析 | Mesh QThread/process bridge、Online MR parse manager、Vehicle mapping dialog manager | 转为兼容对象后只读取计数、解析摘要或 mappings | 否；identity shadow 不进入页面状态 | 各业务页面自己的进度/状态 | 不应改链路表、图表、解析结果或 mapping 表 |

补充边界：

- Mesh 链路明细 Export Process 会在 `finished.result` 附加 `export_identity_diagnostics`，现有页面只读取 path。
- AC 扩展 preview/commit/refresh/save 才是 AC 领域当前附加 `identity_shadow` 的入口；它们同样经过 AC 页面本地终态 slot，页面只处理原业务字段，不保留 shadow。
- `OnlineMrAnalysisReportExporter.result_metadata` 属于兼容直接 exporter，不是当前 Online MR 页面默认报告入口，不能据此创建全局报告诊断入口。
- 直接 manager 调用没有 progress dialog；不能把“没有关闭弹窗”误判为存在结果宿主。

## 4. 可接入宿主候选

| 候选 | 优点 | 主要风险 | 默认关闭/普通用户 | 敏感信息与测试 | Qt 生命周期 | 阶段 8.3 适合度 |
| --- | --- | --- | --- | --- | --- | --- |
| `job_action_helper.py` 完成结果区域 | 已有 parent、job id 过滤、取消和 callback | 现有控件是标准 `QProgressDialog`，无结果区；大多数 diagnostics 任务不走 helper；全局修改会影响所有 helper 任务 | 可由双开关关闭；但不得默认弹摘要 | callback 中可立即转换；helper 单测较容易 | controller 终态立即释放，新增子窗需明确 parent/销毁 | 暂不直接接；只有目标任务已统一走 helper 后才可选 |
| `export_action_helper.py` 导出完成提示 | Mesh export 已有真实 metadata；公共 callback 边界清晰 | 只能覆盖 Export；InfoBar 只表达导出成功，混入风险会造成业务误解和默认打扰 | 必须独立 export-summary flag，默认隐藏 | 可在 callback 先过滤；禁止把 path/samples 传给摘要 | helper和InfoBar生命周期明确 | P1 备选，不作为阶段 8.3 的统一 P0 宿主 |
| BackgroundProcessManager 调用方页面 | 当前即可取得完整 event | 分散在 AC、轨旁、MR/Mesh 等页面；需多点接线，容易把诊断变成业务字段 | 难以统一权限和默认隐藏 | 每页重复过滤，泄漏风险最高 | 页面切换/销毁和并发 Job 各不相同 | 明确不适合 |
| 新增统一诊断中心页面 | 与业务页面隔离，可 internal-only | 当前没有全局事件源、历史或安全结果存储；为了填充页面会引入 event bus/持久化/跨局点残留 | 可默认隐藏 | 若保存完整 result 风险高；测试范围大 | 新页面、导航、生命周期和权限复杂 | 当前不适合最小实现 |
| 新增任务详情弹窗 | 单次、显式、非模态；可只接收 ViewModel；最符合任务语义 | 当前没有任务列表或统一“查看详情”启动点；单独造 dialog 无法覆盖真实任务 | 可完全隐藏，不自动弹出 | widget 不接触 raw result，最容易证明白名单 | parent + delete-on-close 可做到无 worker/timer | **未来首选**，但先决条件未满足 |
| 系统设置开发/诊断页 | 已有 internal-only/feature gate 能力 | 设置页不拥有单次 Job event；跨页面传递会导致结果保留和局点污染，语义也不匹配 | 普通用户可隐藏 | 需要新数据源，泄漏面扩大 | 长生命周期页面容易保留旧结果 | 不适合 |

## 5. 不建议接入的位置

阶段 8.3 及以后仍明确禁止：

1. 不在 AC FIT-AP 主表增加诊断列或入口。
2. 不在光衰表格增加诊断列，不把 identity 风险解释成光衰异常。
3. 不在轨旁 AP 主表或现有 AP 详情增加 shadow 内容。
4. 不在 MR/Mesh 链路表、图表、事件表增加 identity 字段。
5. 不在 Online MR 实时表、状态卡或实时日志增加诊断字段。
6. 不修改导出 workbook、Sheet、表头、首页或 sidecar。
7. 不修改报告 SQL、parser、resolver、Repository 或生产 result。
8. 不在任务完成时默认弹出诊断窗口；只能由维护人员显式打开。

## 6. 安全展示边界

未来宿主必须遵守以下数据路径：

```text
单次内存终态 event
  -> 立即取出 event.result
  -> DiagnosticsSummaryViewModel.from_job_result(...)
  -> 立即释放 raw event/result 引用
  -> 只读宿主仅接收 ViewModel
```

要求：

- 全局 kill switch 和 UI surface flag 必须同时开启；配置缺失即关闭。
- 普通用户、客户构建、权限不足和观测准入未通过时，不创建入口或 dialog。
- widget/dialog 构造函数不得接受 raw result、items、samples、evidence、warnings、error 或路径。
- 不提供“查看原始 JSON”“复制全部”“展开证据”或自由文本 warning。
- 不写数据库、设置、日志、剪贴板历史、缓存、导出或网络。
- diagnostics disabled/unavailable/failed 不改变原 Job/Export 终态和成功提示。
- 同一宿主只显示单次任务摘要，不跨 Job、AC、局点或来源累计。
- 关闭时释放 ViewModel；不新增 timer、worker、QProcess 或后台刷新。

## 7. 阶段 8.3 最小实现建议

### 7.1 当前准入结论

当前结论为 **hold**：暂不进入可见 UI 实现。原因不是 ViewModel 不完整，而是没有统一任务详情启动点，也没有不保存 raw result 的公共终态结果缝隙。

不得用以下方式绕过：

- 同时修改多个业务页面。
- 在 manager 中持久化完整 result 或导入 UI。
- 新增空壳诊断中心，再为它建立全局 raw event 总线。
- 将 Mesh export 的完成提示冒充统一 Job 详情。

### 7.2 未来获批后的最小形态

若后续先有一个明确的、只持有当前终态 event 的任务详情入口，阶段 8.3 推荐只实现：

```text
src/netconsole/ui/diagnostics/diagnostics_summary_dialog.py
src/netconsole/ui/job_result_detail_host.py              # 以最终批准宿主命名
tests/test_diagnostics_summary_dialog.py
tests/test_job_result_detail_host.py
```

其中：

1. host 是唯一可以接触终态 event 的 UI 边界，并立即创建 ViewModel。
2. dialog 只接受 `DiagnosticsSummaryViewModel`，非模态、有 parent、关闭即销毁。
3. 入口是显式“诊断摘要”动作，不自动弹出；disabled/not_collected 时不创建。
4. 不修改 `DiagnosticsSummaryViewModel`、manager、worker、业务页面、workbook 或数据库。
5. 只接一个真实且已批准的任务详情入口；若入口仍不存在，则继续延后。

`job_action_helper.py` 只有在相关 diagnostics 任务已通过该 helper 且产品明确批准它升级为任务详情入口后，才允许作为唯一接线文件。当前不能仅为覆盖率把 AC、轨旁、Online MR 或 Mesh import 改成 helper。

## 8. 测试策略

未来最小宿主至少覆盖：

1. 全局/UI flag 缺失或关闭时不创建入口和 dialog。
2. 宿主只把 event result 交给 ViewModel，之后不保留 raw event/result。
3. dialog 构造只接受 ViewModel，无法访问敏感字段。
4. items/samples/evidence/warnings/error、MAC/IP/name/path 不渲染、不进入 tooltip、日志或复制内容。
5. disabled/not_collected/unavailable/failed/redacted/not_supported/available 状态完整。
6. diagnostics 失败不改变 finished/failed/cancelled，不覆盖原成功提示。
7. dialog 非模态、带 parent、关闭后安全销毁，无 timer/worker/QProcess。
8. 同时完成两个 Job 时按 job_id 隔离，不显示旧任务或跨局点结果。
9. 普通用户和客户 profile 不可见，samples 开关仍不可启用。
10. 静态检查不修改业务页面、导出字段、workbook、SQL、parser 或 resolver。

## 9. 回滚策略

阶段 8.2 只有文档，回滚只需删除本轮文档增量。

未来宿主如获批实施，回滚顺序应为：

1. 关闭全局 kill switch 和 UI flag。
2. 移除唯一宿主的显式入口。
3. 删除 dialog/host，不回退 Job、Export 或业务代码。
4. 不迁移、不删除、不回填任何数据库或报告数据，因为宿主不得持久化。

## 10. 结论

当前项目没有统一 Job 详情页、任务历史页、统一结果面板或诊断中心。Manager 和两个 helper 都只管理运行期与瞬时终态，不能安全提供跨任务详情。

未来首选是“显式打开的单次任务详情诊断摘要弹窗”，且 dialog 只接收阶段 8.1 ViewModel；但在统一任务详情启动点获批前，阶段 8.3 可见 UI 实现应继续暂停。阶段编号推进不授权改业务页面、保存完整 result 或默认展示 diagnostics。

## 11. 2026-07-11 同步复核

本轮重新核对普通 Background Job、Export Process、Online MR 长会话、AC/FIT AP、轨旁和 MR/Mesh 调用链，未发现新增的统一任务详情/历史/诊断中心或安全结果保留层。各页面仍主要消费瞬时 progress/finished/error/cancelled 回调，Export finished metadata 也不构成跨任务详情存储。

因此阶段 8.3 结论保持 hold：未来入口若获批，只能显式、非模态地接收 `DiagnosticsSummaryViewModel`，不得接收或持久化 raw result；关闭后不得保留跨 Job、跨局点引用。本结论不授权新增 Qt 页面、Feature key、数据库或业务字段。
