# ADR：开源能力分阶段集成

## 元数据

| 项目 | 值 |
| --- | --- |
| 状态 | 已接受，限于分阶段实施决策；阶段 1～8 尚未获生产接管授权 |
| 日期 | 2026-07-30 |
| 审计基线 | `github/main` `9cbca3f90afe8c7e5e7fcb0a2ea0f401366a22f4` |
| 当前交付 | 阶段 0：全仓审计、边界与门禁；仅 Markdown |
| 决策范围 | xterm.js、TTP、AntV G6、DuckDB/Parquet、配置版本、Syslog 规则包、scrapli、Inventory/基础资料 |
| 明确排除 | 阶段 1～8 实现、Monaco 在研改动、完整第三方 NMS、生产路径切换、数据迁移、正式打包 |

本 ADR 记录在上述提交上核对到的事实和后续实施约束。后续每个阶段必须从实施时最新
`github/main` 新建独立 worktree 和分支，重新审计基线、保存既有失败集合、定向验证、中文提交、
推送和创建 Draft PR；不得因为本 ADR 已接受而跳过依赖、真实设备或正式包门禁。

## 证据等级

| 等级 | 含义 |
| --- | --- |
| `CONFIRMED` | 已从当前代码、锁文件、测试、构建脚本或稳定项目文档直接确认 |
| `INFERRED` | 由已确认架构推导出的实施方案，尚无实现或运行证据 |
| `UNVERIFIED` | 需要目标系统、真实设备、性能样本或正式安装包验证 |
| `REJECTED` | 与当前架构、安全或范围冲突，本轮明确不采用 |

文中“支持”“可用”只用于 `CONFIRMED` 事实；规划项不提升证据等级。

## 决策摘要

1. `CONFIRMED`：继续使用 Electron Main/Preload + 唯一 Vue Renderer + FastAPI/Python Core；
   Router 只做 DTO、鉴权、Service 调用和响应映射。
2. `INFERRED`：xterm.js、TTP、AntV G6、DuckDB/Parquet 和 scrapli 可作为直接依赖候选，
   但只能在各自阶段锁定版本并通过许可证、离线构建、SBOM、NOTICE 和正式包验证后引入。
3. `INFERRED`：Oxidized、napalm-logs、Nornir、NetBox 只提供模型和设计参考，由 NetConsole
   原生实现，不引入它们的服务、运行环境或第二套事实源。
4. `REJECTED`：阶段 1 不用 `node-pty` 或 ConPTY 作为远程 SSH/Telnet 基础。远程终端应通过
   Python Transport 产生字节流；xterm.js 只是 Renderer 终端控件。
5. `REJECTED`：DuckDB 不替代 SQLite。SQLite 继续保存事务、元数据和任务状态；DuckDB/Parquet
   仅作为可重建分析层，首个试点只允许 MESH。
6. `INFERRED`：TTP 初始只做 shadow。生产结果仍来自现有 parser；模板错误、未匹配和差异只进入
   受控诊断，不得改变生产写入或业务结论。
7. `REJECTED`：交互式终端不建成长时间 `RUNNING` 的普通 Task，也不按输入或输出创建 Task/Event。
   它使用独立、轻量、有界的 Session Store；批量命令、脱离页面采集和日志导出才进入 Job/Export。
8. `CONFIRMED`：现有第三方工具集、全局任务详情、统一导入导出和配置对比能力必须复用，不建立
   第二套工具 Store、任务窗口、Save As/Artifact 状态机或 Diff UI。
9. `CONFIRMED`：最新主线将工作区状态收敛为进程内存。冷启动只恢复 Dashboard，旧布局状态只清理；
   托盘隐藏/恢复同一进程时保留当前标签。因此交互会话不得宣称可跨进程恢复，后端重启、局点切换和
   完整退出必须使旧 session 明确失效。
10. `INFERRED`：阶段 1 首发只允许受保护的 Electron Desktop session。Browser/Server 在建立独立、
    可审计的终端认证与授权前必须 fail closed；现有 WS session cookie 不能作为两者已安全的证据。

## 当前能力审计

### 审计矩阵

