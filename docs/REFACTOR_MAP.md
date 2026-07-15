# 后台任务重构地图

## 1. 当前结论

截至 2026-07-15，NetConsole 已建立统一 Background Job 协议、独立 worker、进程适配器、Job Registry 和 11 个领域 handler 模块；Registry 当前注册 89 个任务类型。Traffic 的三个本地 handler、Online MR Agent 包同步/导入两个 handler 与 AC Mesh-Link 白名单刷新 handler 已直接调用正式 Service/Adapter，Online MR 5B-13A/13B 已增加默认关闭的单 Agent 远端执行器和 Desktop WebHost 控制入口。Phase 0.5 第一批进一步把 18 个正式 FastAPI Router 的静态边界债务清零，但多数既有领域 handler 仍通过 `legacy_handler(...)` 调用 `src/netconsole/services/job_center/handlers/legacy_tasks.py`，因此总体状态仍是“入口与协议统一，领域实现迁移中”，不是“已完成”。

长期界面路线已调整为 Python Core + FastAPI 永久业务层、Vue 永久主界面、Electron 最终桌面外壳，Qt 仅作迁移与回退。该决定不改变本表的当前生产事实；任务迁移应优先形成可被 FastAPI 与迁移期 Qt 共用的 Application Service，详见 [下一代架构](ARCHITECTURE_NEXT.md)。

## 2. 状态定义

| 状态 | 判定标准 |
| --- | --- |
| 已完成 | 生产调用链使用正式领域 handler/service；有取消、进度、终态和测试；旧实现已收口 |
| 部分完成 | 已进入 Registry/worker，但领域 handler 仍薄适配 legacy，或同类页面仍有专用线程路径 |
| 未开始 | 仍在 UI 主线程执行长任务，或没有统一任务/导出协议 |
| 保留兼容 | 旧入口仍存在但不再是当前主要 UI 路径，删除前需验证外部调用者 |

## 3. 生产路径状态表

