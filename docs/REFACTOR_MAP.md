# 后台任务重构地图

## 1. 当前结论

截至 2026-07-12，NetConsole 已建立统一 Background Job 协议、独立 worker、进程适配器、Job Registry 和 11 个领域 handler 模块；Registry 当前注册 86 个任务类型。Traffic 的三个本地 handler 已直接调用正式 Adapter，但多数既有领域 handler 仍通过 `legacy_handler(...)` 调用 `src/netconsole/services/job_center/handlers/legacy_tasks.py`，因此总体状态仍是“入口与协议统一，领域实现迁移中”，不是“已完成”。

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
| AC/FIT AP 资源 | 页面提交 AC Job | ac domain handlers/service | 部分迁移 | 部分 | 资源、历史等 legacy 适配 | 按 task type 搬出纯领域实现 |
| FIT AP 光衰 | `ac_fit_ap_optical_refresh` Job | AC domain handler | 已迁移但保留兼容层 | 是 | 旧 service/helper 是回滚路径 | 先验证调用者再清兼容入口 |
| AP 扩展信息 | preview/commit/refresh/save Job | AC domain + identity adapter | 影子验证 | 旧业务已接管；identity 否 | 原写入 service + shadow metadata | 保持只读，等待观测结论 |
| 轨旁 AP 业务 | 轨旁聚合/详情 Job 与导出 | rail transit handler +专用 export | 部分迁移/影子验证 | 业务部分；identity 否 | lookup、缓存、legacy 聚合/详情 | 不改变旧结果前提下逐项拆分 |
| 配置采集 | snapshot/compare/collect Job | config domain handlers | 部分迁移 | 部分 | 多个任务 thin legacy | 补 handler 单测后迁出 legacy |
| 文件管理 | 页面后台导航/动作 | file domain handlers | 部分迁移 | 部分 | 导航与动作 legacy 适配 | 收敛路径与取消契约 |
| SNMP 查询/采集 | `snmp_query_execute` / `snmp_collection_execute` | snmp domain 正式 handler | 已完成 | 是 | 兼容 service/export 方法 | 保持请求/缓存契约，验证 frozen |
| SNMP MIB/产品数据 | 中心后台刷新/动作 | snmp domain handlers | 部分迁移 | 部分 | MIB/resource/product/data legacy | 分离资源库与请求采集后迁移 |
| 无线扫描/勘测 | 页面提交 wifi survey Job | wifi domain handlers | 部分迁移 | 部分 | 扫描/勘测动作 legacy | 核对设备/平台边界后拆分 |
| MR 原始日志分析 | import/rebuild/profile Job | mesh domain + parser/repository | 部分迁移 | 部分 | domain handler 仍有 legacy | 保留单文件 parsed DB 契约迁移 |
| Online MR 实时采集 | 页面会话 manager/worker | collection start/status/package handler +专用 runner | 部分迁移 | 部分 | 多会话/外部进程生命周期 | 不将长会话误改为一次性 Job |
| Online MR 离线解析 | `online_mr_parse` Job | online_mr domain handler/service | 已迁移但保留兼容层 | 是 | 映射/历史相关 legacy | 收口兼容入口，锁定 raw/parsed 契约 |
| 报告导出 | `submit_export_task` | ExportProcessManager/worker | 已完成主路径 | 是 | 少量兼容直接 exporter | 搜索外部调用者后再删除兼容方法 |
| Job Center | Qt/Python Adapter + TaskRuntime + TaskRepository + worker/registry | 七状态、Event Hub、持久快照、REST/WebSocket、外部 Agent Task 与 11 个 domain modules | 基础设施完成/领域部分迁移 | 任务中心是；领域逻辑否 | 独立 daemon、`legacy_tasks.py` 兼容区 | Traffic 已接；legacy 只迁出 |
| 统一 Traffic | `TrafficTestApplicationService` + Local/Agent Adapter + Supervisor | 本地/Agent iPerf/fping、任务映射、事件、运行索引、REST/专用 WebSocket/Vue 页面 | 阶段 4C 完成 | 是 | 原 Qt iPerf/Ping 页面、无独立 Controller daemon | 阶段 5 复用 Traffic 边界接 Online MR |
| FastAPI / Web Shell | Vue Dashboard/任务中心/Agent/Traffic、对应 API、OpenAPI、`--web-shell` | Application/API 与 Desktop Shell | 阶段 4C 完成 | 任务、Agent 与 Traffic | 无用户登录、正式 dist 发布打包 | 阶段 5 接 Online MR |
| Export Center | ExportJob + manager + worker | 27 通用 + 2 专用类型 | 已完成主路径 | 是 | 兼容直接导出入口 | 继续保证 tmp/原子替换/占用提示 |
| AP Identity | Job/Export finished metadata | canonical resolver + adapters + ViewModel | 影子验证 | 禁止接管 | 旧 matcher/lookup/写入仍生产使用 | 真实局点观测与单宿主批准前 hold |
| Feature Gate | 主窗口/页面 `FeatureGate` | `FeatureStatus + feature_registry.py` | 已完成 | 是 | 个别旧代码需持续搜索 | SNMP/无线勘测保持 DISABLED；新增能力默认登记 |
| 日志分页 | 日志页面/Repository 查询 | 现有分页入口 | 已完成当前需求 | 是 | 大日志策略需随数据量复核 | 保持查询分页，不回 UI 全量加载 |
| 自动清理 | 延时 `AppCleanupService` | 白名单日志/缓存/临时目录 | 已完成受控范围 | 是 | 手工磁盘清理是另一入口 | 不扩大到业务数据和数据库 |
| Go/CentOS/远程 Agent | Windows Go Agent + Python Agent Controller + Vue 管理页 | 配置、健康、能力、Typed Client、Traffic Adapter/Supervisor、任务事件/结果 | 阶段 4C Web 入口完成 | Agent 资源与 iPerf/fping 执行同步 | CentOS、主动注册、持久凭据、独立服务 | CentOS 独立规划 |

## 4. 当前非 Job Center 路径

以下路径并非遗漏，而是尚未统一：

- 单设备连接测试：`DeviceConnectionTestThread`。
- 批量连接测试：`BatchConnectionTestWorker`，默认并发 50、上限 200。
- 批量设备详情采集：`BatchCollectWorker`，默认并发 20、上限 50。
- Online MR 实时采集：页面编排多个会话 worker、fping/iPerf 外部进程和终端连接；生命周期不能简单替换成一次性 Job。
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

阶段 4C 已在阶段 4B-2 应用服务上增加 FastAPI Traffic 路由、按 Run 订阅的专用 WebSocket 和 Vue 流量测试页面，没有拆其他 `legacy_tasks.py`，也没有修改 Agent 协议。Online MR、原 Qt iPerf/Ping、设备/AC/FIT-AP/MESH、SNMP Center、无线勘测均未迁移。
