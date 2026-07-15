# API / Application 边界审计

## 1. 目的与基线

本审计用于确认 FastAPI 只承担传输层职责，不成为新的业务层。目标调用链为：

```text
Vue / Electron
  -> FastAPI Router
  -> Application Service / Query Service
  -> Repository / Infrastructure / Device Adapter
```

审计基线为 2026-07-15 的 `main@dc62324cf7a61bb9e8abbcdb144f97543e04ad68`，覆盖 `src/netconsole/backend/api/` 下全部 18 个 `*_router.py`。SNMP Center 与无线勘测保持 `EXCLUDED / FUTURE_REBUILD`，不在本轮范围内。

本轮只做静态审计和治理排序，不修改 Router、Service、Qt、Vue、Launcher 或 Electron 代码。

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

`sqlite3` 仅用于捕获存储异常时，不等同于 Router 直接访问数据库，因此不单独把 Router 判为 `REFACTOR_REQUIRED`；它仍是需要以稳定领域错误替代的跨层耦合，见第 5 节。

## 3. 总体结论

| 项目 | 结果 |
| --- | --- |
| Router 总数 | 18 |
| `PASS` | 11 |
| `WARNING` | 2 |
| `REFACTOR_REQUIRED` | 5 |
| 直接 Repository import | 0 |
| 直接 Parser import | 0 |
| `sqlite3.connect`、cursor、SQL | 0 |
| `Path.read_text/write_text`、`shutil`、`zipfile` 等文件业务 | 0 |
| Paramiko、Netmiko、AsyncSSH 或设备网络连接 | 0 |
| Router 内 Service 构造 | 2 |
| 直接依赖 `sqlite3` 异常类型 | 10 |

结论不是“Router 普遍失控”。文件管理、配置采集和绝大多数查询 Router 已经通过 Application/Query Service 工作；真正需要优先治理的是 3 个 Online MR Router 的有副作用局点解析、Traffic Router 的查询/可用性/控制编排，以及轨道交通基础资料 Router 的导入策略拼装。

原先“文件管理 Router 直接操作文件系统”的高风险假设不成立：下载路径均由 `FileManagementApplicationService` 完成解析和白名单校验，Router 只在最后返回 `FileResponse`。配置采集也未在 Router 内重新实现采集或文件读取。

## 4. Router 审计矩阵

| Router | 状态 | 当前边界与问题 | 最小后续动作 |
| --- | --- | --- | --- |
| `ac_management_router.py` | `PASS` | 通过 `AcManagementQueryService` 查询资源、光衰和配置；无直接设备连接或 Repository。`sqlite3.OperationalError` 映射位于 156 行。 | 业务改动触及该模块时，改用稳定 Query Service 错误。 |
| `ac_mesh_link_router.py` | `PASS` | 查询经 `AcMeshLinkQueryService`，刷新经 `AcMeshLinkRefreshApplicationService`；Task 创建未在 Router 重做。存储异常映射位于 221 行。 | 保持查询/刷新双 Service 边界。 |
| `agent_router.py` | `PASS` | 通过 `AgentControllerService` 完成 Agent 查询、控制和事件转发；Router 仅做 DTO、Secret 解包和 WebSocket 传输。 | 无。 |
| `config_collection_router.py` | `WARNING` | 所有配置查询、采集、diff、Task 和 Artifact 均调用 `ConfigCollectionApplicationService`；但 24-29 行在 Router 内提供 Service fallback 并写回 `app.state`。正式组合根已在 `src/netconsole/backend/api/main.py` 注入该 Service。 | 删除 Router fallback，只接受组合根注入；未接线时返回稳定 503。 |
| `device_management_router.py` | `PASS` | 设备列表、详情、操作预览和任务均经 `DeviceManagementWebService`；无直接 Repository 或设备连接。存储异常映射位于 116 行。 | 业务改动触及该模块时，改用稳定 Service 错误。 |
| `feature_router.py` | `PASS` | 只读取集中 Feature Registry 并输出 DTO；未形成第二套 Feature 规则。 | 无。 |
| `file_management_router.py` | `PASS` | 列表、下载任务、路径解析和白名单均经 `FileManagementApplicationService`；107-109 行仅流式返回 Service 已核准文件。 | 保持 Artifact streaming 边界；无需新建 File Service。 |
| `job_center_router.py` | `PASS` | 任务、摘要和日志均经 `JobCenterQueryService`；无直接 Task Repository 或日志文件读取。存储异常映射位于 69 行。 | 业务改动触及该模块时，改用稳定 Query Service 错误。 |
| `mesh_analysis_router.py` | `PASS` | SQL、统计、raw tail 和 Artifact 解析全部委托 `MeshAnalysisQueryService`；下载仅返回 Service 白名单结果。 | 无。 |
| `network_tools_router.py` | `WARNING` | TCP 端口测试经 `NetworkToolsApplicationService`，但 17-18 行每次请求自行构造 Service，11 行还导入 `traffic_router` 的私有 `_execution_target` 与 `traffic_run_dto`。 | 在组合根注入 Service；把共享 API 映射移入独立 presentation helper。 |
| `online_mr_agent_control_router.py` | `REFACTOR_REQUIRED` | Agent 生命周期已在 `OnlineMrAgentWebControlService`；但 5-8 行复用 sibling Router 的私有 `_site_id`，并在 35、55、63、72、78 行继承其有副作用局点解析。 | 由 Agent Application Service 提供当前局点；只复用无 I/O 的公共 API 鉴权依赖。 |
| `online_mr_control_router.py` | `REFACTOR_REQUIRED` | LOCAL 启停已委托 `OnlineMrWebControlService`，loopback/Desktop session 校验合法；但 23-31 行直接调用 `SiteManager.get_current_site()`。该方法会确保 demo 局点、建目录、初始化数据库并可能回写配置。 | 由 Online MR Application Service 提供当前局点，保留 Router 信任边界校验。 |
| `online_mr_router.py` | `REFACTOR_REQUIRED` | 会话、preview、raw tail 均经 `OnlineMrQueryService`；但 25-26 行的 GET 路由局点解析直接调用同一非纯 `SiteManager.get_current_site()`。 | 给 Query Service 增加公开的 `current_site_id()`，GET Router 不再触发基础设施写入。 |
| `rail_transit_base_data_router.py` | `REFACTOR_REQUIRED` | 大多数查询、preview、apply、rollback 已经进入对应 Service；但 204-223 行直接访问 `import_service.guard`、调用 `import_policy_rows()` 并硬编码身份边界文案。 | 增加公开 `get_import_policy(site_id)` 用例，统一返回 Guard 状态、身份边界和策略 DTO。 |
| `task_router.py` | `PASS` | Task 查询、取消和事件流均经 `TaskApplicationService`；`cancellable` 仅为响应映射，真实取消规则仍在 Service。 | 无。 |
| `traffic_router.py` | `REFACTOR_REQUIRED` | 启动与事件存储使用 `TrafficTestApplicationService`；但 47-75、381-391 行在 Router 计算执行端可用性，153-165 行自行做日期过滤和分页，220-238 行自行完成 run 到 controller task 的取消/重试编排。 | 在 Traffic Application Service 增加执行端查询、带过滤分页的 run 查询、`cancel_run` 和 `retry_run` 用例；保留 DTO/WebSocket 传输逻辑。 |
| `train_communication_router.py` | `PASS` | 所有列车通信聚合经 `TrainCommunicationQueryService`；Router 只做参数、404 和错误映射。 | 无。 |
| `wireless_dashboard_router.py` | `PASS` | 聚合、缓存和状态计算均在 `WirelessDashboardQueryService`；Router 只做参数和错误映射。 | 无。 |