| 领域 | 当前事实与主要路径 | 复用结论 | 等级 |
| --- | --- | --- | --- |
| SSH/Telnet | `src/netconsole/services/netmiko_connection.py`、`connection_manager.py` 已封装 Netmiko/Paramiko、SSH/Telnet、隧道、提示符、重试和敏感文本清理 | 阶段 1 先增加窄的 interactive adapter，不全局替换 Transport | `CONFIRMED` |
| 设备连接测试 | `device_connection_preflight.py` 与 Job Center `LocalProcessAdapter` 已支持保存凭据和一次性 stdin sensitive bootstrap | 复用凭据预检、错误分类和一次性敏感引导模式 | `CONFIRMED` |
| SFTP | `file_transfer_service.py`、`host_key_trust_service.py` 区分 SSH 登录、SFTP 子系统、host key、隧道、`.part` 和大小校验 | 不把交互终端和文件传输合成一个状态机 | `CONFIRMED` |
| 外部终端 | `external_terminal.py` 支持 SecureCRT/Xshell/PuTTY；普通设备可按设置传密码，FIT-AP 固定 Telnet 23 且不传用户名/密码 | 保留既有外部终端；内置终端不得复制 argv/URL 凭据模型 | `CONFIRMED` |
| 工具集 | Electron `ExternalToolStore/Service` 使用 `userData/external-tools.json`，Renderer 启动只提交 `toolId` | 内置终端作为产品内置能力接入现有导航；不写入第三方工具 Store | `CONFIRMED` |
| AC 常驻采集 | `mesh_link_resident_polling_service.py` 与 `handlers/ac_jobs.py` 的 `ac_mesh_link_resident_poll` 复用单 SSH 会话、控制文件、重连和退避 | 可借鉴连接生命周期，但不能直接作为交互终端 Session Store | `CONFIRMED` |
| Job Center | `job_registry.py` 当前代码导入实测 117 个 task type；`TaskApplicationService -> TaskRepository -> tasks.db`，schema v3，快照/事件分表，REST + `/ws/tasks` | 长任务复用；`legacy_tasks.py` 只迁出不迁入；终端会话不进入普通 Job | `CONFIRMED` |
| Job 文档漂移 | `docs/JOB_CENTER.md` 仍写 88 个 task type | 数量必须由代码产生；本 ADR记录 117，不顺手改专题文档 | `CONFIRMED` |
| 全局任务详情 | `apps/web/src/task-center/components/TaskDetailDrawer.vue` 是唯一详情宿主；Electron `openTaskWindow` 只恢复主窗口并通知 Vue | 后续 Job 详情复用该抽屉，不建新窗口 | `CONFIRMED` |
| 用户文件 | `exportActionRegistry.ts`、`useUserSelectedExport.ts` 和 Electron 受控下载形成统一保存契约 | 日志、图和数据导出先登记固定动作，取消选择时不得创建 Job/Artifact | `CONFIRMED` |
| 配置采集 | `config_lifecycle_service.py`、`config_snapshot_repository.py`、config Job/API/Vue 已有 running/saved/diff、正文 SHA-256、raw 引用、跨设备对比、删除隔离和失败恢复 | 阶段 5 在现有模型兼容扩展，不创建另一套配置库或 Diff 页面 | `CONFIRMED` |
| 配置规范化缺口 | 当前正文裁剪为首个独立 `#` 到最后 `return`；尚无独立 raw/normalized hash、previous version、significant change 模型 | 阶段 5 必须显式版本化 normalizer，不能把现有正文 hash 误写成完整版本模型 | `CONFIRMED` |
| H3C parser | `parsers/h3c/` 与 `adapters/h3c/` 已覆盖 version、interface、LLDP、transceiver 等；fixture 位于 `tests/fixtures/h3c/` | TTP 先与这些确定性结果做 shadow | `CONFIRMED` |
| ZTE parser | `parsers/zte/zxr10.py`、`vlan.py` 覆盖 version、interface、optical、LLDP、switchvlan、VLAN/PVID，保留 `offline -> no_module` 语义 | TTP 不得改变 PVID 来源优先级、冲突警告和光模块结论 | `CONFIRMED` |
| MESH raw/存储 | raw 不可删除；`catalog.sqlite`、Profile `mesh.sqlite`、每来源 `*.mesh.sqlite`；派生 schema 为 `meshlog_compact_v3_tagged_samples`；支持 SHA、防重、分页、过滤、只读查询和最多 2000 点降采样 | 阶段 4 只旁路生成可重建 Parquet，SQLite 元数据和旧查询保留 | `CONFIRMED` |
| 无人值守 Syslog | `SyslogUdpReceiver` 默认有界队列 20,000；`RawStreamWriter` 按小时写不可变 NDJSON，每 100 条或 1 秒 flush；内置正则解析 WMESH/IFNET | 阶段 6 只给当前 raw 事实源增加版本化 shadow 规则层 | `CONFIRMED` |
| 图表/拓扑 | MESH、Online MR、Ping、Traffic 使用 ECharts；`FixedTrainTopology.vue` 是固定六节点拓扑；未发现通用关系图或 G6 依赖 | G6 只承载关系图，时序 ECharts 保持不变 | `CONFIRMED` |
| 路径 | `src/netconsole/core/paths.py` 已提供配置、任务、MESH、Online MR、AC Mesh-Link、无人值守目录入口 | 新数据目录必须由 PathResolver 增加，不允许 `Path.cwd()` 或用户文件名拼路径 | `CONFIRMED` |
| Electron 安全 | `security.ts` 启用 sandbox/context isolation，禁用 Node integration/webview/任意导航，CSP 仅允许 self、受控 loopback、data/blob | xterm/G6 必须本地打包；不得用 CDN 或扩展为不受控源 | `CONFIRMED` |
| 冻结打包 | `clean_build_spec.py` 由 `ALLOWED_DATA`、`RUNTIME_DATAS`、`RUNTIME_IMPORTS` 生成 PyInstaller 白名单；electron-builder `extraResources` 只复制受控 Backend/branding/native | TTP 模板、规则包、DuckDB 二进制依赖都需显式入白名单和 packaged smoke | `CONFIRMED` |
| WebSocket | `/ws/tasks`、`/ws/agents`、`/ws/traffic/*` 当前只调用 `send_json`，生产代码没有 `receive_*` | 现有 WS 是服务端推送通道，不能冒充通用双向交互 Transport；终端必须新建独立、有界的双向协议 | `CONFIRMED` |
| 桌面会话认证 | `DesktopSessionMiddleware` 可用短期 header/cookie 保护 Electron 本机 HTTP/WS，Browser/Server 没有独立终端认证 | 阶段 1 只开放 Electron Desktop；Browser/Server fail closed | `CONFIRMED` |
| 合规 | `open_source_notices.json`、`THIRD_PARTY_COMPONENTS.md`、`generate_sbom.py`、`check_runtime_deps.py` 和 package smoke 是严格门；自动闭包主要覆盖 Python，普通前端 npm lock 依赖尚无同等精确的 PURL/SBOM 自动校验 | 未知许可证、版本或组件缺失必须阻断发布；新增 `@xterm/*` 时必须先补齐 npm 自动闭包门 | `CONFIRMED` |
| 候选依赖现状 | Python/Node 依赖清单和锁文件未发现 xterm、TTP、G6、DuckDB、Parquet、scrapli、node-pty | 所有候选均是未来新增依赖，不得称为已具备 | `CONFIRMED` |
| Windows 10 | 当前仓库没有内置终端正式安装包的人工验收证据 | `embedded_terminal` 在目标机验收前保持关闭/development | `UNVERIFIED` |
| Windows Server 2012 | 当前仓库没有上述候选依赖在 Windows Server 2012 上的可信运行证据；Electron 43/Node 24、旧 CPU 指令集和 VC Runtime 组合兼容性未知，旧检查清单还含与 fail-closed 数据根冲突的历史描述 | 全部标记未验证，以能力探测和旧路径回退代替兼容承诺 | `UNVERIFIED` |