| 领域 | 当前生产入口 | 新架构入口 | 当前状态 | 是否已接管 | 遗留路径 | 下一步 |
| --- | --- | --- | --- | --- | --- | --- |
| 设备管理 CRUD/分组 | 页面提交后台 mutation/list Job | device domain handlers | 部分迁移 | 部分 | 若干 handler 仍 thin legacy | 逐任务下沉 service 并收口旧函数 |
| 设备批量连接 | `BatchConnectionTestWorker` | 尚无进程 Job | 尚未迁移 | 否 | QThread + 线程池 | 先保留逐设备进度/取消再评估迁移 |
| 设备批量采集 | `BatchCollectWorker` | 尚无进程 Job | 尚未迁移 | 否 | QThread + 线程池 | 保留失败隔离与阶段进度后再评估 |
| AC/FIT AP 资源 | Qt 页面提交 AC Job；Web 查询 SQLite，Mesh-Link 刷新提交白名单 Task | ac domain handlers/service + Web Query API + `ac_mesh_link_refresh` | 5C-4 已增加资源只读页；5C-5 已增加 Mesh-Link 监控；5C-5A 已增加固定 `display` 命令、raw 和原子快照闭环 | Mesh-Link 刷新与查询是；其他采集部分 | 资源、历史等 legacy 适配；写操作仍 Qt | 保持唯一受控刷新入口，AC 配置操作继续 Qt |
| FIT AP 光衰 | `ac_fit_ap_optical_refresh` Job | AC domain handler | 已迁移但保留兼容层 | 是 | 旧 service/helper 是回滚路径 | 先验证调用者再清兼容入口 |
| AP 扩展信息 | preview/commit/refresh/save Job | AC domain + identity adapter | 影子验证 | 旧业务已接管；identity 否 | 原写入 service + shadow metadata | 保持只读，等待观测结论 |
| 轨旁 AP 业务 | 轨旁聚合/详情 Job 与导出 | rail transit handler +专用 export | 部分迁移/影子验证 | 业务部分；identity 否 | lookup、缓存、legacy 聚合/详情 | 不改变旧结果前提下逐项拆分 |
| 轨道交通基础资料 | Qt AP 扩展/设备资料；Web 查询、问题治理、预览和受控导入审计 | Query/Preview/Import Service + Guard + 受控 API | 5C-6B 已增加运行态预览、人工决策、备份、事务、脱敏审计、幂等和冲突回滚 | 默认只读；副本可授权写入；真实局点未授权 | Qt 编辑仍保留；AP Identity 不接管；无删除/通用更新 | 先在副本持续验收，真实局点写入必须单独授权 |
| 在线列车车地通信检测 | Web 按列车分别展示 MR-CT/MR-TC、Mesh-Link、Online MR、fping/iPerf、任务和包；MR 详情以独立页签受控 LOCAL/AGENT 启停 | 只读聚合 Query Service + LOCAL/AGENT Web Control Service + Vue | 5C-10A LOCAL 已接入；5B-13B AGENT Fake 全链路已通过 | 聚合与控制代码是；两项现场验收冻结 | Web 无强停/删除/命令；正式分析/报告未接入 | 列车上电后分别执行 5C-10A-B 与 5B-13A-A |
| 轨道交通无线综合看板 | Web 聚合基础资料、FIT-AP/光衰、Mesh-Link、列车通信、Online MR、任务、Agent 缓存和 Mesh 分析 | `WirelessDashboardQueryService` + GET-only API + Vue | 5C-9 已增加只读总览、既有告警映射、数据时效和分层刷新 | 是，只读 | 详情和所有控制继续由原页面承担 | 保持无设备连接、无新阈值、无写入边界 |
| 配置采集 | snapshot/compare/collect Job | config domain handlers | 部分迁移 | 部分 | 多个任务 thin legacy | 补 handler 单测后迁出 legacy |
| 文件管理 | 页面后台导航/动作 | file domain handlers | 部分迁移 | 部分 | 导航与动作 legacy 适配 | 收敛路径与取消契约 |
| SNMP 查询/采集 | `snmp_query_execute` / `snmp_collection_execute` | snmp domain 正式 handler | 已完成 | 是 | 兼容 service/export 方法 | 保持请求/缓存契约，验证 frozen |
| SNMP MIB/产品数据 | 中心后台刷新/动作 | snmp domain handlers | 部分迁移 | 部分 | MIB/resource/product/data legacy | 分离资源库与请求采集后迁移 |
| 无线扫描/勘测 | 页面提交 wifi survey Job | wifi domain handlers | 部分迁移 | 部分 | 扫描/勘测动作 legacy | 核对设备/平台边界后拆分 |
| MR 原始日志分析 | Qt import/rebuild/profile Job；Web 只读查看既有结果 | mesh domain + parser/repository + GET-only Query API + Vue | 5C-8 已增加来源、主备链路、时间线、切换、RSSI、空口、异常、AP 统计和 artifact 受控访问 | Qt 分析部分；Web 查询是 | domain handler 仍有 legacy；Web 不重解析、不生成报告 | 保留单文件 parsed DB 和既有规则，控制面继续 Qt/Job |
| Online MR 实时采集 | Legacy Qt 与 Desktop WebHost 调用同一 Application Service；LOCAL/AGENT 分派到隔离 executor | collection Application Service + LOCAL/AGENT Executor + 两个 Web Control Service + 单例 API Facade + Qt Adapter + Query API | 5B-13B 已增加独立 AGENT 页签和回环 Fake 闭环；Phase 0.5 已收口三个 Router 的无副作用当前局点边界 | LOCAL 生命周期、Agent Service 与 Web Agent 代码闭环是 | 无 Agent 强停、多 Agent、自动解析/报告；真实验收冻结 | 列车上电后执行 5C-10A-B 与 5B-13A-A，不用 Fake 代替 |
| Online MR 离线解析 | `online_mr_parse` Job | online_mr domain handler/service | 已迁移但保留兼容层 | 是 | 映射/历史相关 legacy | 收口兼容入口，锁定 raw/parsed 契约 |
| 报告导出 | `submit_export_task` | ExportProcessManager/worker | 已完成主路径 | 是 | 少量兼容直接 exporter | 搜索外部调用者后再删除兼容方法 |
| Job Center | Qt/Python Adapter + TaskRuntime + TaskRepository + worker/registry；Web 使用独立只读 Query Service | 七状态、Event Hub、持久快照、REST/WebSocket、GET-only Web 监控、外部 Agent Task 与 11 个 domain modules | 5C-3 已完成只读 Web 列表/详情/日志 tail；领域仍部分迁移 | 任务中心是；Web 查询是；领域逻辑否 | 既有 `/api/tasks` 兼容接口、独立 daemon、`legacy_tasks.py` 兼容区 | Web 保持无 stop/delete/retry；legacy 只迁出 |
| 统一 Traffic | `TrafficTestApplicationService` + Local/Agent Adapter + Supervisor + 单例 `TrafficWebApplicationService` | 本地/Agent iPerf/fping、任务映射、事件、运行索引、REST/专用 WebSocket/Vue 页面 | 阶段 4C 完成；Phase 0.5 已收口执行端、分页、取消/重试与共享 presentation 映射 | 是 | 原 Qt iPerf/Ping 页面、无独立 Controller daemon | 阶段 5 复用 Traffic 边界接 Online MR |
| Launcher / FastAPI / Desktop Shell | `main.py --mode auto|qt|web|server`、兼容 Qt Web Shell；Electron 源码入口 `apps/desktop_electron` | Core-owned FastAPI、Qt 短期 Cookie、Electron 动态端口/临时令牌、唯一 Vue Renderer | Launcher 四模式与 Phase 0.5 组合根已完成；Electron 已有安全窗口、main/preload、Python supervisor、Vue 双 Adapter 和源码开发/生产资源冒烟 | 生命周期基础是；Electron 安装发布、托盘/升级和业务替换否 | Qt 默认入口、页面级 Task Service、权限/审计、完整纵向业务与真实验收 | 保持 Qt Legacy 回退；按固定纵向闭环顺序迁移，安装发布另立任务 |
| Export Center | ExportJob + manager + worker | 27 通用 + 2 专用类型 | 已完成主路径 | 是 | 兼容直接导出入口 | 继续保证 tmp/原子替换/占用提示 |
| AP Identity | Job/Export finished metadata | canonical resolver + adapters + ViewModel | 影子验证 | 禁止接管 | 旧 matcher/lookup/写入仍生产使用 | 真实局点观测与单宿主批准前 hold |
| Feature Gate | 主窗口/页面 `FeatureGate` | `FeatureStatus + feature_registry.py` | 已完成 | 是 | 个别旧代码需持续搜索 | SNMP/无线勘测保持 DISABLED；新增能力默认登记 |
| 日志分页 | 日志页面/Repository 查询 | 现有分页入口 | 已完成当前需求 | 是 | 大日志策略需随数据量复核 | 保持查询分页，不回 UI 全量加载 |
| 自动清理 | 延时 `AppCleanupService` | 白名单日志/缓存/临时目录 | 已完成受控范围 | 是 | 手工磁盘清理是另一入口 | 不扩大到业务数据和数据库 |
| Go/CentOS/远程 Agent | Windows Go Agent + Python Agent Controller + Vue 控制中心 | 配置、健康、能力、Typed Client、远端状态/工具/任务/日志/采集包查询、Traffic Adapter/Supervisor、Online MR Agent Executor/Web Adapter | 阶段 5B-13B 回环 Fake Agent 正式 HTTP/下载/导入闭环已通过 | Agent 资源、iPerf/fping 与单 Agent MR 代码闭环 | CentOS、主动注册、持久凭据、独立服务、多 Agent MR | 5B-13A-A 真实验收冻结；Fake 不替代现场验收 |

