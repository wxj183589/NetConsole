# API / Application 边界审计

> 历史审计记录：本文保留 2026-07-15/16 当时的范围和结论。v1.3.9 后续已正式删除 SNMP Center、通用 MIB/OID 平台和无线勘测；文中的 `EXCLUDED / FUTURE_REBUILD` 不再代表当前产品状态。

## 1. 目的与基线

本审计用于确认 FastAPI 只承担传输层职责，不成为新的业务层。目标调用链为：

```text
Vue / Electron
  -> FastAPI Router
  -> Application Service / Query Service
  -> Repository / Infrastructure / Device Adapter
```

初始审计基线为 2026-07-15 的 `main@dc62324cf7a61bb9e8abbcdb144f97543e04ad68`；Phase 0.5 第一批以 `29624b2c` 为集成基线，完成 A-D 领域收口与 E 中央接线，覆盖 `src/netconsole/backend/api/` 下全部 18 个 `*_router.py`。SNMP Center 与无线勘测保持 `EXCLUDED / FUTURE_REBUILD`，不在本轮范围内。

该历史结论只表示当时第一批 Router 静态边界和定向契约已收口，不表示所有领域 Service 或真实设备验收已完成。Qt 退出状态以当前架构与最终迁移矩阵为准。

## 2. 判定口径

Router 允许：

- DTO、Query、上传大小和输入格式校验；
- 鉴权、Feature Gate、loopback/Desktop session 等信任边界校验；
- 从 `request.app.state` 获取 Application/Query Service；
- 调用公开 Service 用例并映射响应或稳定错误；
- 在 Service 已完成路径解析、白名单和权限校验后返回 `FileResponse`；
- WebSocket 连接、游标、心跳和事件转发等传输逻辑。

Router 禁止：

- 直接连接 SQLite、执行 SQL 或操作 Repository；
- 直接读写、复制、压缩或解析业务文件；
- 直接连接设备或调用 SSH、Telnet、SNMP、Agent HTTP 等基础设施；
- 调用 Parser、计算业务规则或维护第二套 Task/Session 状态机；
- 绕过公开 Application Service，访问其内部组件或在 API 层完成用例编排。

状态定义：

| 状态 | 含义 |
| --- | --- |
| `PASS` | Router 只做传输、信任边界、Service 调用和响应映射；未发现直接 I/O 或业务编排。 |
| `WARNING` | 当前调用仍经过 Service，但存在 Router 自行组装 Service、跨 Router 私有依赖等边界债务。 |
| `REFACTOR_REQUIRED` | Router 已直接触发有副作用的基础设施 Helper，或承担业务策略、查询/控制用例编排；进入功能对等开发前应下沉。 |

Router 不再直接依赖 `sqlite3` 异常类型；共享 API 错误映射统一把存储与 I/O 异常转换为既有 HTTP 状态和消息。

## 3. 总体结论

| 项目 | 结果 |
| --- | --- |
| Router 总数 | 18 |
| `PASS` | 18 |
| `WARNING` | 0 |
| `REFACTOR_REQUIRED` | 0 |
| 直接 Repository import | 0 |
| 直接 Parser import | 0 |
| `sqlite3.connect`、cursor、SQL | 0 |
| `Path.read_text/write_text`、`shutil`、`zipfile` 等文件业务 | 0 |
| Paramiko、Netmiko、AsyncSSH 或设备网络连接 | 0 |
| Router 内 Service 构造 | 0 |
| 直接依赖 `sqlite3` 异常类型 | 0 |

3 个 Online MR Router 统一经单例 `OnlineMrApiFacade` 获取无副作用当前局点并调用既有 Query、LOCAL control、AGENT control；Traffic Router 经单例 `TrafficWebApplicationService` 完成执行端、查询、取消与重试编排；基础资料导入策略经既有 `RailTransitBaseDataImportService.get_import_policy()` 返回。配置采集和网络工具 Service 由 `create_app()` 组合根注入，Traffic 与 Network Tools 共用纯 presentation 映射。

文件下载继续由 `FileManagementApplicationService` 完成路径解析和白名单校验，Router 只返回受控 `FileResponse`；Streaming 与 WebSocket 仍是允许的传输层行为。

## 4. Router 审计矩阵