### 重复实现风险

1. 为内置终端复用 `external-tools.json` 会把“产品内会话状态”和“用户自备 EXE 配置”混为一体。
2. 为终端、shadow parser 或 Parquet 构建另建任务数据库、WebSocket 任务流或详情窗口，会形成第二套
   Task 状态源。
3. 页面自行实现终端日志、拓扑图或配置下载，会绕开统一文件选择、Artifact 和失败重试。
4. 在 Vue 内硬编码快捷命令，会复制 Command Reference、设备 Profile 和 Adapter 的命令事实。
5. TTP 一次性替换 Python parser，会丢失 H3C/ZTE 的分页、提示符、PVID、光模块和部分失败语义。
6. G6 替换 ECharts，会错误地把关系图技术用于秒级时序分析。
7. DuckDB 保存局点、设备、任务或 Dataset 状态，会与 SQLite 事务事实源竞争。
8. YAML Syslog 规则覆盖 raw 或原地改写结构化结果，会破坏证据追溯。
9. 配置版本另建 Diff UI 会与 Monaco 在研工作发生冲突。
10. 把交互终端绑定到跨进程工作区恢复，会与最新“冷启动仅 Dashboard”规则冲突并制造伪恢复。

### 已知架构债务

- `CONFIRMED`：多数既有 Job handler 仍通过 `legacy_tasks.py` 薄适配。新阶段不得继续向兼容区堆逻辑。
- `CONFIRMED`：Job 专题文档的 task type 数量漂移；后续应单独由 Job Center 维护任务修正。
- `CONFIRMED`：设备凭据仍由设备模型/SQLite 保存；完整迁移包也会包含凭据。阶段 1 只能复用受控
  读取和一次性内存输入边界，不能宣称已经存在系统凭据保险库。
- `CONFIRMED`：外部终端为兼容第三方程序仍可能把普通设备密码放入 argv/URL。该现状不能成为
  内置终端的设计先例。
- `CONFIRMED`：配置快照、MESH 派生库和 Syslog 规则目前各自有稳定模型，但尚无通用 parser registry、
  topology DTO 或 analytics dataset manifest。
- `UNVERIFIED`：Windows Server 2012、旧 CPU 指令集、VC Runtime、Python 3.13 冻结运行时与 DuckDB
  wheel 的组合尚未验证。

## 依赖策略

