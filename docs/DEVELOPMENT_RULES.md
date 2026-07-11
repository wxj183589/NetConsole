# NetConsole 开发规则

本文是新增功能和维护存量代码的强制检查表。

## 先判断任务类型

开发前先回答：

1. 是否访问网络、设备、外部命令、数据库、磁盘或大文件？
2. 是否可能执行超过 300ms？
3. 是否包含大循环、批量操作、解析、压缩、图表或报告生成？
4. 用户是否需要进度、取消、日志和失败原因？

超过 300ms 的 IO、CPU 或网络任务不得在 UI 线程执行。重 CPU、重 IO、重网络和批量任务进入 Worker Process；所有导出进入独立 Export Process。

## Job 必备字段和能力

所有普通任务和导出任务必须具备：

- `job_id`
- `task_type` 或 `job_type`
- 可 JSON 序列化的 `params`
- `progress`
- `cancellation`
- 用户可理解的 `error message`
- structured result

Worker 必须支持 `progress / log / finished / error / cancelled`。失败不得只写控制台，UI 必须收到友好消息，traceback 进入诊断日志或事件字段。

## Worker JSONL 协议

- stdout 只能输出一行一个 JSON 对象的 UTF-8 JSONL。
- stderr 只用于 traceback 和诊断输出。
- 原始设备日志、外部命令回显不得直接打印到 stdout。
- 公共编码、解析和输出复用 `services/job_center/worker_protocol.py`。
- handler 中遗留的普通 `print` 会由 worker 重定向到 stderr；新增代码仍应使用结构化 log event。

## 编码边界

- Worker 内部协议和 Job JSON 固定 UTF-8。
- Python 文本读写显式指定 `encoding="utf-8"`。
- SSH/Telnet/SNMP、H3C 回显、MIB、CSV 和历史日志在 Adapter 边界做编码兜底。
- 外部文本按 `utf-8-sig → utf-8 → gb18030 → gbk` 尝试，不能因终端乱码删除中文。

## 导出统一规则

- UI 只创建 `ExportJob`，不得直接写 Excel。
- 输出先写临时文件，成功后替换目标文件。
- 取消、失败和进程异常必须清理临时文件、Job 文件和取消文件。
- Excel 列宽按表头和采样内容自适应，长字段有上限，保留横向滚动/查看能力。
- XLSX 保持 WPS/Excel 兼容、冻结表头、筛选、文本格式和中文字段。
- 目标文件被 WPS/Excel 占用时提供明确关闭文件后重试提示。

## 页面瘦身

页面只保留：

- 布局和控件创建。
- 信号绑定。
- 输入收集和轻量校验。
- loading / empty / success / error / cancelled 状态刷新。
- 结构化结果到 ViewModel 的绑定。

业务判断下沉 Domain Service；展示转换下沉 ViewModel / Presenter；数据读写下沉 Repository；解析下沉 Parser；设备通信下沉 Adapter。

不允许新增巨型 page 文件。触碰现有巨型页面时，以当前用例为边界逐段迁移，不做破坏性全量重命名。

## Dispatcher 和 Handler

- 新任务必须注册到 `services/job_center/handlers/<domain>_jobs.py`。
- 不得向 `services/background_tasks.py` 或 `handlers/legacy_tasks.py` 追加任务。
- `services/background_tasks.py` 只作为兼容入口。
- 跨领域公共能力放 `handlers/common.py` 或正式公共 service，不复制路径和取消解析代码。

## UI 与任务状态

- 推荐使用 `ui/job_action_helper.py::submit_background_job`。
- 导出使用 `ui/export_action_helper.py::submit_export_task`。
- 对话框非模态，任务运行时防重复提交。
- 超过 1 秒显示阶段或进度；可取消任务提供取消入口。
- 页面切换、主题切换不得清空任务状态和日志。
- Worker 不访问 QWidget；数据库连接在 Worker 内创建。

## SNMP 查询边界

- GET、GETNEXT、GETBULK、WALK、SET 从 UI 统一提交 `snmp_query_execute`，页面不得直接创建 `SnmpClient` 或查询 QThread。
- SNMP profile、operation、OID、超时、重试、bulk 参数和 SET 类型必须通过可序列化请求模型传递，禁止跨进程传 client、repository 或 Qt 对象。
- MIB 名称/OID 展示上下文可随请求传入，但 MIB 搜索、全局仓库、H3C 映射、Trap 和 Poll 不进入查询 Job。
- WALK/GETBULK 在批次边界报告进度并检查取消；结果较大时由 Worker 写缓存或分页，页面只绑定结构化行。

## SNMP 批量采集边界

