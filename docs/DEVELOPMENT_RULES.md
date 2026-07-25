# NetConsole 开发规则

本文是新增功能和维护存量代码的强制检查表。

## 先判断任务类型

开发前先回答：

1. 是否访问网络、设备、外部命令、数据库、磁盘或大文件？
2. 是否可能执行超过 300ms？
3. 是否包含大循环、批量操作、解析、压缩、图表或报告生成？
4. 用户是否需要进度、取消、日志和失败原因？

超过 300ms 的 IO、CPU 或网络任务不得在 UI 线程执行。重 CPU、重 IO、重网络和批量任务进入 Worker Process；所有导出进入独立 Export Process。

## 下一阶段 UI 与分层边界

- 当前产品形态是 Python Core + FastAPI 永久业务层、Vue 唯一主界面和 Electron 桌面外壳；Qt 源码、运行时和入口已删除，历史行为只通过 Git 与最终迁移矩阵追溯。
- 不新增 Qt 业务页面或 Qt 专用业务逻辑。新功能默认沿共享规则/Application Service -> FastAPI -> Vue 建设。
- Vue 与 Electron 只负责表现和受控本机能力；FastAPI Router 只负责 DTO、鉴权、调用 Application Service 和响应映射。
- Vue、Electron 和 Router 均不得直接操作 Repository、SQLite、设备命令、SSH/SNMP 或业务文件。
- Electron 安全基础已进入实现期；只允许 `apps/desktop_electron` 中的窗口、Python 生命周期和白名单 Bridge，不得新增第二套 Renderer/业务 Core。路径只能使用当前原生对话框授予的临时能力，禁止任意命令、程序或未授权路径。
- SNMP Center、通用 MIB/OID 平台与无线勘测已删除，不得恢复代码、资源、依赖或入口；网络工具无线扫描是独立保留能力。

详细规则见 [下一代架构](ARCHITECTURE_NEXT.md) 与 [下一阶段开发指南](DEVELOPMENT_GUIDE.md)。

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
- SSH/Telnet/SNMP、H3C 回显、CSV 和历史日志在 Adapter 边界做编码兜底。
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
- Worker 不访问 DOM、Renderer 或 Electron 对象；数据库连接在 Worker 内创建。

## 设备管理 SNMP 边界

SNMP 仅作为设备管理的只读连接测试与基础识别适配器存在，不是通用查询或采集平台。

- 只支持 SNMP v1 和 v2c；禁止新增 SNMPv3 用户、安全级别、认证/加密协议、Context 或密钥字段。
- 只允许 RO community；禁止 RW community、SET 和任何配置写入。
- Application Service 可调用受限的 GET、GETNEXT 和有行数上限的 WALK，用于 `sysName`、`sysDescr`、`sysObjectID`、`sysUpTime` 与接口描述等固定基础 OID。
- Vue、Router 和设备页面不得接收任意 OID、操作类型、MIB 上下文或设备地址后直接执行请求。
- community 只能存在于设备凭据边界和短期调用参数，不得进入 API 响应、任务结果、缓存或普通日志。
- 不得恢复通用查询、批量采集、GETBULK、Trap、Poll、拓扑、MIB/OID 字典或产品参考平台。

## AC Domain 边界

- FIT-AP 资源采集统一通过 `ac_fit_ap_resources_refresh`；页面只传 device_uuid、site_name、source 和路径，不传 Device、连接或 repository 对象。
- AC Domain 决定 CLI/SNMP 来源。H3C CLI 信息更完整时保留 CLI；只有明确 OID 与已验证 mapper 同时存在时才允许 SNMP 结果写入 AC repository。
- `display wlan ap all`、address、radio、LLDP 等命令及其 parser 合并规则保持在现有 Adapter/Service/Parser，不复制到页面或通用 SNMP 层。
- Domain/Worker 内创建 DeviceRepository、AcRepository 和采集 Client；页面不得创建 AC 资源采集线程或进程。
- FIT-AP 全量与单 AP 光衰采集统一复用 `ac_fit_ap_optical_refresh`；页面不得创建私有光衰任务、直接调用 H3C 光模块 collector 或重新判断 AP 离线关联。
- 光衰命令、解析、阈值、历史合并及 AP 离线关联保持在现有 AC Optical Domain/H3C collector；交换机无光不得直接改写在线 AP 的 AP 侧异常。
- 光衰异常、AP 离线关联、里程/区间归属、轨旁 AP 业务规则不得下沉到通用 SNMP Collection。
- FIT-AP 是主应用数据，迁移 facade 和任务入口不得修改 schema 或破坏旧资源、历史和扩展信息兼容。
- AC 命令动作统一提交 `ac_command_action_execute`，通过 `action` 区分动作；页面不得创建 `AcCommandActionThread`、连接设备或直接运行 CLI。
- 固化 AP、开启远程登入等危险动作必须在页面提交前保留确认弹窗；Worker 不弹窗，也不得把 `confirm_required` 当作已完成确认的替代品。
- 固化新上线 AP 必须保留 `wlan auto-ap persistent all + save force`；开启 AP 远程登入必须保留 `probe + wlan ap-execute all exec-console enable`，不得改成 SNMP。
- 页面提交的 command_sequence 必须由 Domain 与既有 command profile 再校验。自定义序列只能复用已验证固定序列，不开放任意配置命令。