| 候选 | 决策 | 预期用途 | 引入前门禁 |
| --- | --- | --- | --- |
| `@xterm/xterm` 与必要 addon | 直接依赖候选 | DOM renderer 终端显示、fit、search；链接默认禁用或受控白名单 | 固定 npm lock 事实、许可证、精确 PURL/SBOM 自动校验、Notice/`THIRD_PARTY_COMPONENTS.md`、无 CDN、包体积、CSP、Electron build/package smoke |
| TTP | 直接依赖候选 | 版本化 CLI 模板与 shadow parser | Python 3.13、模板错误隔离、冻结资源、许可证、NOTICE/SBOM |
| `@antv/g6` | 直接依赖候选 | 共享关系拓扑组件 | 固定版本、许可证、CSP、按需打包、500～1000 节点和销毁测试 |
| DuckDB | 直接依赖候选 | 对 Parquet 的本地只读分析和聚合 | wheel/CPU/VC Runtime/Server 2012/冻结加载/包体积/降级 |
| Parquet | 文件格式 | MESH 可重建列式派生数据 | 优先验证 DuckDB 原生读写，阶段 4 不默认引入 pyarrow |
| scrapli | 实验性直接依赖候选 | 与现有 SSH Transport 对比 | 默认关闭，真实只读设备、编码、并发、取消、冻结和回退 |
| Oxidized | 只借鉴设计 | 配置版本、内容去重、显著变化 | 不引入 Ruby 服务或其存储 |
| napalm-logs | 只借鉴设计 | 版本化 YAML 规则组织 | 不引入消息总线或完整服务 |
| Nornir | 只借鉴设计 | Inventory 分组、单设备结果、部分失败 | 不引入并行调度框架 |
| NetBox | 只借鉴设计 | 最小 Source of Truth 模型 | 不引入服务、数据库或第二套 UI |
| `node-pty` / ConPTY | `REJECTED`（阶段 1） | 不适用 | 远程 SSH/Telnet 不需要本机伪终端；避免平台耦合和额外原生二进制 |
| 完整第三方 NMS | `REJECTED` | 不适用 | 会复制 Inventory、凭据、任务、数据库、API 和 UI 事实源 |

具体版本和传递依赖不得在 ADR 中提前锁定。每个实现阶段使用当时维护中的版本，更新对应
`package.json`/`pnpm-lock.yaml` 或 `pyproject.toml`/`constraints.txt`。当前构建脚本生成的精确闭包
主要覆盖 Python；普通前端 npm 依赖不能仅凭 `package.json`/lock 更新或手工说明视为合规。引入
`@xterm/*` 必须同批新增从 npm lock 提取版本/传递依赖事实并核对许可证、PURL、CycloneDX SBOM、
Notice/`THIRD_PARTY_COMPONENTS.md` 的自动化测试，以及正式 package smoke。

## 目标边界

```text
Vue 页面 / 公共组件
    -> REST / WebSocket / 固定 Electron Bridge
    -> Application Service
    -> Domain Service / Registry
    -> Existing or Experimental Infrastructure Adapter
    -> SQLite metadata + immutable raw + rebuildable derived data
```

- Vue 只处理布局、输入、轻量校验和状态绑定，不执行 SSH/Telnet、SQL 或任意文件写入。
- Electron 只负责窗口/进程生命周期和白名单 Native Bridge，不建立第二套业务 Core。
- FastAPI Router 不实现设备协议、解析算法、数据集状态机或文件选择。
- SQLite 连接不跨线程/进程共享；Worker 通过现有 Job 协议和 Repository 写入。
- 原始 MESH、Syslog 和配置内容是证据；派生结果可版本化重建但不得伪装成原始数据。

## 跨阶段契约

### 数据分类与持久化

| 类别 | 示例 | 规则 |
| --- | --- | --- |
| 事务事实 | 局点、设备、Task、快照元数据、Dataset Manifest | SQLite；兼容迁移、WAL 和 Repository 边界 |
| 不可变证据 | MESH raw、Syslog NDJSON、原始配置 | 业务数据根受管目录；SHA-256、来源、相对路径、不可覆盖 |
| 可重建派生数据 | normalized config、TTP shadow、Parquet、规则解析结果 | parser/schema version；临时文件 + 校验 + 原子替换；失败保留旧路径 |
| 短期会话状态 | terminal session、WS cursor、输出 ring buffer | 进程内有界 Store；不进入工作区持久化；重启后明确过期 |
| 用户正式文件 | 会话日志、拓扑图、报告 | 固定 Export Action/Export Process/Artifact；用户选择最终路径 |

新增路径必须经过 `PathResolver`。用户输入、设备名、局点名和文件名不得直接变成目录片段；
Repository 只接受受控相对路径，并拒绝逃逸、符号链接和联接。

### 凭据

- 保存凭据只由现有设备 Repository/连接 Service 解析，Renderer 不接收明文。
- 一次性凭据沿用 stdin sensitive bootstrap 或建立等强度的一次性内存通道；不得进入 URL、
  localStorage、sessionStorage、Task params、环境变量、普通日志和 WebSocket 状态。
- Session Store 只保留不可逆 credential source/reference 和生命周期状态，不保存可序列化明文。
- 认证错误返回稳定分类，不返回内部堆栈、绝对路径、命令参数或设备秘密。
- 外部终端既有 argv/URL 兼容行为不复制到内置终端。

### 错误和诊断

跨阶段稳定错误至少包括：

```text
dependency_unavailable
feature_disabled
transport_connect_failed
transport_auth_failed
transport_timeout
parser_unsupported
parser_failed
dataset_not_ready
dataset_corrupted
websocket_disconnected
session_expired
packaging_resource_missing
```

日志只记录 `operation_id`、`task_id` 或 `session_id`、`site_id`、`device_id`、`parser_id`、
`transport_id`、duration 和安全错误分类。不得记录密码、Token、完整敏感配置、终端逐键输入、
完整 raw 输出或内部上传临时绝对路径。shadow 诊断保存受控 Artifact 引用、哈希、计数和脱敏差异。

### WebSocket 背压和资源释放