- 多设备采集统一使用 `snmp_collection_execute`，不得为具体设备、OID 或 AC/AP 用例增加零散 task_type。
- 并发按设备限制为 5～50；每设备独立 Client，单设备内 OID 顺序执行，禁止跨线程共享 Client、repository 或 SQLite connection。
- 默认失败策略是记录单设备错误并继续；`stop_on_failure` 仅停止投递新设备，不强制中断正在执行的网络调用。
- 取消必须停止新任务、等待当前请求收敛并只产生 cancelled 终态，不得同时返回 failed/finished。
- 批量缓存必须去敏并原子写入；认证字段只能存在于临时 Job 参数，不能写入结果缓存或日志。
- Batch Collection 是一次性任务，不得在该服务中加入 interval、常驻 Poll、Trap 或 AC 业务字段映射。

## AC Domain 边界

- FIT-AP 资源采集统一通过 `ac_fit_ap_resources_refresh`；页面只传 device_uuid、site_name、source 和路径，不传 Device、连接或 repository 对象。
- AC Domain 决定 CLI/SNMP 来源。H3C CLI 信息更完整时保留 CLI；只有明确 OID 与已验证 mapper 同时存在时才允许 SNMP 结果写入 AC repository。
- `display wlan ap all`、address、radio、LLDP 等命令及其 parser 合并规则保持在现有 Adapter/Service/Parser，不复制到页面或通用 SNMP 层。
- Domain/Worker 内创建 DeviceRepository、AcRepository 和采集 Client；页面不得创建 AC 资源采集 QThread。
- FIT-AP 全量与单 AP 光衰采集统一复用 `ac_fit_ap_optical_refresh`；页面不得创建光衰 QThread、直接调用 H3C 光模块 collector 或重新判断 AP 离线关联。
- 光衰命令、解析、阈值、历史合并及 AP 离线关联保持在现有 AC Optical Domain/H3C collector；交换机无光不得直接改写在线 AP 的 AP 侧异常。
- 光衰异常、AP 离线关联、里程/区间归属、轨旁 AP 业务规则不得下沉到通用 SNMP Collection。
- FIT-AP 是主应用数据，迁移 facade 和任务入口不得修改 schema 或破坏旧资源、历史和扩展信息兼容。
- AC 命令动作统一提交 `ac_command_action_execute`，通过 `action` 区分动作；页面不得创建 `AcCommandActionThread`、连接设备或直接运行 CLI。
- 固化 AP、开启远程登入等危险动作必须在页面提交前保留确认弹窗；Worker 不弹窗，也不得把 `confirm_required` 当作已完成确认的替代品。
- 固化新上线 AP 必须保留 `wlan auto-ap persistent all + save force`；开启 AP 远程登入必须保留 `probe + wlan ap-execute all exec-console enable`，不得改成 SNMP。
- 页面提交的 command_sequence 必须由 Domain 与既有 command profile 再校验。自定义序列只能复用已验证固定序列，不开放任意配置命令。

## Qt 测试生命周期

- 需要创建顶层 QWidget/QDialog 的测试模块可通过 `pytestmark = pytest.mark.usefixtures("qt_page_lifecycle")` 显式启用 `tests/conftest.py` 中的生命周期隔离。
- fixture 在 pytest 进程内强引用唯一 `QApplication`，每条用例后先排空当前事件，再关闭顶层窗口并处理 `DeferredDelete`，避免对象累计到 pytest 最终 GC 时触发 native abort。
- 不得把页面清理 fixture 全局 autouse；带延迟回调、QThread 或 QProcess 的页面必须先确保任务已完成或已取消，再按模块接入。
- 如果某个 Qt 模块仍无法安全共享 `QApplication`，应使用独立 pytest 子进程隔离该模块，不在业务代码中加入测试专用延迟或异常吞噬。

## AP Identity 边界

