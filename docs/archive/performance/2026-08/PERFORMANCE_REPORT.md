# NetConsole 数据加载性能专项报告

日期：2026-08-21
基线：`github/main@f21b67df`
分支：`codex-A/perf-site-loading`
Change Impact：L4（SQLite 全局连接工厂、Renderer API Client、NcDataTable、Export/Artifact 消费者）

## 结论

- 已增加请求级 API、SQL、Repository 分段计时，以及 Renderer API、表格 DOM commit、局点切换阶段计时。
- FIT-AP 列表不再为全量结果读取详情版本投影，只为当前页 MAC 批量读取；详情、历史和导出入口保持原契约。
- 设备管理普通列表不再在分页前读取最多 1000 个任务和全部设备 facts，只读取当前页；连接状态筛选及采集状态/时间排序保留原全量语义。
- 轨旁 AP 普通文本、站点和异常筛选复用同一 revision snapshot；只有可规范化的完整 MAC 查询才扩展 Identity 查询键。
- 轨旁 AP 已有内存 snapshot cache、revision 校验和 single-flight，不新增数据库 read model。
- 轨旁 AP 导出已经在 Export Process 中完成 snapshot 构建、XLSX 渲染、进度、取消和完成通知，本次未重复建设。
- 在线表格同步已经在 Job Center 后台任务中执行，采用 WPS 异步提交、轮询、进度、取消和未完成批次恢复；当前缺少真实远端与大工作簿分阶段计时，本次不改变同步协议。
- 三个重点页面均为服务端分页，单页上限 200。当前证据不足以支持全局替换 NcDataTable 为虚拟表格；本次先把轨旁表固定列从 3 列降为 2 列。
- 局点切换已在详细数据加载前创建 metadata workspace，并新增分段计时；`<500ms` 仍需真实 Electron/局点验收，不能由单元测试替代。

## Profiling 契约

Backend 每个 HTTP 响应增加：

- `X-Request-ID`：请求关联 ID。
- `Server-Timing`：`app`、`sql`、`repository` 总耗时及 SQL 次数。
- 超过 250 ms 的请求写入 `API_PERFORMANCE_PROFILE`，包含状态码、总耗时、SQL 次数/耗时和命名 Repository 阶段；不记录 SQL 文本、参数或业务数据。

Renderer 控制台增加：

- `API_PERFORMANCE_PROFILE`：请求总耗时、request ID、Server-Timing。
- `UI_TABLE_PROFILE`：table ID、当前页行数、Vue nextTick 后首帧 commit 耗时。
- `SITE_SWITCH_PROFILE`：preflight、metadata workspace、activate、backend restart 分段耗时。

重点 Repository 阶段：

- FIT-AP：`ac.fit_ap.list_projection`
- 设备：`devices.groups`、`devices.station_metadata`、`devices.list`、`devices.page_tasks`、`devices.page_facts`
- 轨旁 AP：`trackside.business_snapshot`

## 小型隔离实测

在 `D:/study/test-data/NetConsole/<run-id>` 创建测试夹具，预热后各请求执行 10 次，以下为中位数。数据规模很小，只验证 profiling 可用和数量级，不代表生产局点。

| 请求 | API app | SQL | Repository |
| --- | ---: | ---: | ---: |
| FIT-AP，第 1 页/1 行 | 13.445 ms | 8.120 ms | 11.865 ms |
| 设备，名称排序，第 1 页/1 行 | 14.780 ms | 3.470 ms | 9.150 ms |
| 设备，连接状态排序，第 1 页/1 行 | 12.585 ms | 3.335 ms | 8.845 ms |
| 轨旁 AP，空业务快照 | 3.765 ms | 2.075 ms | 3.185 ms |

限制：

- 未读取或复制 `D:/NetConsoleData`、`D:/NetConsoleData-dev`。
- 未执行真实 AC、真实轨旁交换机或大局点数据库测试。
- 未执行 Electron DevTools Performance trace、长列表滚动 FPS 或真实局点切换计时。

## 分项分析

### 局点切换

现行顺序是 preflight -> metadata workspace -> activate -> backend restart。metadata workspace 会先进入目标局点的轻量设置页，详细业务页数据由重启后的页面请求加载，不在切换动作中等待 FIT-AP、轨旁 AP 或设备全量数据。

状态：实现了阶段 profiling，保留现有 rollback/确认语义；真实 `<500ms` 首屏目标为 PENDING。

### FIT-AP 资源

原路径在分页前读取资源、未认证 AP、光衰、LLDP/交换机上下文和全部详情版本。当前列表仍需在分页前计算站点、状态、模型和筛选项，以保持业务筛选与拓扑排序不变；详情版本改为当前页 MAC 批量读取。

状态：消除全量详情版本读取；未收窄旧 DTO，避免破坏现有页面和导出消费者。后续只有在真实 profiling 证明光衰/LLDP 投影仍为主热点时，才应设计兼容的新轻量 DTO。

### 设备管理

普通排序字段（名称、系统名、地址、站点、类型、更新时间）先完成设备本体排序和分页，再按当前页 UUID 批量读取 tasks/facts。以下场景保留原全量投影，确保排序/筛选语义不变：