- 现有 Task/Agent/Traffic WS 都是服务端推送且没有 `receive_*`；Online MR、AC 常驻采集和 SFTP
  只能借鉴连接/取消/清理生命周期，不得冒充终端所需的通用双向交互 Transport。
- 终端输入控制帧与输出数据帧分型；限制单帧、发送队列、输出 ring buffer、滚屏和空闲时间。
- 慢消费者不得无限积压；达到上限后先给稳定诊断，再受控断开，绝不阻塞设备读取线程。
- Task WebSocket 继续复用 `/ws/tasks`；终端使用独立 session WS，不混写 Task Event。
- 标签关闭、站点切换、Renderer 销毁、Backend 重启和 Electron 完整退出均必须关闭连接、reader、
  timer、queue 和临时授权。托盘隐藏同一进程时按明确设置保留或关闭。
- `TerminalSessionStore` 和所有终端 Transport 必须接入现有 FastAPI lifespan shutdown；Backend
  shutdown 即使没有 Renderer 主动断开，也要关闭全部 session、reader、timer、queue 和设备连接。
- G6/ECharts 页面卸载时销毁实例和监听器；DuckDB 查询/Worker 取消时关闭连接并清理仅属于本次
  操作的 staging 文件。

### Feature 与回退

规划中的 Feature key：

```text
embedded_terminal
ttp_parser_shadow
g6_topology
duckdb_mesh_analytics
config_version_history
syslog_rule_engine
scrapli_transport
```

用户可见页面、Tab 和动作还必须登记 Feature Registry，并接入 i18n。`embedded_terminal` 在正式
package smoke、Windows 10/11 人工验收和安全门全部通过前保持默认关闭/development；能力探测成功
只说明依赖可加载，不能使页面或入口显示。阶段 1 还必须同时满足 Electron Desktop runtime、本机
受保护 session 和 Feature 门，Browser/Server 一律 fail closed。替换 parser、存储查询路径和
Transport 的开关默认关闭；依赖缺失或能力探测失败时旧路径继续工作，应用不能因此启动失败。

## 阶段计划和文件影响范围

下表是变更预算，不是提前授权。实施时可按现有命名调整新增文件，但不得越过所列所有权边界。

| 阶段 | 依赖顺序 | 预计主要影响 | Flag / 初始状态 | 回滚 |
| --- | --- | --- | --- | --- |
| 0 审计/ADR | 无 | 本 ADR、`docs/README.md` | 无 | 回退文档提交；不影响运行时 |
| 1 xterm 会话终端 | 阶段 0 | `src/netconsole/services/terminal/`、Application Service、terminal Router/DTO/WS、`apps/web/src/views/terminal/`、导航/Feature/i18n、必要 Main/Preload 生命周期测试、Node 依赖与合规文件 | `embedded_terminal` 默认关闭/development；仅 Electron Desktop，正式 package smoke、Windows 10/11 人工验收和安全门通过后才可评审开启 | 关闭 Flag；移除新路由/依赖；外部终端与工具集保持可用 |
| 2 TTP Parser Registry | 阶段 0；可与阶段 1独立 | parser registry、TTP adapter、版本化模板资源、shadow diagnostics、Worker/测试、PyInstaller data、Python 依赖与合规文件 | `ttp_parser_shadow` 默认关闭；即使开启仍由 legacy 产出生产结果 | 关闭 shadow；删除模板派生诊断；legacy parser 不删除 |
| 3 G6 拓扑 | 阶段 0；建议复用阶段 2稳定 DTO | topology Query Service/DTO/API、`apps/web/src/components/topology/`、设备 LLDP 和车内固定拓扑页面、导出动作、Node 依赖与合规文件 | `g6_topology` 初始受控开启 | 关闭 Flag，保留原表格/固定拓扑；不影响 ECharts |
| 4 DuckDB/Parquet MESH 试点 | 阶段 0；依赖稳定 MESH schema | analytics adapter、Dataset Manifest Repository、MESH build/query Job/API、PathResolver、包资源/依赖/性能脚本 | `duckdb_mesh_analytics` 默认关闭 | 停止新建数据集，旧 SQLite 查询恢复；删除仅可重建 Parquet，不删 raw/metadata |
| 5 配置版本 | 阶段 0；建议 parser/normalizer 契约稳定 | 现有 config snapshot schema/repository/service/API、normalizer、Job/Export、稳定 Diff DTO；不改 Monaco UI | `config_version_history` 默认关闭 | 停止写新字段/派生文件，旧 snapshot/diff 保持；迁移必须向后兼容 |
| 6 Syslog YAML 规则 | 阶段 0；复用 parser version 经验 | `ground_unattended` rule loader/engine、规则资源、重解析 Job、诊断 API/UI、PyInstaller data | `syslog_rule_engine` 默认关闭或 shadow | 关闭规则层，恢复内置正则；保留 raw NDJSON，规则派生可重建 |
| 7 scrapli 实验 | 阶段 1 Transport Protocol 稳定后 | experimental transport adapter、Profile/Feature 选择、对比测试、Python 依赖与合规文件 | `scrapli_transport` 默认关闭且按设备 Profile | 关闭 Flag，全量回到 Existing SSH；不迁移或删除凭据 |
| 8 Inventory/基础资料收敛 | 前述 DTO 稳定后 | 现有设备/分组和轨交基础资料 Application/Repository/API；结果树 DTO；不建新服务 | 无全局切换；逐用例 Feature | 逐用例恢复现有查询/批量结果，不做破坏性 schema 回退 |