## 4. 当前非 Job Center 路径

以下路径并非遗漏，而是尚未统一：

- 单设备连接测试：`DeviceConnectionTestThread`。
- 批量连接测试：`BatchConnectionTestWorker`，默认并发 50、上限 200。
- 批量设备详情采集：`BatchCollectWorker`，默认并发 20、上限 50。
- Online MR 实时采集：页面仍编排多会话显示和 Qt 兼容句柄，但 LOCAL 生命周期、Traffic 和 SSH 子任务由 Application Service/Worker 统一管理；不能简单替换成一次性 Job。
- 少量兼容导出 service 仍可直接写文件，但当前正式页面导出应走 Export Process。

这些路径若要迁移，必须先保留逐设备/逐会话进度、取消、失败隔离和现有用户交互，不能只替换类名。

## 5. 迁移顺序

1. 按领域从 `legacy_tasks.py` 搬移纯业务函数，保持 task type 和结果契约不变。
2. 为每个迁移 handler 补齐取消检查、阶段进度、错误 code 和直接单元测试。
3. 核对页面只依赖 `BackgroundProcessManager` 与稳定结果，不读取 worker 私有文件。
4. 验证冻结态 `--background-worker --job` 与源码态 `python -m netconsole.background_worker --job`。
5. 搜索并删除已无生产调用者的 compatibility re-export/legacy 函数；无法证明无调用者时保留并标记。
6. 最后评估专用线程是否值得迁移，不能与领域 handler 拆分混成一次高风险改动。