| Router | 状态 | 当前边界与问题 | 最小后续动作 |
| --- | --- | --- | --- |
| `ac_management_router.py` | `PASS` | 通过 `AcManagementQueryService` 查询资源、光衰和配置；存储与快照 I/O 异常经共享 API helper 保留既有 HTTP 映射。 | 保持查询 Service 边界。 |
| `ac_mesh_link_router.py` | `PASS` | 查询经 `AcMeshLinkQueryService`，刷新经 `AcMeshLinkRefreshApplicationService`；Task 创建未在 Router 重做。 | 保持查询/刷新双 Service 边界。 |
| `agent_router.py` | `PASS` | 通过 `AgentControllerService` 完成 Agent 查询、控制和事件转发；Router 仅做 DTO、Secret 解包和 WebSocket 传输。 | 无。 |
| `config_collection_router.py` | `PASS` | 查询、采集、diff、Task 和 Artifact 均调用组合根注入的 `ConfigCollectionApplicationService`；缺失接线返回稳定 503。 | 保持唯一组合根注入。 |
| `device_management_router.py` | `PASS` | 设备列表、详情、操作预览和任务均经 `DeviceManagementWebService`；无直接 Repository 或设备连接。 | 保持 Service 用例边界。 |
| `feature_router.py` | `PASS` | 只读取集中 Feature Registry 并输出 DTO；未形成第二套 Feature 规则。 | 无。 |
| `file_management_router.py` | `PASS` | 本地/远程目录、下载队列、路径解析和白名单均经 `FileManagementApplicationService`；Router 仅流式返回 Service 已核准的受控文件。 | 设备文件使用独立 `device_file_ref`，不得伪装 Artifact；保持现有 File Service。 |
| `job_center_router.py` | `PASS` | 任务、摘要和日志均经 `JobCenterQueryService`；无直接 Task Repository 或日志文件读取。 | 无。 |
| `mesh_analysis_router.py` | `PASS` | SQL、统计、raw tail 和 Artifact 解析全部委托 `MeshAnalysisQueryService`；下载仅返回 Service 白名单结果。 | 无。 |
| `network_tools_router.py` | `PASS` | TCP 端口测试经组合根注入的 `NetworkToolsApplicationService`；执行目标与 Traffic DTO 使用共享 presentation helper。 | 保持与 Traffic Router 的 DTO 契约一致。 |
| `online_mr_agent_control_router.py` | `PASS` | Agent 生命周期经单例 `OnlineMrApiFacade` 和既有 `OnlineMrAgentWebControlService`；只复用无 I/O 的 Desktop/loopback 鉴权依赖。 | 保持 AGENT 正常停止与默认关闭边界。 |
| `online_mr_control_router.py` | `PASS` | LOCAL 启停经单例 `OnlineMrApiFacade` 和既有 `OnlineMrWebControlService`；Router 仅保留 loopback/Desktop session 信任边界。 | 保持 LOCAL 生命周期与权限契约。 |
| `online_mr_router.py` | `PASS` | 会话、preview、raw tail 经单例 `OnlineMrApiFacade` 调用 `OnlineMrQueryService`；当前局点只读解析不创建目录、数据库或配置。 | 保持查询白名单和无副作用局点解析。 |
| `rail_transit_base_data_router.py` | `PASS` | 查询、preview、apply、rollback 与导入策略均调用现有 Service；策略由 `RailTransitBaseDataImportService.get_import_policy()` 统一返回。 | 保持 Guard、身份边界和写保护不变。 |
| `task_router.py` | `PASS` | Task 查询、取消和事件流均经 `TaskApplicationService`；`cancellable` 仅为响应映射，真实取消规则仍在 Service。 | 无。 |
| `traffic_router.py` | `PASS` | 启动、执行端可用性、过滤分页、取消和重试经单例 `TrafficWebApplicationService`；Router 保留 DTO 与 WebSocket 传输。 | 保持 REST 数组响应与专用 WebSocket 契约。 |
| `train_communication_router.py` | `PASS` | 所有列车通信聚合经 `TrainCommunicationQueryService`；Router 只做参数、404 和错误映射。 | 无。 |
| `wireless_dashboard_router.py` | `PASS` | 聚合、缓存和状态计算均在 `WirelessDashboardQueryService`；Router 只做参数和错误映射。 | 无。 |

## 5. 跨文件问题

### 5.1 Online MR 当前局点边界已收口

`OnlineMrApiFacade.current_site_id()` 只读 `app_config.json`、验证局点名和既有局点目录；缺失、无效、不可读或不存在均返回稳定错误且不创建 demo 局点、目录、数据库或配置。三个 Router 共用组合根中的同一 Facade，不再调用 `SiteManager.get_current_site()` 或跨 Router 导入私有局点 helper。

### 5.2 存储异常映射已收口

正式 Router 的 `sqlite3` import/catch 已全部移除。`src/netconsole/backend/api/error_mapping.py` 集中捕获 SQLite 与受控 I/O 异常，各 Router 仍显式给出原有 HTTP 状态和用户消息；静态守卫要求临时债务表为空。

### 5.3 组合根已统一

`src/netconsole/backend/api/main.py` 的现有 `create_app()` 是唯一组合根：单例 Task、Agent、Traffic、LocalProcessAdapter 与 Online MR Application 生命周期不变；新增的 Online MR Facade 和 Traffic Web Application Service 各只创建一次。配置采集、网络工具和基础资料导入 Service 也由这里注入。未引入 `ApiRuntimeServices` 类、第二套容器或空 composition 包。

## 6. 治理顺序与阶段门

Phase 0.5 第一批 A-D/E 的 Router 边界修复已完成，静态守卫债务为零。后续模块开发继续以定向测试优先；若新增 Router 依赖、Service 编排或存储错误映射，必须保持静态守卫通过。Phase 1 是否启动仍由主控依据全量验证、真实业务优先级和现场条件决定，本记录不替代该决策。

## 7. 非目标

- 不新增产品页面或恢复已删除的桌面宿主；
- 不启动 Electron、Launcher 或通用 Native Bridge 实现；
- 不迁移或审计 SNMP Center、无线勘测；
- 不连接真实 MR、Agent、AC、设备 IP 或生产凭据；
- 不把本审计文档描述成已经完成代码整改。
