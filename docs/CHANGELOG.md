# NetConsole 更新日志

## v1.3.8 - 2026-07-12

### 本次修复

- 新增可运行的 Electron Desktop 安全基础：复用唯一 Vue/FastAPI，使用 sandboxed 单文件 preload、白名单 IPC、动态回环 Python 后端、通过 stdin 传递的每次启动临时会话令牌与优雅退出控制管道；Vue 增加 Browser/Electron Runtime Adapter 和最小桌面状态区。当前处于 Electron 与 Qt 并行迁移阶段，只完成源码开发/生产资源模式；Electron 安装包、签名、升级、托盘与业务模块替换尚未完成。
- 启动架构第一阶段的 Launcher/WebHost 子项改为无 Qt Launcher：新增 `auto/qt/web/server`，完成轻量能力探测后创建唯一 FastAPI Core Runtime，再启动 Qt、本机浏览器或无 Shell Server；`web/server` 通用导入链不加载 PySide6，Qt WebConsoleHost 复用 Launcher 服务，普通启动增加单实例和启动诊断。Server 在远程鉴权完成前只允许回环绑定，Qt probe 使用不加载 FastAPI/Core 的轻量入口。旧 `--web-shell`、Qt 页面及提权网络管理入口继续兼容；Native Bridge、EmbeddedLayout 和旧 Qt 页面服务容器统一尚未完成。
- 补齐发布链遗漏的 `web_frontend_meta` 校验模块，继续强制核对 Web `index.html`、构建身份、构建时间和导航 schema，避免发布测试在收集阶段失败。
- 修复 Desktop WebHost 可能继续加载旧 Vue `dist` 的问题：源码/冻结模式使用明确资源边界，构建生成并校验前后端 build id；Web 导航改由统一 Registry 按固定模块顺序渲染，补齐深色子菜单、侧栏折叠、窄屏抽屉和最小可操作窗口，并建立 Qt/Web 功能对等矩阵。未完成页面仍不开放占位入口，Qt 页面继续保留。
- 完成 Online MR 阶段 5B-13B：在线列车通信 MR 详情新增独立 LOCAL/AGENT 页签，Desktop WebHost 以严格 `127.0.0.1`、短期会话、默认关闭开关和字段白名单接入单 Agent start/status/normal stop；远端 package 继续由正式下载器/Importer 收敛，不新增强停、删除、命令、URL 或 Go Agent 改动。新增随机回环端口 Fake Agent 全链路验收，5C-10A-B 与 5B-13A-A 真实设备验收在列车下电期间继续冻结。
- 完成 Web 演进阶段 5B-2A：新增纯 Python `OnlineMrApplicationService`、LOCAL 执行入口和所属局点 `tasks.db` 中的 Task/Session 映射；任务快照显式记录局点/设备摘要，会话通过 `online_mr_session_created` 结构化事件幂等关联，业务阶段与 Job Center 七状态保持分离。
- 统一 Online MR 启动失败与遗留会话状态：会话创建后的初始连接失败固定落为 `FAILED`，显式恢复核对将失去活动宿主的旧会话标为 `ABORTED`，均保留 raw 且不触发解析或打包；Legacy Qt、自动时长、Traffic/Agent、API/Vue 和正常停止/最终化顺序未修改。
- 完成 Web 演进阶段 5B-1：新增 Online MR 会话/日志/指标/Artifact/备注 DTO 与纯 Python 只读 `OnlineMrQueryService`，兼容旧或不完整会话、缺表解析库、日志增长和安全相对引用；Qt Legacy 页面、采集启停、Traffic/Agent、FastAPI/Vue 与 schema 均未修改。
- 固定 Online MR 停止、最终化和打包契约：Traffic、SSH、raw writer 与摘要完成 flush 后才允许最终解析和原子发布 ZIP；强停或文件稳定性未知不得伪装完成，必须保留 raw 并允许后续重新最终化。
- 完成 Web 演进阶段 4D：Qt Web Shell 改为非阻塞等待本地 FastAPI，增加启动/失败重试页、外链系统浏览器跳转、JavaScript 日志和退出前 WebSocket 卸载；关闭后不残留 Uvicorn/Python/QtWebEngine 进程，普通 Qt 入口继续不依赖 FastAPI 或 Node。
- 修复轨旁 AP 业务详情联表数据含嵌套字典时的显示文本提取异常，避免该详情页在归一化展示值时触发 `TypeError`。
- Agent 发布工具统一从 `resources/tools/windows-x64/` 取用 fping/iPerf3，交付包只复制 Agent 所需工具；IPOP 不再作为 Agent 运行依赖。
- 完成 Web 演进阶段 4C：新增 Traffic REST API、按 Run 订阅的 `/ws/traffic/{traffic_run_id}` 和 Vue“网络工具 / 流量测试”页面，支持 iPerf Server、iPerf Client、高频 Ping、实时带宽/RTT 图、日志、历史、停止和原配置重试；高频样本继续不进入全局 `/ws/tasks`。
- 完成 Web 演进阶段 4B-2：新增 `TrafficTestApplicationService`、本地/Agent 执行适配、远端 Supervisor、Controller/Agent Task 映射、持久事件流和 Controller 重启恢复；尚未创建 Traffic REST/WebSocket 或 Vue 页面。
- 新增每局点 `traffic_runs.sqlite`，只保存 Traffic Run 索引、Agent 映射和独立高频 Ping 样本；iPerf interval 继续只写既有 `iperf_results.sqlite`，Agent 事件重放使用远端事件键幂等去重。
- 新增纯 Python `LocalProcessAdapter` 和三个 Traffic Job handler；高频样本不进入全局 Task Event 表。本地 fping `packet_size` 已传入 `-b`，多目标 Ping 批量落库，timeout 不再伪造 RTT=0。
- Agent Token 继续只保存在会话级 Vault；Agent Traffic 启动、轮询和停止留在 Controller 进程内。无 Token 恢复标记 `CREDENTIAL_REQUIRED`，Controller 停止轮询不会停止远端任务。
- 完成 Web 演进阶段 4B-1：Windows Go Agent 新增真实 `fping` 任务、每任务增量事件游标、结果描述和 iPerf 3.20 强类型参数；`ping_probe` 继续明确为 TCP Connect，不伪装为 ICMP Ping。
- Python `AgentHttpClient` 新增 fping/iPerf 启动、任务查询/停止、事件和结果的强类型 DTO/方法；本阶段未创建 Traffic 数据库、应用服务、Controller 轮询、FastAPI Traffic API 或 Vue 页面。
- 完成 Web 演进阶段 3：新增每局点 `agents.db`、Agent 配置/运行快照分离、`AgentControllerService`、会话级凭据、健康检查调度、Agent REST API、`/ws/agents` 与 Vue Agent 管理页面；本阶段不提供任何业务任务启动接口。
- Windows Go Agent 新增向后兼容的 `GET /api/v1/capabilities`；Controller 对旧 Agent 保留未知能力，不根据操作系统猜测。Element Plus 改为按需导入，Dashboard、任务中心与 Agent 页面按路由分包，移除阶段 2 约 1 MB 单包警告。
- 统一窗口标题为 `NetConsole v1.3.8 by WXJ`，分离 Git SSH 推送地址与关于页 HTTPS 浏览地址；修复弹出模块错误复用“设备管理”的当前页归属。
- 统一轨旁 AP 规划、轨旁 AP 业务和在线解析表格的选择、复制、列宽与上下文菜单；日志中心首次进入异步加载并明确显示加载/空/错误状态，启动期不再记录逐次 geometry 噪声。
- 网络工具移除本地网卡配置入口，工具箱移除“本机路由”；IPOP v4.1 改为用户在系统设置中配置的可选外部工具，所有正式发布包均不携带其二进制；Online MR 移除独立“收起设备列表”按钮并保留自动折叠逻辑。
- 功能开关配置页改为仅源码开发态可见，新增可持久化“工程师打包”选项和 engineer edition；系统设置中未接入运行逻辑的参数统一禁用并标注“未实现”。
- 新增统一结构化文件契约和强导入校验；XLSX/CSV/JSON/ZIP 校验模块、类型、schema、必要结构、字段、非空数据和 ZIP 路径安全，主要导入入口在业务层先完整校验再写入。