- connection status 筛选
- `last_collected_at` 排序
- `last_collect_status` 排序
- `status` 排序

状态：普通首屏路径已优化；动态状态全量排序仍可由新的生产 profile 决定是否需要 Repository 级 SQL 投影。

### 轨旁 AP 业务

业务 snapshot 由基础资料、规划、设备、LLDP、FIT-AP 和 Identity revision 共同确定。现有缓存以来源 revision 和 Identity 查询 MAC 为键。此前普通文本也被放入 Identity 查询键，导致每个搜索词创建不同 snapshot；现仅完整 MAC 查询扩展键。

状态：修复无效 cache miss；不改变 Identity normalizer、matched/unresolved/ambiguous 规则、站点作用域或业务阈值。

### 导出

轨旁 AP 业务导出当前链路：

`Renderer -> Export Task(job_id) -> Export Process -> frozen snapshot -> XLSX Artifact -> Task Center/完成通知`

已确认支持 progress、cancel、临时文件清理、Artifact、`snapshot_build_ms` 和 `export_render_ms`。Renderer 不生成工作簿，也不把当前页作为导出事实源。

状态：已有能力满足本专项要求，本次只做回归验证。

### 在线表格同步

现有轨旁 AP WPS 同步链路：

`Renderer -> Job Center(task_id) -> frozen snapshot -> local XLSX -> Workbook DTO -> WPS async submit -> remote poll -> persisted summary/notification`

同步不在 Renderer/UI 线程执行，已有 `task_id`、阶段进度、取消检查、远端任务状态持久化和未完成批次恢复。静态审计发现本地构建会先渲染一次 XLSX，再分别读取工作簿 DTO 和格式清单；这是可测量的候选热点，但当前没有真实大工作簿阶段计时，不能据此判定它是用户所见慢的主因。远端提交、轮询和 WPS 脚本执行同样可能占主要耗时。

状态：异步链路满足不阻塞 UI 的要求；本轮不修改协议、冻结快照、工作簿字段或 WPS 脚本。下一步应在真实授权环境分别记录 snapshot、XLSX render、DTO/format parse、payload serialize、remote submit、remote wait 和 remote execute 耗时，再决定是否合并本地两次工作簿读取。

### 大表

FIT-AP、设备和轨旁 AP 均为服务端分页，最大 200 行。直接在共享 NcDataTable 引入 virtual scroll 会影响选择、列宽、固定列、上下文菜单和多个消费者，当前缺少 DOM/滚动证据。此次仅减少轨旁固定列，且新增统一表格 commit profiling。

状态：减少固定列完成；virtual scroll 为 NOT IMPLEMENTED，需以真实 200 行 Electron trace 证明必要性后再进入独立 L3 任务。

## 验收状态

| 目标 | 自动证据 | 状态 |
| --- | --- | --- |
| API/SQL/Repository profiling | Middleware、连接包装、响应头及测试 | PASS |
| 前端 API/表格渲染 profiling | Vitest 与 Renderer 全量测试 | PASS |
| FIT-AP 当前页详情批量加载 | Query Service 回归测试 | PASS |
| 设备当前页 facts/tasks | API 回归测试 | PASS |
| 轨旁普通查询 snapshot 复用 | cache-key 回归测试 | PASS |
| 轨旁 Export Process/progress/cancel | 既有导出契约测试 | PASS |
| 在线表格异步 submit/poll/progress/cancel/resume | Job Center 与 WPS 定向测试/静态调用链 | PASS |
| 固定列减少 | 轨旁页面测试 | PASS |
| 局点切换 <500ms | 真实 Electron/局点未执行 | PENDING |
| 真实大表滚动/冻结体验 | Electron DevTools 未执行 | PENDING |
| 真实 Excel/WPS 打开 | 未执行 | PENDING |
| 真实 WPS 远端分阶段耗时 | 未连接真实云端 | PENDING |

## 自动化验证

- Python 定向领域/导出套件：`188 passed`；请求 ID 回归子集：`38 passed`。
- 最终 L4 Full Gate：Renderer `175 files / 1206 tests passed`，typecheck/build 通过；Electron `34 files / 279 tests passed`，typecheck/build 通过。
- 最终 Python 全量：`4456 passed, 2 skipped, 1 failed`。唯一失败为 `tests/test_database.py::test_demo_context_creates_demo_data_once_with_connection_and_snmp_examples` 的 LLDP 历史行数断言；该失败已在干净基线 `f21b67df` 独立复现，为基线既有失败，不在本专项修改业务逻辑。
- Architecture Guard：`13/13 passed`；主线 contract smoke：`12 passed`；Ruff、文档路径门和 `git diff --check` 通过。
- Full Gate 总状态为 `FAIL`，原因仅为上述已确认基线失败；不能把其余 suite 通过写成完整 Gate PASS。

真实 Electron GUI、真实局点、真实 WPS 远端、Excel/WPS 打开和 `<500ms` 局点切换均保持 PENDING。

## 数据与兼容性

- 未修改 AP Identity 规则。
- 未修改数据库 schema 或事实表。
- 未删除历史数据。
- 未修改设备命令、轨旁业务阈值、导出字段或 revision 契约。
- 未访问生产数据根。