## 数据库与路径规则

- Repository 是 SQLite 访问入口；UI 不直接拼接复杂 SQL，不跨线程/进程共享 connection。
- 使用统一 SQLite helper、busy timeout 和受控 WAL 初始化；并发 worker 各自打开并关闭连接。
- 普通新增表、字段和索引必须提供安全升级与兼容读取路径。设备管理、FIT AP 等主应用库禁止静默删除、重建或丢字段。
- schema 严重不匹配需要重建时，先创建可识别备份并由用户选择；会话 parsed 数据库可重建，但 raw 事实来源必须保留。
- 路径统一通过 `PathResolver`；生产代码和文档不得写开发机绝对路径。自动清理只处理白名单日志、缓存和临时目录。

## 文件与目录归位（强制）

所有新增文件先分类，再落到唯一职责目录；不得因为启动方式、IDE 工作目录或临时排障而创建第二套运行目录。

- 生产、源码开发和打包运行统一使用安装器登记的 `HKLM\Software\NetConsole\DataRoot`，由 `PathResolver` 派生 `sites/`、`runtime/`、`agents/`、`migrations/` 和 `staging/`。未配置数据根必须停止启动，禁止回退到 `LocalAppData`、用户目录、仓库、安装目录、当前工作目录或系统临时目录。
- `LocalAppData\NetConsole`、`LocalAppData\NetConsole\Development`、仓库根 `data/` 和 `.local/` 只能作为受控迁移的只读来源；活动进程不得写入这些路径。发现它们在迁移完成后仍有新文件或 SQLite WAL/SHM，先停止旧进程并执行增量迁移，不能直接删除。
- Agent 的真实 `config.json`、`targets.json`、任务、日志和采集包只允许位于 `<data_root>\agents\local\`；`apps/agent/resources/config/` 只保存脱敏模板。配置中的 Token、密码、community 和私钥不得进入仓库、普通日志或迁移报告。
- 源码树只保存源码、版本化配置、资源、测试样本、文档和维护脚本；数据库、原始回显、抓包、采集会话、报告、缓存、安装包和构建产物不得写回源码目录。测试必须使用显式 `RuntimeMode.TEST` 与 `D:\NetConsoleTestData\<run-id>`。
- 迁移必须在所有相关进程退出后执行 dry-run；发布前用 SHA-256 和 SQLite `quick_check/integrity_check` 复核，目标已有不同内容时写入 `migrations/conflicts/`，不得覆盖目标。每次 apply 都生成 manifest，源目录在核验和留存策略确定前不得删除。
- 清理只能处理已白名单的缓存、临时文件和轮转日志，并先解析绝对路径确认位于允许子树；不得对未知目录递归删除，不得把“迁移报告中的可删除”当作单阶段删除授权。

提交前必须检查 `git status`、目标目录是否符合本规则、是否产生未跟踪的运行文件，并在文档/脚本中说明受影响的数据根、迁移 manifest、冲突保留和回滚边界。

## UI、i18n 与日志规则

- 1920×1080 下核心字段和终态操作不可遮挡；复杂页面使用 scroll area/splitter，收起后必须能恢复。
- 表格支持横向滚动和手工列宽；数字框/下拉框无焦点时不得被滚轮误改；勾选列使用 Element Plus selection column 和稳定业务 ID。
- 状态同时提供文字与颜色，并覆盖 loading、empty、success、error、cancelled；不能只用颜色表达。
- 用户可见文案优先进入 i18n；设备密码、community、认证密钥和未经脱敏的身份样本不得写普通日志。
- 外部命令输出在来源 Adapter 处按明确编码解码；终端乱码不得触发删除中文或改写原始文件。

## 无 Qt 测试边界

- 测试不得安装或导入 PySide/PyQt/QFluentWidgets，也不得设置 `QT_QPA_PLATFORM` 或恢复 Qt fixture。
- 页面行为由 Vue/Vitest 和 Electron E2E 覆盖；永久 Python 业务规则由无界面 pytest 覆盖。
- 发布门必须反向验证 Backend、安装包、许可证与依赖元数据均不携带 Qt 运行时。

## AP Identity 边界

- AP identity 迁移以 [AP_MODEL_ASSESSMENT.md](AP_MODEL_ASSESSMENT.md) 为基线；现有 `ap_entities` 是内部统一身份基础，不得再新增平行 AP 主表。
- `ap_uuid` 只用于已解析的站点数据库对象；跨模块关联优先规范化 AP MAC。序列号、AC+APID 和 AP 名称只能按来源、站点/AC 作用域和唯一性降级匹配。
- 表内 `id`、AC 原生 `apid/ap_id`、`ap_uuid` 是三种不同语义，接口和测试不得混用。
- AP MAC 与 Radio MAC/BSSID/BBSSID 分层；Peer MAC 是日志观测值，只有带 source/match rule 的 resolver 结果才能说明其对应 AP 或 Radio。
- identity 解析必须返回 matched、unresolved 或 ambiguous；多候选不得静默选第一条，失败不得顺手创建 AP 实体。只有 AC 资源 Repository 写入口可以创建新 `ap_uuid`。
- `site_id` 数据作用域、业务站点 station 和区间 section 分开；section 可以存在而 station 为空。PIS 默认不强制红/蓝网，信号系统按既有规则处理。
- 轨旁业务同时引用 AP identity 与交换机 device_uuid+interface 拓扑 identity；光衰同时引用 AC、AP、接口和在线状态，任何 identity 工具不得承载或改写业务判定。
- MR/Mesh、无线扫描、历史查询、页面展示和导出只能读取统一 identity 结果，写入各自的观测/派生数据，不能回写 AP 主身份。
- AP Identity 基础工具保持纯 Python，不接生产写流程、不改 schema；领域接入必须先做旧/新 shadow comparison 并保留旧生产路径作为回滚。
- 基础工具固定在 `services/ap_identity`，不得导入 PySide6、UI、Repository、Job Center、网络连接或光衰/轨旁业务规则。
- Radio/BSSID resolver 默认只使用 Candidate 显式映射；复用 H3C 派生规则时必须通过后续具名适配器和 shadow comparison，不能在通用 resolver 中隐式推导。
- AC/FIT-AP 统一通过 `services/ac/ac_identity_adapter.py` 只读接入；adapter 只接收普通 row，不导入 Repository/UI/Worker，不写数据库。
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
- 阶段 8 的历史 Qt 宿主方案已终止；任何可见展示必须等待真实局点试运行、脱敏复核，并接入当前统一任务窗口或具名 Vue 页面。所有 flag 默认关闭且 internal-only，不得增加第二套任务持久化或直接绑定原始 result。
- diagnostics disabled/unavailable/failed只影响诊断区域，不得改变原Job/Export终态、成功提示或旧业务结果；全局kill switch关闭展示时不得停止生产任务或删除业务数据。
- 脱敏结构以 `src/netconsole/models/diagnostics_summary.py` 为永久模型，导出适配位于 `src/netconsole/services/export_identity_diagnostics.py`；两者不得依赖 Renderer、Electron、网络或数据库连接，也不得保留原始 result 引用。
- 全局/UI 逻辑开关缺失时视为关闭；samples 开关即使为真也不得暴露明细。历史宿主评审文档仅作设计证据，不构成恢复 Qt Dialog/Manager 的授权。

## 提交前检查

- 新增/修改 Python 文件通过 `python -m py_compile`。
- 对应 pytest 覆盖成功、失败、空数据、取消。
- 搜索 UI 页面是否出现网络连接、Excel 保存、大文件解析和长查询。
- 搜索 Worker 是否导入 UI page。
- 检查生产调用只使用永久 `TaskApplicationService / TaskRuntime / LocalProcessAdapter / ExportJob` 入口，不恢复已删除的 Qt Manager/Helper。
- 说明是否影响数据库结构、导出模板、编码策略、日志和中文显示。