### 文档

- 以当前代码、测试和近期提交为基线，全面同步根 README、架构、Job/Export、重构地图、Feature、数据路径、构建、UI 表格和业务专题文档。
- 新增 Online MR 实时采集与 SNMP Center 专题，明确实际状态、命令、并发、缓存、数据目录、查询/导出路径和功能限制。
- 明确 Job Registry 当前注册 86 个任务、分属 11 个 handler 模块但领域迁移未完成，设备批量线程仍未进入 Job Center；AP Identity 继续只读 shadow/diagnostics，阶段 8.3 可见宿主保持 hold。

### 架构
- 完成 Web 演进阶段 2：每局点 `tasks.db` 正式保存任务快照和结构化事件，新增 `TaskRepository`、`TaskEventHub`、恢复核对、任务 REST API 与 `/ws/tasks`；Qt 继续通过兼容 signals 使用原 Job/Worker 协议。
- 新增 Vue 3/TypeScript/Vite/Element Plus/Pinia/Vue Router 基础工程，提供 App Layout、Dashboard 空页和任务中心列表/详情/日志/停止入口；FastAPI 提供 `apps/web/dist` 和 SPA fallback。
- 新增 Registry 级 `FeatureStatus`；SNMP Center 与无线勘测设为不可由 profile 重开的 `DISABLED`，Qt 导航/页面入口和 Web 路由关闭。网络工具无线扫描单独登记并保持可用，Web 迁移为 HOLD。
- 新增 Web 演进阶段 0/1 基线：保留现有 Python Core，增加 Desktop/Server `RuntimeMode`、Pydantic API DTO、FastAPI 健康检查/OpenAPI 和不替换当前主窗口的 `--web-shell` 实验入口；Vue 与业务 API 尚未开始。
- 将 Job 文件、取消文件、七状态、JSONL 分块解析、终态和清理下沉到无 PySide6 依赖的 `TaskRuntime`/`TaskApplicationService`；原 `BackgroundProcessManager` 保留为 Qt/QProcess Adapter，现有 JobSpec、Registry、handlers、Worker 和 Export Process 不变。
- 本阶段冻结 SNMP Center 与 `module.wifi_survey`，未修改 MR/MESH/AP/光衰/iPerf/SNMP/无线勘测算法、数据库 schema 或 Agent 协议。
- 已建立 NetConsole 分层架构规范。
- 已引入并整理 Job Center 规则，以领域注册表替代巨型任务分发。
- 已明确 UI 线程治理、Worker Process、Export Process 和 Domain Service 边界。
- 已为后续 AC / SNMP / MR / iperf / Export / Agent 开发提供统一规范。
- 已将车载 MR 在线 SSH 实时采集迁入长运行 Job / Worker Process，页面不再执行 SSH、采集循环、大日志解析或停止后打包。
- 已集中在线 MR 命令序列与会话路径，停止时协作取消并清理 SSH/文件句柄，压缩失败保留原始日志；Worker stdout 仅输出 UTF-8 JSONL。
- 在线 MR 手动/实时解析与分析报告分别接入 Job Center 和 Export Process，主程序侧保留可替换执行端边界。
- 新增独立 Windows x64 Go Agent V1：提供 HTTP/Web 目标管理、iPerf server/client、并发 TCP 探测、MR SSH 原始采集、统一任务状态、Token 鉴权和原子 ZIP 打包；Windows 工具统一由 ToolManager 读取 `windows-x64/{iperf3,fping}` 配置路径，并通过 API/Web 展示检测结果，不扫描旧目录。Agent 不主动注册/上传，Python 主程序的多 Agent 管理页面尚未接入。
- SNMP GET、GETNEXT、GETBULK、WALK、SET 查询执行链路已接入 `snmp_query_execute`；Worker 负责创建查询服务、格式化结果和写入兼容缓存，页面不再直连 SNMP Client 或查询 QThread。
- SNMP 查询支持统一进度、异常与协作取消事件；MIB 浏览/搜索、全局 MIB 仓库、H3C 映射、Trap、Poll 和产品参考库保持原状。
- 新增 `snmp_collection_execute` 与 `SnmpCollectionService`，支持多设备、多 OID、5～50 并发、失败重试、部分成功汇总和协作取消；每设备使用独立 SNMP Client。
- SNMP 批量结果以原子 JSON 缓存保存任务摘要和去敏 records，包含 device_id、OID、value、timestamp、success、error，不新增数据库表。
- 新增 `services/ac` facade，FIT-AP/AP状态/Radio/LLDP 资源刷新复用既有 `ac_fit_ap_resources_refresh` 进入 Job Center；H3C CLI collector、parser、raw log 和 repository 规则保持不变。
- AC 页面不再为资源刷新创建 `AcResourceCollectThread`；取消、异常和完成改为统一 Job 终态。SNMP Collection 仅在提供明确 OID 与已验证映射器时使用，避免未经验证的数据覆盖 FIT-AP 主数据。
- 新增 `AcOpticalService`，FIT-AP 全量与单 AP 光衰采集复用 `ac_fit_ap_optical_refresh` 进入 Worker；页面不再创建 `FitApOpticalCollectThread` 或直接调用光衰 collector。
- 光衰迁移保留 H3C CLI 命令、解析、阈值、重试、历史合并及 repository 规则；AP 离线关联与交换机侧光模块状态在 Domain 层完成，不修改 AP 统一模型、轨旁业务或数据库结构。
- 新增 `AcCommandService` 与 `ac_command_action_execute`，AC 页面固化新上线 AP、开启 AP 远程登入等现有命令动作改由 Worker Process 执行，不再创建 `AcCommandActionThread`。
- 命令迁移保留原确认弹窗、H3C command profile、命令白名单、连接/编码、逐命令超时、尾部 read-timeout 特殊成功判定及 raw log；固化 AP 继续执行 `wlan auto-ap persistent all + save force`，远程登入继续执行 `probe + wlan ap-execute all exec-console enable`。
- 完成 AP 统一模型阶段 0 评估，新增 AP 数据来源、标识/字段矩阵、消费者读写边界、不可破坏业务规则、风险清单和阶段 1～6 迁移路线。
- 评估确认现有 `ap_entities` 应作为统一 identity 基础，不新增第二张 AP 主表；本阶段未修改生产模型、数据库 schema、Repository 写入、轨旁/光衰/MR/Mesh 规则、页面或导出字段。
- 完成 AP identity 阶段 1，新增不可变 Identity/Radio/Location/Observation/Candidate/Evidence 模型、严格 MAC/名称/里程规范化、保守 resolver 和六类只读 row adapters。
- 新工具尚未接入任何生产流程，不写数据库、不访问 UI/Worker/网络，也不承担光衰、轨旁或 MR/Mesh 业务判断；Peer 只命中 AP MAC时保持 unresolved 并记录低置信证据。
- 完成 AP identity 阶段 2，新增 AC FIT-AP/扩展信息 shadow adapter 与结构化报告；统计 matched、unresolved、ambiguous、identity_changed、name-only、MAC-like name 和缺失 AC 作用域。
- `fit_ap_extension_preview/commit`、`ac_ap_extensions_refresh/save` 只附加 `identity_shadow`；旧 preview/result 字段、commit/save service、legacy helper、Repository SQL、schema、UI 和导出保持不变。
- 完成 AP identity 阶段 3，新增 AC 光衰只读 identity adapter；区分 AP 侧、交换机侧、合并和离线记录，统计 matched、unresolved、ambiguous、identity_changed、interface-only 和缺失 AC 作用域。
- `ac_fit_ap_optical_refresh` 的 load/collect、all/single 只附加 `identity_shadow`；仅交换机接口、Radio/BSSID 和 Peer MAC 不会被当作 AP identity，shadow 失败不改变原光衰任务结果。
- 原 AP 在线/离线、交换机无光、阈值、H3C 采集/解析、历史合并、Repository SQL、schema、UI 和导出字段保持不变。
- 完成 AP identity 阶段 4 轨旁业务只读接入评估，梳理主页面与兼容 Job、FIT-AP/扩展/LLDP/光衰/离线台账聚合、双击详情、缓存和历史链路。
- 评估确认轨旁行必须同时保留 AP identity 与交换机 UUID+接口 topology identity；当前 serial/MAC/name 和全量详情 fallback 缺少显式 AC 作用域，阶段 4.1 只能旁路记录差异。
- 本阶段未修改轨旁生产代码、lookup、缓存、双击定位、页面/导出字段、Repository SQL、数据库 schema、光衰规则或 MR/Mesh 规则。
- 完成 AP identity 阶段 4.1，新增纯 Python 轨旁 identity shadow service；统计 matched、unresolved、ambiguous、identity_changed、name-only、缺失 AC 作用域、interface-only、LLDP-only 和 optical fallback。
- 轨旁主 snapshot 与兼容 Job 仅在旧 rows 后附加 `identity_shadow`；详情 resolver 仅在旧 matches 后附加 `detail_identity_shadow`，shadow 失败不改变 finished 和原结果。
- 双击详情、候选端口、当前/历史 LLDP、光衰接口 fallback、采集范围、行排序/分页、缓存、导出、Repository SQL和数据库 schema保持不变。
- 完成 AP identity阶段5 MR/Mesh resolver shadow评估，梳理离线MESH、Online MR、Vehicle MR的数据来源、Peer/AP/Radio字段语义、lookup差异、主备链依赖与阶段5.1接入点。
- 评估确认离线/Online仅部分复用`MeshPeerMappingService`，Online页面和Vehicle MR仍有独立缓存/旧lookup；Peer MAC、Peer Radio、BSSID和AP MAC不得折叠。
- 记录Online MR报告重复MAC列、离线section持久化不完整、无作用域名称和Vehicle lookup副作用等现有风险；本阶段未修改生产代码、parser、mapping/cache、schema、业务规则、页面或导出。
- 完成AP identity阶段5.1，新增纯Python `MrMeshIdentityShadowService`；统一统计matched/unresolved/ambiguous、identity变化、Peer/AP/Radio重复MAC、Radio/BSSID-only、name-only和缺失AC作用域。
- `mesh_log_import`、`online_mr_parse`、`vehicle_mr_mapping_load`仅在旧result后附加`identity_shadow`；诊断异常返回`available=false`，原任务仍保持finished。
- Candidate只读来自FIT-AP、`ap_entities`和AP扩展；离线只读旧mapping/cache，Online MR只读parsed DB，Vehicle mapping不调用带站点回填副作用的旧lookup。parser、DB写入、主备链、短链、乒乓、RSSI、UI和导出字段保持不变。
- 完成AP identity阶段6导出字段去重诊断评估，盘点MR/Mesh、Online/Vehicle MR、轨旁AP、AC光衰、FIT-AP、OmniPeek和无线扫描导出入口、字段语义与现有契约测试。
- 评估区分Online MR当前页面Export Process报告与兼容直接详细报告；后者存在PeerMac、AP MAC、Peer Radio MAC三列同源风险，本阶段仅记录，不修改SQL、表头或行值。
- 阶段6只设计阶段6.1只读diagnostics；未修改任何生产Python、数据库schema、Repository SQL、parser、workbook/CSV/NAM、样式、列宽、WPS/Excel兼容、页面或业务统计。
- 完成AP identity阶段6.1 P0，新增纯Python `ExportIdentityDiagnostics`；Mesh链路明细以流式旁路计数并在Export Process finished result附加元数据，Online MR兼容详细报告在旧rows后附加`result_metadata`。
- diagnostics覆盖Peer/AP/Peer Radio重复、MAC-like名称、Radio/BSSID-only、缺失MAC/min RSSI/备链和字段存在性；异常降级为`available=false`。原workbook、Sheet、表头、SQL、三列同源值、样式、列宽、筛选、冻结、parser和业务规则未改，默认不生成sidecar。
- 完成AP identity阶段7真实局点只读观测方案，覆盖AC扩展、光衰、轨旁、MR/Mesh、Mesh导出和Online MR兼容报告六类结果，定义运行步骤、统一指标、采样范围、风险分级、回滚和阶段8决策门。
- 阶段7规定MAC/IP/名称/路径使用campaign HMAC或token，完整result/items/evidence/raw log/SQLite/xlsx不得提交；阈值只作评估门槛。本阶段未新增脚本、sidecar、UI或生产业务改动。
- 完成AP identity阶段8只读展示方案评估，核对六类shadow/diagnostics真实结构，定义安全聚合允许列表、禁止字段、UI/报告候选、默认关闭、全局kill switch、不可用状态和权限边界。
- 阶段8确认当前没有独立Job Center任务详情或通用诊断中心；阶段8.1必须等待真实局点观测准入并只选一个维护宿主。本阶段未实现UI、feature flag、报告、数据库、sidecar或生产逻辑。
- 完成AP identity阶段8.1最小实现，新增默认关闭的纯Python `DiagnosticsSummaryViewModel`；只读取三类既有result metadata的允许列表聚合，过滤明细、身份、路径和未知字段，并将异常安全降级。
- 当前没有统一Job详情宿主，因此未新增Qt组件、页面入口或持久化；风险等级只提供只读建议，不改变Job/Export终态、resolver、数据库、导出文件或业务规则。
- 完成AP identity阶段8.2 Job详情宿主接入评审，梳理普通Job、Export、Online MR长任务、AC资源/光衰、轨旁和MR/Mesh七类终态result流转，并比较六类候选宿主。
- 评审确认当前没有任务详情/历史/统一结果面板或诊断中心；未来首选只接收ViewModel的显式非模态任务详情弹窗，但统一启动点批准前阶段8.3保持hold。本阶段未修改生产Python、Qt UI、feature flag、数据库、导出或业务结果。