每阶段只能提交本阶段文件，必须更新相关专题文档和 `docs/CHANGELOG.md`；阶段 0 因无用户可见运行时
变化不更新 CHANGELOG。

## 阶段 1 实施门禁

### 复用边界

- 首发只允许 `RuntimeMode.DESKTOP`、本机 loopback 和已认证 Electron Desktop session；Browser/Server
  即使能访问普通 API 或携带现有 cookie，也必须返回稳定的 `feature_disabled`/未授权结果并 fail closed。
- 复用 `ConnectionManager`、`ConnectionTarget`、host key、隧道、编码和错误清理；新增
  `InteractiveTerminalTransport` 窄接口，不把现有命令采集 API 当作字节流接口硬套。
- Online MR、AC 常驻采集和 SFTP 只复用可证明适用的连接生命周期、取消与资源释放模式；它们没有
  通用双向 WS/Transport 契约，阶段 1 不得用这些既有能力替代 `InteractiveTerminalTransport`。
- 新建轻量 `TerminalSessionStore`，状态至少为 `CREATED/CONNECTING/AUTHENTICATING/READY/
  RECONNECTING/CLOSING/CLOSED/FAILED`，且 session_id 与局点、设备、transport、编码、cols/rows、
  创建和最近活动时间关联，并由现有 FastAPI lifespan shutdown 统一关闭。
- API/WS 只能提交设备 ID、协议选择、凭据来源、resize 和输入数据；不得提交任意本机程序、
  Python 类名、任意 host/port 绕过设备授权或明文已保存密码。
- 设备终端输出一律视为不可信输入。阶段 1 默认禁用或以严格白名单控制 Web Links、OSC hyperlink/
  clipboard、任意 URL、文件协议和外部打开；不得执行设备输出携带的脚本、导航或剪贴板动作，也不得
  为 xterm 放宽现有 CSP。
- 默认使用 DOM renderer。WebGL addon 后置为独立兼容性、安全、资源释放和正式包评估，不进入阶段 1
  首发依赖集合。
- 快捷命令复用 Command Reference/设备 Profile；第一阶段默认只读。复制、粘贴和外部动作必须由
  用户显式触发；多行粘贴和高风险命令必须提示确认，且不得绕过后端设备授权、命令 Profile 和命令边界。
  手工输入不逐键审计，但客户端提示不能代替后端约束。
- 日志导出登记固定 Export Action；不自行保存路径，不在页面加载或会话恢复时自动弹 Save As。
- 工作区只在当前进程内保留 session 引用；冷启动、Backend 重启和站点切换返回
  `session_expired`，不尝试恢复设备连接。

### 自动化验收

1. 创建、认证成功/失败、输入/输出、resize、UTF-8/GB18030、断线和受控重连。
2. 两个标签的流和状态隔离；关闭标签、WebSocket、Renderer、Backend、Electron 后资源释放。
3. 慢消费者、最大帧、队列、ring buffer、滚屏和空闲超时边界。
4. 凭据不出现在 API、WS 状态、Task、日志、错误、标题、导出名或持久化工作区中。
5. FIT-AP Telnet 23 不错误附带用户名/密码；普通设备权限仍由后端决定。
6. 托盘隐藏/恢复的同进程策略与完整退出策略；冷启动只显示 Dashboard，旧 session 明确失效。
7. `@xterm/*` 本地资源以 DOM renderer 在原 CSP 下工作，无 CDN、CSP 放宽、WebGL addon 或
   `node-pty`/ConPTY 运行时依赖。
8. 不影响 SecureCRT/Xshell/PuTTY、第三方工具 Store、全局任务详情和现有 Job WS。
9. Vue 组件行为、API/Application/adapter、Main/Preload 白名单、Feature/i18n 和架构 Guard。
10. 设备输出中的 Web Links、OSC hyperlink/clipboard、任意 URL、文件协议和外部打开默认禁用或
    受白名单控制；复制粘贴只能由用户动作触发，多行/高风险输入确认不能绕过后端命令边界。
11. Web production build、Electron typecheck/build、正式 package smoke；npm lock 版本与传递依赖、
    许可证、精确 PURL/SBOM、Notice/`THIRD_PARTY_COMPONENTS.md` 自动一致性；包体积对比。
12. `git diff --check`、相关 Ruff/pytest/py_compile；记录 main、feature、new/common failed nodeids。
13. Monaco 相关文件为零改动。

### 人工和平台验收

- 从设备详情、工具集内置入口和 AC/FIT-AP 上下文打开终端；同时连接两台设备且输出不串线。
- 搜索、清屏、复制粘贴、fit、编码、重连、日志导出和活动操作关闭确认符合现有 UI 规范。
- `UNVERIFIED`：Windows 10/11 正式安装包实测和安全人工验收完成前，`embedded_terminal` 保持
  默认关闭/development；完整退出后还必须确认无残留 SSH、Python、Electron 子进程。