## 5. 跨文件问题

### 5.1 当前局点 Helper 不是纯读取

`SiteManager.get_current_site()` 在 `src/netconsole/core/sites.py:95-104` 内调用 `ensure_demo_site()` 和 `list_sites()`，会进一步创建目录、初始化数据库，并在配置异常时保存修正后的配置。它不能作为 Router 的轻量参数 Helper。

这一个根因同时影响：

- `online_mr_router.py`；
- `online_mr_control_router.py`；
- 通过私有 import 继承该行为的 `online_mr_agent_control_router.py`。

应按 Query/Application Service 分别提供当前局点用例，不要新增另一个全局 Service Locator。

### 5.2 存储异常类型泄露到 API

10 个 Router 直接 `import sqlite3`，其中 9 个显式捕获 SQLite 异常，`wireless_dashboard_router.py` 在组合异常中捕获。它们没有执行 SQL，所以不是直接数据库越界；但 API 错误协议仍了解底层存储实现。

后续不做一次性全仓重构。每次治理一个模块时，由 Application/Query Service 把 `sqlite3.Error`、`OSError` 等转换成稳定领域错误，Router 只负责领域错误到 HTTP 的映射。

### 5.3 组合根不唯一

`src/netconsole/backend/api/main.py:228-292` 已集中向 `app.state` 注入主要 Service。`config_collection_router.py` 的 fallback 与 `network_tools_router.py` 的逐请求构造使组合责任重新进入 API 层，应收回组合根。

## 6. 治理顺序与阶段门

本审计完成后，Phase 0.5 的“发现与定级”完成，但“边界修复”尚未完成。建议继续按定向测试优先拆成小批次：

1. **Online MR 当前局点边界**：一次修复共享根因，覆盖 Query、LOCAL 控制和 Agent 控制三个 Router；不得改变既有控制权限和真实设备冻结项。
2. **Traffic Application 用例收口**：下沉执行端可用性、过滤分页、取消和重试；不得重写 Traffic 事件、Repository 或 Agent Adapter。
3. **基础资料导入策略查询**：增加一个公开 Service 用例；不得改变现有 Guard、写开关或身份规则。
4. **组合根清理**：删除配置 fallback，注入 Network Tools Service，并抽离共享 API 映射。
5. **稳定领域错误**：只在触及相关模块时渐进替换 `sqlite3` 异常，不单独发起全仓大改。

前三项 `REFACTOR_REQUIRED` 根因完成并通过模块定向测试后，再进入 Phase 1 的设备管理 Web 对等开发。最终集成批次提交前再运行全量 pytest、前端测试/构建、Ruff、文档链接检查和受影响的 Go 测试。

## 7. 非目标

- 不新增 Web 或 Qt 页面；
- 不启动 Electron、Launcher 或通用 Native Bridge 实现；
- 不迁移或审计 SNMP Center、无线勘测；
- 不连接真实 MR、Agent、AC、设备 IP 或生产凭据；
- 不把本审计文档描述成已经完成代码整改。