### 测试
- 新增 Go Agent 的目标脱敏/原子写入、Token 鉴权、工具路径/DLL/结构化错误、任务互斥/停止/打包、Windows 子进程工作目录与输出、TCP 探测、假 SSH 多 Shell 采集和 ZIP 原子替换测试；Windows 本机已完成 iPerf TCP/UDP 与持续任务停止冒烟。
- 新增可按测试模块启用的 Qt 页面生命周期 fixture，修复 Vehicle MR 测试全部通过后在 pytest 最终 GC 阶段触发 `0xc0000374` 的问题。
- Qt fixture 保持单一 `QApplication` 强引用并逐条清理顶层窗口；带异步任务的页面不做全局强制清理，避免中断仍在运行的 QProcess。
- 新增 SNMP 请求模型兼容、五类操作 handler、Worker JSONL 成功/异常/取消、结果缓存和页面提交/状态恢复测试。
- 新增 100 设备并发、部分 timeout、重试、停止策略、取消、JSONL、去敏缓存和内部提交接口测试；增加默认跳过的真实设备 GET/WALK/GETBULK smoke 框架。
- 新增 AC Domain 的 CLI/SNMP 策略、未映射拒绝、Job finished/failed/cancelled、页面 Job 提交和依赖边界测试；AC 既有业务回归保持通过。
- 新增 AC 光衰批量/单 AP、离线关联、交换机无光不误判、采集失败、部分成功、取消单终态、UI 提交与状态恢复测试。
- 新增 AC 命令顺序、安全白名单、结构化错误、Job 成功/失败/取消、Worker JSONL 防污染、确认弹窗和 UI 终态恢复测试。
- 新增 36 个 AP identity characterization tests，覆盖 MAC/名称/UUID/APID 作用域、跨 AC 歧义、显式 Radio/BSSID、Peer observation、位置辅助证据、PIS/信号网络域和只读依赖边界。
- 新增 15 个 AC identity adapter/Job 兼容测试，覆盖 old/new 一致、unresolved、ambiguous、候选变化、作用域、Radio/BSSID 保护、shadow 失败不阻断及旧写入路径保留。
- 新增 AC 光衰 identity shadow 测试，覆盖 AP/交换机/离线记录、跨 AC 歧义、name-only、H3C MAC、Radio/BSSID/Peer 边界、Job load/collect/single 兼容、失败隔离和回滚路径。
- 新增轨旁 identity shadow 测试，覆盖 UUID/MAC/name、跨 AC 歧义、interface/location/LLDP/Radio/BSSID保护、主 snapshot/兼容 Job、详情 fallback、失败隔离和输入不变。
- 新增MR/Mesh identity shadow测试，覆盖Peer MAC低置信边界、显式Radio/BSSID、duplicate MAC诊断、old/new变化、section-only、Vehicle name-only、三个Job兼容和失败隔离。
- 新增Diagnostics Summary ViewModel测试，覆盖默认关闭、三类来源、export别名、白名单过滤、samples禁用、安全状态、风险建议和异常不影响业务结果。