- `UNVERIFIED`：Windows Server 2012 只能在目标机实测后提升等级。阶段 1 不能以“不依赖 ConPTY”
  推导出完整兼容；Electron 43/Node 24、旧 CPU 指令集和 VC Runtime 组合兼容性均未知。

任一凭据泄漏、资源残留、无限缓冲、CSP 放宽、未受控链接/OSC/剪贴板/粘贴、Browser/Server
错误开放、npm 合规闭包缺失、正式包资源缺失或第三方工具回归均阻断阶段 1。

## 阶段 2 fixture 和迁移清点

### 已有脱敏样本

| 厂商 | 命令/语义 | 当前 fixture / 测试 | 结论 |
| --- | --- | --- | --- |
| H3C | `display version` | `tests/fixtures/h3c/display_version.txt`、`tests/test_h3c_parsers.py` | 可进入首批 shadow |
| H3C | `display interface`（含 PVID/Tagged/Untagged/Passing） | `display_interface.txt`、`test_h3c_parsers.py` | 可进入首批 shadow；先按现有真实命令，不擅自改为 brief |
| H3C | `display lldp neighbor-information list/verbose` | 对应两个 fixture、`test_h3c_parsers.py` | 可进入首批 shadow |
| H3C | `display transceiver diagnosis interface` / interface | 对应 fixture、parser 测试 | 可进入首批 shadow |
| H3C FIT-AP | LLDP、光模块诊断、AC AP 资源 | `tests/fixtures/h3c/display_fit_ap_*` 与 `tests/fixtures/h3c/ac/` | 只选择结构稳定子命令；需保持 AC 身份边界 |
| ZTE | `show version` | `zte_5960x_show_version.txt`、`real_c89e4_show_version_redacted.txt` | 可进入首批 shadow |
| ZTE | `show interface brief/detail` | 多个 5960X/C89E4 fixture、`test_zte_zxr10_parser.py` | 可进入首批 shadow |
| ZTE | `show opticalinfo brief/detail` | 多个 threshold/detail/redacted fixture | 可进入首批 shadow；保持 `offline -> no_module` |
| ZTE | `show lldp neighbor brief/entry` | `hzdt10_show_lldp_neighbor_brief.txt`、`hzdt10_show_lldp_entry.txt` | 可进入首批 shadow |
| ZTE | `show running-config switchvlan` | `hzdt10_show_running_config_switchvlan.txt`、`test_zte_vlan_parser.py` | 可进入首批 shadow |
| ZTE | `show vlan` / `show vlan id 71` | 两个 hzdt10 fixture、`test_zte_vlan_parser.py` | 可进入首批 shadow；保持 PVID 来源和冲突警告 |

### 明确缺口

- H3C 没有独立 `display vlan` fixture/生产 parser；当前 VLAN/PVID 主要来自 `display interface`。
  在取得脱敏真实样本和现有业务消费者前，不声明 H3C `display vlan` 支持。
- 现有 fixture 数量不等于型号覆盖；每个模板必须声明 vendor/platform/model/software_version 适用范围。
- 需为每个候选补空输出、分页残留、命令回显、提示符、CRLF/LF、GB18030 转码、字段缺失、
  单位变化和 unsupported fixture。
- TTP 自身模板语法错误、资源缺失和初始化失败必须逐模板隔离，不得阻断 Backend 启动。

### Shadow 比较和切换门禁

统一比较记录数量、规范化接口 ID、LLDP 邻居、VLAN/PVID、光功率、模块在线状态、缺失字段和类型，
状态固定为 `MATCH/PARTIAL_MATCH/MISMATCH/TTP_FAILED/LEGACY_FAILED/UNSUPPORTED`。生产结果始终取
legacy，直到单命令同时满足多份 fixture、一致性、边界样本、真实只读设备、正式包资源和功能开关
回退。任何命令切换都必须独立 PR，不允许按厂商一次性切换。

## 阶段 3～8 关键门禁

### 阶段 3：G6

- 后端先提供稳定 `TopologyGraphDto`、Node、Edge、status/warnings；Vue 不推导核心业务状态。
- 首批只有设备 LLDP 与车内固定拓扑公共化；AC/FIT-AP、MESH 当前链路和站点/AP 布点后置。
- G6 不替代 ECharts；导出 PNG/SVG 使用统一导出协调器；组件卸载必须 dispose。

### 阶段 4：DuckDB/Parquet

- 只试点 MESH；raw 不变，SQLite 保存 Dataset Manifest，Parquet 保存可重建派生行，DuckDB 查询。
- Manifest 至少记录 dataset/source/parser/schema/SHA/row count/time range/relative paths/state/error。
- 状态至少 `PREPARING/READY/FAILED/STALE/REBUILDING`；先写 staging，校验行数和时间范围后原子提交。
- 先测现有路径，再测 100 万行首屏、过滤、聚合、峰值内存和目录大小；未达到目标如实保留旧路径。
- DuckDB 缺失、加载失败、CPU/VC Runtime 不满足或 Dataset 损坏时应用仍启动并回退 SQLite。

### 阶段 5：配置版本

- 兼容扩展现有 snapshot，分别记录 raw/normalized SHA、normalizer id/version、previous snapshot、
  significant change 和 change summary。