## 6. 完成标准

一个任务只有同时满足以下条件才可标记“已完成”：

- Registry 中 task type 唯一且领域归属清晰；
- handler 不再反向调用对应 legacy 实现；
- 生产页面走统一 manager；
- 进度、取消、失败、异常退出和清理经过测试；
- stdout JSONL 协议未被普通 print 污染；
- 数据/临时文件位于 PathResolver 管理目录；
- 文档、变更记录和代码搜索结果同步；
- 冻结态 smoke 验证通过。

## 7. 当前阶段边界

阶段 5C-5 复用既有 AC Mesh-Link parser 和 `vehicle_mr_online.sqlite`，增加快照、MR 状态、轨旁 AP 匹配、过期判定和 Vue 在线监控。阶段 5C-5A 增加唯一 `POST /api/ac-management/mesh-links/refresh`：Web 只创建 Task，Worker 从当前局点读取凭据并固定执行 `screen-length disable`、`display clock`、`display wlan mesh-link ap`，可选读取 switch-history；raw 经 staging 原子落盘，结构化快照事务提交，失败保留旧快照。阶段 5C-6 复用 `devices.db` 中 AP 扩展点位和设备资料，增加只读基础资料页面与质量检查。阶段 5C-6A 将正式资料、导入来源和运行态分层，增加实体问题分组、精确匹配和字段级合并计划。阶段 5C-6B 增加 15 分钟运行态预览、Feature/环境/目标范围 Guard、人工决策、数据库哈希乐观锁、SQLite 备份、单事务写入、脱敏审计、幂等和冲突保护回滚；副本可显式授权，真实局点仍未授权。阶段 5C-7A 再以 GET-only 聚合服务统一展示列车、CT/TC、Mesh-Link、Online MR、fping/iPerf、任务和采集包。阶段 5C-8 增加只读 Mesh 分析 Web 页面，阶段 5C-9 将既有只读结果聚合为无线综合看板。阶段 5C-10A 在列车通信 MR 详情中增加默认关闭的 LOCAL start/normal stop：严格要求 Desktop、`127.0.0.1`、短期 Cookie 和当前局点，复用 ApplicationService 全生命周期，不开放 Web 强停或 Agent 执行。真实设备尚未在本阶段自动连接，需 5C-10A-A 单独授权验收。

阶段 4C 已在阶段 4B-2 应用服务上增加 FastAPI Traffic 路由、按 Run 订阅的专用 WebSocket 和 Vue 流量测试页面。阶段 5B-3 至 5B-5 收口 Online MR LOCAL 生命周期并接入 Legacy Qt；阶段 5B-6 至 5B-13A 固化 Agent 契约、包同步/导入和单 Agent executor；阶段 5B-13B 增加独立 Web AGENT 页签与回环 Fake 验收。阶段 5C-10A 的 LOCAL 与 5B-13B 的 AGENT 控制都默认关闭，只提供正常停止，不接受命令、URL、路径或凭据字段，也不修改 MR 命令、Traffic flush、raw、Go Agent、AC、SNMP Center 或无线勘测。

Phase 0.5 第一批 A-D/E 只收口 API/Application 边界：三个 Online MR Router 复用单例 Facade，Traffic Router 复用单例 Web Application Service，基础资料策略复用既有 Import Service，配置与 Network Tools 只接受组合根注入，正式 Router 不再直接依赖 SQLite 异常。Task/Agent/Traffic/LocalProcessAdapter/Online MR Application 单例和原关停预算保持不变，未引入新的运行容器。