## v1.3.7 - 2026-07-08

### 新增
- 新增磁盘清理入口，用于扫描和清理软件运行日志、缓存和临时文件。
- 新增开源许可说明入口，展示第三方组件、版本、许可证和用途。

### 优化
- 优化启动流程，主窗口优先显示，日志清理和缓存清理延后到后台执行。
- 优化 MR 原始 MESH 日志分析大数据页签加载体验，减少 UI 卡顿。
- 优化车载 MR 离线收集分析 Excel 报告，默认输出诊断型汇总、问题、切换、MESH 质量和证据类 Sheet，不再默认导出大体量明细和趋势图。
- 优化 MR 原始 MESH 链路明细导出字段，移除“归属来源”和“Peer Radio MAC”，保留现场排查需要的 Peer MAC、对端射频口、归属信息和源定位字段。
- 优化文件管理设备侧操作为只读下载模式。

### 修复
- 修复车载 MR 收集分析图表 tooltip 残留和遮挡问题。
- 修复功能开关默认注册和空值回退导致的模块页丢失问题。
- 修复 MR 原始 MESH 主链路建链顺序和 Active 主链路区段 RSSI 统计不一致问题，确保平均、最低、最高和 P10 RSSI 来自同一组有效样本，缺失数据统一显示为 N/A。
- 修复 MR 原始 MESH 导出中“平均 RSSI/最高 RSSI 有值但最低 RSSI 为空”的问题，单样本区段保持平均、最低、最高一致。

## v1.3.6 - 2026-07-06

### 优化
- 优化车载 MR 在线收集、Mesh 日志分析和轨道交通相关页面体验。
- 增强日志中心分页、中文化和运行日志清理能力。
- 优化无线扫描页面的基础交互和导出体验。

### 修复
- 修复部分设备采集和解析结果显示不一致问题。

## v1.0.0 - 2026-06-12

### 新增
- 初始版本包含设备管理、无线扫描、车载MR在线收集和基础日志查看能力。