- AP identity 迁移以 [AP_MODEL_ASSESSMENT.md](AP_MODEL_ASSESSMENT.md) 为基线；现有 `ap_entities` 是内部统一身份基础，不得再新增平行 AP 主表。
- `ap_uuid` 只用于已解析的站点数据库对象；跨模块关联优先规范化 AP MAC。序列号、AC+APID 和 AP 名称只能按来源、站点/AC 作用域和唯一性降级匹配。
- 表内 `id`、AC 原生 `apid/ap_id`、`ap_uuid` 是三种不同语义，接口和测试不得混用。
- AP MAC 与 Radio MAC/BSSID/BBSSID 分层；Peer MAC 是日志观测值，只有带 source/match rule 的 resolver 结果才能说明其对应 AP 或 Radio。
- identity 解析必须返回 matched、unresolved 或 ambiguous；多候选不得静默选第一条，失败不得顺手创建 AP 实体。只有 AC 资源 Repository 写入口可以创建新 `ap_uuid`。
- `site_id` 数据作用域、业务站点 station 和区间 section 分开；section 可以存在而 station 为空。PIS 默认不强制红/蓝网，信号系统按既有规则处理。
- 轨旁业务同时引用 AP identity 与交换机 device_uuid+interface 拓扑 identity；光衰同时引用 AC、AP、接口和在线状态，任何 identity 工具不得承载或改写业务判定。
- MR/Mesh、无线扫描、历史查询、页面展示和导出只能读取统一 identity 结果，写入各自的观测/派生数据，不能回写 AP 主身份。
- 阶段 1 只允许纯 Python identity 工具和 characterization tests，不接生产写流程、不改 schema；后续领域接入必须先做旧/新 shadow comparison 并提供回滚适配器。
- 阶段 1 工具固定在 `services/ap_identity`，不得导入 PySide6、UI、Repository、Job Center、网络连接或光衰/轨旁业务规则。
- Radio/BSSID resolver 默认只使用 Candidate 显式映射；复用 H3C 派生规则时必须通过后续具名适配器和 shadow comparison，不能在通用 resolver 中隐式推导。
- 阶段 2 验收前，生产模块不得导入 `services.ap_identity`；阶段 2 也只能先接 FIT-AP/extension 只读或兼容适配，不得连带迁移光衰、轨旁、MR/Mesh 或导出。
- 阶段 2 统一通过 `services/ac/ac_identity_adapter.py` 接入，adapter 只接收普通 row，不导入 Repository/UI/Worker，不写数据库。
- AP 扩展 preview/commit/refresh/save 的 `identity_shadow` 仅是诊断附加字段；commit/save 必须继续使用旧 service/legacy 写入路径，shadow unavailable、unresolved 或 ambiguous 都不得阻断原流程。
- `identity_changed` 只表示 old/new 状态或候选差异，不授权新 resolver 覆盖旧 key；旧 helper 必须保留为回滚路径。
- 阶段 3 只能在光衰 Domain 内增加 identity shadow，不得改变光衰阈值、AP 离线关联、交换机无光规则、Repository 写入或页面字段。
- 阶段 3 光衰 shadow 统一通过 `services/ac/ac_optical_identity_adapter.py`；仅有交换机接口的记录不得解析为 AP，Radio/BSSID/Peer MAC 不得作为光衰 AP 写入匹配依据。
- 光衰 `identity_shadow` 只附加到 Job result；诊断异常必须返回 `available=false` 且不得改变原任务终态。旧 `AcOpticalService` UUID/name 关联和业务分类结果始终是生产结果与回滚路径。
- 阶段 4 轨旁评估以 [TRACKSIDE_AP_IDENTITY_ASSESSMENT.md](TRACKSIDE_AP_IDENTITY_ASSESSMENT.md) 为准；交换机接口是 topology identity，站点/区间/里程只作位置证据。
- 阶段 4.1 只能在旧轨旁聚合 rows 和旧详情 matches 生成后附加只读 shadow；不得改变候选端口、LLDP/光衰 fallback、行去重、采集范围、缓存、双击定位、状态、导出或历史。
- 轨旁 shadow adapter 只接收普通 row，不导入 UI/Repository/Worker、不写数据库；shadow 失败必须 unavailable 且不得改变加载或详情任务终态。
- 阶段 4.1 统一使用 `services/rail_transit/trackside_ap_identity_shadow.py`；聚合使用 `identity_shadow`，详情使用 `detail_identity_shadow`，页面不得消费这些字段改变显示或选择。
- LLDP neighbor MAC 只能作为 peer observation evidence；interface/port 是 topology evidence，station/section/mileage 是位置 evidence，Radio/BSSID 不作为轨旁 AP MAC 匹配输入。
- 阶段 5 MR/Mesh评估以 [MR_MESH_AP_IDENTITY_ASSESSMENT.md](MR_MESH_AP_IDENTITY_ASSESSMENT.md) 为准；`peer_mac` 是日志观测，Peer Radio、Radio MAC和BSSID/BBSSID不得直接折叠为AP MAC。
- 阶段5.1统一使用`services/mr_mesh_identity_shadow.py`，只在`mesh_log_import`、`online_mr_parse`、`vehicle_mr_mapping_load`旧结果完成后附加只读诊断；不得修改raw parser、mapping/cache、数据库、ACTIVE/STANDBY、主备链、同AP双Radio、短链、乒乓、RSSI或Busy规则。
- MR/Mesh shadow adapter只接收普通row，不导入UI/Repository/Worker/网络或parser，不写parsed DB；候选快照由handler通过现有Repository只读方法构建，shadow失败必须unavailable且不得改变原任务终态。
- Online MR shadow读取parsed DB时必须使用只读连接；Vehicle mapping shadow不得调用带光衰站点回填副作用的`load_trackside_ap_lookup()`。
- Mesh链路明细继续不导出“归属来源”和“Peer Radio MAC”；任何重复MAC诊断不得在阶段5.1改变页面列、报告SQL或导出表头/值。
- 阶段6导出评估以 [EXPORT_FIELD_DEDUP_ASSESSMENT.md](EXPORT_FIELD_DEDUP_ASSESSMENT.md) 为准；必须区分当前页面 Export Process入口与兼容/直接 exporter，不得把同名报告服务视为同一调用链。
- 阶段6.1只允许在旧formatter输入/输出旁路附加小型聚合 diagnostics；不得修改workbook/CSV/NAM、Sheet、表头、报告SQL、解析、页面、主备链、RSSI/min RSSI、Busy、短链或乒乓结果。
- Peer MAC、Peer Radio MAC、AP MAC、Radio MAC和BSSID/BBSSID只可按各自语义统计相同值；相同不等于可删除。现有输入没有安全字段时diagnostics必须`available=false`。
- 导出逻辑 golden 应比较Sheet、表头、关键行值、筛选、冻结窗格、样式和列宽；不得依赖不稳定的XLSX二进制哈希。diagnostics或sidecar失败不得改变原导出终态。
- 阶段6.1 P0统一使用`services/export_identity_diagnostics.py`；Mesh只在旧行进入formatter前流式观察，Online MR兼容报告只在旧位置数组生成后按原表头观察。diagnostics不得持久化、不得生成默认sidecar，也不得成为字段删除或SQL修改依据。
- Mesh Export Process只在finished result附加`export_identity_diagnostics`；`OnlineMrAnalysisReportExporter.export()`继续返回原`Path`，诊断通过只读`result_metadata`暴露。诊断失败必须`available=false`且原导出继续成功。
- 阶段7真实局点观测统一遵守 [AP_IDENTITY_OBSERVATION_PLAN.md](AP_IDENTITY_OBSERVATION_PLAN.md)：只提取聚合字段，不支持的指标写`null`，完整result/items/evidence/raw log/数据库/xlsx不得进入仓库，MAC/IP/名称/路径必须使用campaign HMAC或token脱敏。
- 阶段7阈值只用于决定是否有资格评估只读展示，不是生产强制规则。identity changed非零、作用域/歧义超阈值或RSSI/备链缺失相对基线增加时，继续使用旧生产路径；不得自动修复、删除字段或调整resolver。
- 后续只读展示必须使用独立feature flag、默认关闭、可整体禁用，只展示脱敏聚合和不可用状态，不展示shadow items、samples、evidence或warning明文。
- 阶段8只读展示评估以 [AP_IDENTITY_DISPLAY_ASSESSMENT.md](AP_IDENTITY_DISPLAY_ASSESSMENT.md) 为准。展示层必须先经过严格字段允许列表，未知字段丢弃，`items/samples/evidence/warnings/error`和明文身份/路径不得进入ViewModel、UI、日志或默认报告。
- 阶段8.1可见展示必须等待真实局点试运行、脱敏复核和单一宿主批准；所有flag默认关闭且internal-only。当前没有独立Job Center详情或通用诊断中心，不得为了展示同时修改多个业务页面、增加任务持久化或直接绑定原始result。
- diagnostics disabled/unavailable/failed只影响诊断区域，不得改变原Job/Export终态、成功提示或旧业务结果；全局kill switch关闭展示时不得停止生产任务或删除业务数据。
- 阶段8.1统一使用`ui/diagnostics/diagnostics_summary_view_model.py`消费普通mapping；该模块不得导入PySide6、业务Service、Repository、parser、网络、数据库或文件IO，不得保留原始result引用。
- 阶段8.1的全局/UI逻辑开关缺失时视为关闭；samples开关即使为真也不得暴露明细。当前无统一Job详情宿主，禁止在多个业务页面临时接线；阶段8.2必须另行批准单一宿主。
- 阶段8.2宿主评审以 [AP_IDENTITY_JOB_DETAIL_HOST_ASSESSMENT.md](AP_IDENTITY_JOB_DETAIL_HOST_ASSESSMENT.md) 为准。当前 manager/helper 只发出瞬时终态，不得为诊断展示在 Job Center 保存完整 result、建立原始事件持久化或反向导入 UI。
- 阶段8.3在统一任务详情启动点获批前保持hold。未来dialog只能接收`DiagnosticsSummaryViewModel`，不得接收raw result；入口必须显式、非模态、默认关闭，关闭后不得保留跨Job/局点引用。

## 提交前检查

- 新增/修改 Python 文件通过 `python -m py_compile`。
- 对应 pytest 覆盖成功、失败、空数据、取消。
- 搜索 UI 页面是否出现网络连接、Excel 保存、大文件解析和长查询。
- 搜索 Worker 是否导入 UI page。
- 检查旧 `BackgroundJob / BackgroundProcessManager / run_background_task / ExportJob / ExportProcessManager` 导入仍可用。
- 说明是否影响数据库结构、导出模板、编码策略、日志和中文显示。
