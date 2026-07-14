# 后台任务重构地图

## 1. 当前结论

截至 2026-07-14，NetConsole 已建立统一 Background Job 协议、独立 worker、进程适配器、Job Registry 和 11 个领域 handler 模块；Registry 当前注册 89 个任务类型。Traffic 的三个本地 handler、Online MR Agent 包同步/导入两个 handler 与 AC Mesh-Link 白名单刷新 handler 已直接调用正式 Service/Adapter，但多数既有领域 handler 仍通过 `legacy_handler(...)` 调用 `src/netconsole/services/job_center/handlers/legacy_tasks.py`，因此总体状态仍是“入口与协议统一，领域实现迁移中”，不是“已完成”。

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
| 轨道交通基础资料 | Qt AP 扩展/设备资料；Web 只读查询与导入预览 | `RailTransitBaseDataQueryService` + GET API + 非持久化 preview | 5C-6 已增加站点/区间派生、轨旁 AP、列车/MR、质量问题和导入预览 | Web 只读是；正式写入否 | Qt 编辑/正式导入仍保留；AP Identity 不接管 | 先做真实局点只读验收，再单独设计受控写入 |
| 配置采集 | snapshot/compare/collect Job | config domain handlers | 部分迁移 | 部分 | 多个任务 thin legacy | 补 handler 单测后迁出 legacy |
| 文件管理 | 页面后台导航/动作 | file domain handlers | 部分迁移 | 部分 | 导航与动作 legacy 适配 | 收敛路径与取消契约 |
| SNMP 查询/采集 | `snmp_query_execute` / `snmp_collection_execute` | snmp domain 正式 handler | 已完成 | 是 | 兼容 service/export 方法 | 保持请求/缓存契约，验证 frozen |
| SNMP MIB/产品数据 | 中心后台刷新/动作 | snmp domain handlers | 部分迁移 | 部分 | MIB/resource/product/data legacy | 分离资源库与请求采集后迁移 |
| 无线扫描/勘测 | 页面提交 wifi survey Job | wifi domain handlers | 部分迁移 | 部分 | 扫描/勘测动作 legacy | 核对设备/平台边界后拆分 |
| MR 原始日志分析 | import/rebuild/profile Job | mesh domain + parser/repository | 部分迁移 | 部分 | domain handler 仍有 legacy | 保留单文件 parsed DB 契约迁移 |
| Online MR 实时采集 | Legacy Qt 页面通过兼容 Adapter 调用 LOCAL 生命周期，并可在独立对话框同步、匹配、下载和导入 Agent 已有包；Web 提供只读实时展示 | collection Application Service + Agent contract/typed download/import/controller + Qt Job 入口 + GET-only Query API | 5C-2 已接入 Web 状态、预览和 raw tail，远程执行仍未启用 | LOCAL 生命周期是；Web 只读是；Agent 仅已有包同步/导入 | 页面自管 Traffic 兼容方法、Agent start/stop/status 自动同步、Web 启停、离线解析接入 | 保持 Qt 启停与 Web 只读边界，再单独设计远程 start/status/stop |
| Online MR 离线解析 | `online_mr_parse` Job | online_mr domain handler/service | 已迁移但保留兼容层 | 是 | 映射/历史相关 legacy | 收口兼容入口，锁定 raw/parsed 契约 |
| 报告导出 | `submit_export_task` | ExportProcessManager/worker | 已完成主路径 | 是 | 少量兼容直接 exporter | 搜索外部调用者后再删除兼容方法 |
| Job Center | Qt/Python Adapter + TaskRuntime + TaskRepository + worker/registry；Web 使用独立只读 Query Service | 七状态、Event Hub、持久快照、REST/WebSocket、GET-only Web 监控、外部 Agent Task 与 11 个 domain modules | 5C-3 已完成只读 Web 列表/详情/日志 tail；领域仍部分迁移 | 任务中心是；Web 查询是；领域逻辑否 | 既有 `/api/tasks` 兼容接口、独立 daemon、`legacy_tasks.py` 兼容区 | Web 保持无 stop/delete/retry；legacy 只迁出 |
| 统一 Traffic | `TrafficTestApplicationService` + Local/Agent Adapter + Supervisor | 本地/Agent iPerf/fping、任务映射、事件、运行索引、REST/专用 WebSocket/Vue 页面 | 阶段 4C 完成 | 是 | 原 Qt iPerf/Ping 页面、无独立 Controller daemon | 阶段 5 复用 Traffic 边界接 Online MR |
| FastAPI / Web Shell | Vue Dashboard/只读任务中心/Agent/AC/Traffic/Online MR/轨道交通基础资料、对应 API、OpenAPI、`--web-shell`、普通主程序托盘 Web 控制台 | Application/API、Desktop WebHost 与临时本地会话 | 阶段 5C-6 已增加基础资料 GET API 和唯一非持久化 import-preview POST | 任务、Agent、Traffic、AC 查询、Mesh-Link 刷新、基础资料只读查询 | Online MR Web 启停、基础资料正式写入、其他 AC 写操作、统一用户登录 | 继续从低风险页面迁移，不扩大命令或写入边界 |
| Export Center | ExportJob + manager + worker | 27 通用 + 2 专用类型 | 已完成主路径 | 是 | 兼容直接导出入口 | 继续保证 tmp/原子替换/占用提示 |
| AP Identity | Job/Export finished metadata | canonical resolver + adapters + ViewModel | 影子验证 | 禁止接管 | 旧 matcher/lookup/写入仍生产使用 | 真实局点观测与单宿主批准前 hold |
| Feature Gate | 主窗口/页面 `FeatureGate` | `FeatureStatus + feature_registry.py` | 已完成 | 是 | 个别旧代码需持续搜索 | SNMP/无线勘测保持 DISABLED；新增能力默认登记 |
| 日志分页 | 日志页面/Repository 查询 | 现有分页入口 | 已完成当前需求 | 是 | 大日志策略需随数据量复核 | 保持查询分页，不回 UI 全量加载 |
| 自动清理 | 延时 `AppCleanupService` | 白名单日志/缓存/临时目录 | 已完成受控范围 | 是 | 手工磁盘清理是另一入口 | 不扩大到业务数据和数据库 |
| Go/CentOS/远程 Agent | Windows Go Agent + Python Agent Controller + Vue 只读控制中心 | 配置、健康、能力、Typed Client、远端状态/工具/任务/日志/采集包查询、Traffic Adapter/Supervisor、本机维护自检 | 阶段 5B-12A localhost 自检通过 | Agent 资源、只读监控与 iPerf/fping 执行同步 | CentOS、主动注册、持久凭据、独立服务、远程 MR 控制 | 远程控制另行设计，不以本机结果代替现场验收 |

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