- raw 不覆盖；相同 raw hash 不重复文件；raw 不同但 normalized 相同可以记录采集事件但不标显著变化。
- 稳定 Diff/API 可供未来 Monaco 消费，本阶段不修改 Monaco 页面、组件、依赖、测试或 Vite 配置。

### 阶段 6：Syslog 规则包

- raw NDJSON 永远是事实源；规则结果带 parser_version 和 raw file/line 或 event sequence。
- 单个 YAML 规则失败不阻断启动；首批仅 H3C WMESH/IFNET，先 shadow/只读诊断。
- 普通用户不能在线编辑生产规则；后续编辑器即使复用 Monaco，也必须另行审批。

### 阶段 7：scrapli

- 统一 Transport Protocol 稳定后才引入；默认 Existing SSH，按设备 Profile/Feature 选择实验路径。
- 同设备、同只读命令对比登录/命令耗时、输出/解析一致性、失败分类、资源释放、并发和重连。
- 未取得 H3C Comware 7、ZTE ZXR10、GB18030、提示符/system-view、冻结包和目标平台证据前不生产切换。

### 阶段 8：Inventory/基础资料

- 只吸收 Nornir 的分组/继承/单设备结果/部分失败和 NetBox 的最小 Source of Truth 思路。
- 复用现有设备、分组和轨交基础资料，不建立新的 Inventory 数据库、同步服务或管理 UI。
- 规划值和实际采集值分离，来源、采集时间和冲突状态可追溯；不得以规划值覆盖真实采集。

## Monaco 在研边界

当前 `main` 只在工作区快捷键防护选择器中出现 `.monaco-editor` 兼容类名，未包含本 ADR候选依赖。
其他分支正在开发配置对比 Monaco 能力，本阶段不读取其未提交 diff，不合并该分支，也不把它纳入
阶段 0 基线。

后续阶段 1～4、6～8 禁止修改：

- `apps/web/src/views/config-collection/` 的 Monaco 在研页面、组件和测试；
- Monaco 依赖、`apps/web/package.json`/`pnpm-lock.yaml` 中由该分支引入的条目；
- Monaco 专用 Vite、worker、CSP 和测试配置；
- 其他 worktree 的任何文件或未提交修改。

阶段 5 只能提供稳定 Backend DTO/API 和数据模型，不实现或替换 Diff UI。若实施时 Monaco 已合入
`main`，必须从最新主线重新审计后复用其公开接口，仍不得复制组件或回退其实现。

## 发布与兼容门禁

每个新增依赖都要完成：

1. 维护状态、许可证、固定版本和传递依赖清点；
2. Python constraints 或 Node lock 更新；Node 依赖还必须从 npm lock 自动提取精确版本和传递闭包；
3. `open_source_notices.json`、Notice、`THIRD_PARTY_COMPONENTS.md` 和 CycloneDX SBOM 更新，并自动
   校验许可证、精确 PURL 与 lock/SBOM 一致性；
4. PyInstaller `RUNTIME_IMPORTS/RUNTIME_DATAS` 或 electron-builder 资源白名单更新；
5. 完全离线、干净环境安装和构建；
6. Electron CSP、asar/extraResources、Backend 冻结加载和 package smoke；
7. 安装包体积前后对比、升级、修复和卸载验证；
8. Windows 10/11，以及 Windows Server 2012、目标 CPU 指令和 VC Runtime 的分别记录。

Windows 10 和 Windows Server 2012 的内置终端当前均标记 `UNVERIFIED`。能力探测必须在导入可选
二进制依赖之前完成，
可选依赖不得在模块顶层使 Backend 崩溃；探测失败返回 `dependency_unavailable`，关闭 Feature 并
保留旧路径。探测成功也不能自动显示或开启 `embedded_terminal`；只有正式 package smoke、
Windows 10/11 人工验收、安全门和目标系统正式安装包实测证据才能提升对应兼容等级。Windows
Server 2012 还必须单独验证 Electron 43/Node 24、旧 CPU 指令集和 VC Runtime。

## 验证和后续决策

阶段 0 只运行 Markdown 相对链接、文档/目录静态 Guard 和 `git diff --check`，不运行全量 pytest、
pnpm install、前端全量构建或正式打包。阶段 0 没有生产代码、数据库、导出或耗时任务影响。

阶段 1 开始前需要单独确认：

1. `InteractiveTerminalTransport` 是否能在不泄漏凭据的前提下复用现有 Netmiko/Paramiko 连接；
2. 内置终端的托盘驻留默认策略和空闲关闭阈值；
3. xterm addon 最小集合、DOM renderer、包体积和不放宽的正式包 CSP；
4. npm lock/PURL/SBOM/许可证自动闭包以及 Notice/`THIRD_PARTY_COMPONENTS.md` 门禁；
5. Windows 10/11、Windows Server 2012 测试机及真实只读 H3C/ZTE 设备；
6. main 基线失败集合，包括已知 Netmiko 定向失败是否仍存在。

本 ADR 不授权自动合并。每个阶段的 Draft PR 必须陈述修改/未修改范围、数据迁移、安全、回滚、
测试、main/feature/new/common failed nodeids、正式包结果和现场待验证项。