阶段 5C-5 复用既有 AC Mesh-Link parser 和 `vehicle_mr_online.sqlite`，增加快照、MR 状态、轨旁 AP 匹配、过期判定和 Vue 在线监控。阶段 5C-5A 增加唯一 `POST /api/ac-management/mesh-links/refresh`：Web 只创建 Task，Worker 从当前局点读取凭据并固定执行 `screen-length disable`、`display clock`、`display wlan mesh-link ap`，可选读取 switch-history；raw 经 staging 原子落盘，结构化快照事务提交，失败保留旧快照。阶段 5C-6 复用 `devices.db` 中 AP 扩展点位和设备资料，增加只读基础资料页面、质量检查与唯一非持久化 `import-preview` POST，不创建 Task、不连接设备、不写正式资料。旧快照没有 raw 时仍明确返回不可用，也不在轨道交通契约中引入客户端数量。

阶段 4C 已在阶段 4B-2 应用服务上增加 FastAPI Traffic 路由、按 Run 订阅的专用 WebSocket 和 Vue 流量测试页面，没有拆其他 `legacy_tasks.py`，也没有修改 Agent 协议。阶段 5B-3 至 5B-5 收口 Online MR LOCAL 生命周期并接入 Legacy Qt；阶段 5B-6 固化 Agent 契约，5B-7 增加安全 ZIP importer，5B-8 增加类型化查询、受控下载和 importer 编排，5B-9 增加维护脚本与 Controller 手工下载/导入门面，5B-10 复用既有 Agent Profile，增加只读包同步、局点静态设备 IP 候选和高层导入入口，5B-11 将该能力通过两个 Job 接入 Legacy Qt。阶段 5C-0 增加按需 Desktop WebHost、托盘入口、WebEngine fallback、本地临时会话和前端发布打包；阶段 5C-1 增加 Agent 远端状态、工具、任务、日志和采集包的只读控制中心；阶段 5B-12A 增加仅限 localhost 的 fping/iPerf 维护自检并完成本机真实 Agent 冒烟；阶段 5C-2 增加 Online MR GET-only API、当前/最近会话、采集器、轻量 view 预览和 raw 白名单尾部页面；阶段 5C-3 复用 `tasks.db` 事实源，增加 `mode=ro + query_only` 的 Web 查询边界、任务详情、结构化日志 tail 和 Online MR 关联跳转；阶段 5C-4 复用既有 AC Repository、光衰 severity 与配置裁剪/diff，增加 `devices.db` 只读查询、FIT-AP 后端分页、Mesh Radio 1/2 详情和配置分块查看，且不在轨道交通资源契约中暴露客户端数量。当前 Web 不调用设备连接、采集、固化 AP、`save force`、远程登录或任意命令接口，也未启用 AGENT executor、远程 MR start/stop、Online MR Web 启停或离线解析接入；本阶段没有修改 Go Agent、LOCAL 生命周期、AC 命令、SNMP Center 或无线勘测。
