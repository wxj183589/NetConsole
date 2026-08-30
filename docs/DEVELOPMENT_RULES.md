# NetConsole 开发规则

本文是新增功能和维护存量代码的强制检查表。

## 先判断任务类型

开发前先回答：

1. 是否访问网络、设备、外部命令、数据库、磁盘或大文件？
2. 是否可能执行超过 300ms？
3. 是否包含大循环、批量操作、解析、压缩、图表或报告生成？
4. 用户是否需要进度、取消、日志和失败原因？

超过 300ms 的 IO、CPU 或网络任务不得在 UI 线程执行。重 CPU、重 IO、重网络和批量任务进入 Worker Process；所有导出进入独立 Export Process。

## 共享层稳定窗口与风险分级

Electron-only 架构收口后的下一至两个开发周期是共享基础设施稳定窗口。业务 Bug 和必要兼容修复可以继续；`api/client`、`NcDataTable`、Task/Job、Export、AP Identity、Feature Registry、Path/DataRoot、Electron runtime 和构建发布原则上不做并行的大范围重构。稳定窗口结束必须以新的 `main` 基线通过为证据，不能只按日期宣布结束。

同一时间最多进行一个 L3/L4 共享基础设施重构。业务功能可以并行，但不得借业务需求顺手重写共享层；确需触碰共享层时将它计入当前唯一基础设施改动，并由集成负责人确认消费者和合并顺序。

改动风险按以下最低等级管理：

- `L1`：单页面 CSS、文案、局部只读展示或纯文档；
- `L2`：单一领域 Application Service、Repository、Parser 或页面行为；
- `L3`：共享组件、Renderer API 基础、Task/Job、Export、AP Identity；
- `L4`：Feature Registry、DataRoot、数据库迁移、Electron runtime、CI、构建发布。

机器可读范围与消费者套件以 [`config/architecture/change_impact_matrix.json`](../config/architecture/change_impact_matrix.json) 为准，执行入口为 `python -m scripts.quality.check_change_impact`。路径审计只能上调最低风险，不能替代语义审阅；跨领域、兼容协议或持久化行为变化必须人工上调。L3/L4 必须执行 [Consumer Matrix](./development/CHANGE_IMPACT_FRAMEWORK.md#consumer-matrix)，并在合并到 `main` 后对最终提交复验。

## 分支与 Worktree 生命周期

- 普通分支目标寿命为当天，最长原则上 1～2 天；超过期限或基线明显漂移时，从最新 `main` 创建新 worktree/分支并只迁移本任务提交。
- 不反复 merge `main` 到业务分支，不在业务分支解决与本任务无关的冲突，也不把其他线程的工作树改动带入本任务提交。
- 开始 L3/L4 前检查高风险文件的并行所有权；有并行修改时由集成负责人决定串行、拆分或停止，无法确认时明确标记 `UNKNOWN`。
- 合并顺序由依赖关系和风险决定，不以“谁先完成”替代集成审计。分支绿不等于 `main` 绿；合并后回归失败必须用独立修复任务恢复基线。

## 下一阶段 UI 与分层边界

- 当前产品形态是 Python Core + FastAPI 永久业务层、Vue 唯一主界面和 Electron 桌面外壳；Qt 源码、运行时和入口已删除，历史行为只通过 Git 与冻结迁移矩阵追溯。
- 不新增 Qt 业务页面或 Qt 专用业务逻辑。新功能默认沿共享规则/Application Service -> FastAPI -> Vue 建设。
- Vue 与 Electron 只负责表现和受控本机能力；FastAPI Router 只负责 DTO、鉴权、调用 Application Service 和响应映射。
- Vue、Electron 和 Router 均不得直接操作 Repository、SQLite、设备命令、SSH/SNMP 或业务文件。
- Electron 安全基础已进入实现期；只允许 `apps/desktop_electron` 中的窗口、Python 生命周期和白名单 Bridge，不得新增第二套 Renderer/业务 Core。路径只能使用当前原生对话框授予的临时能力，禁止任意命令、程序或未授权路径。
- SNMP Center、通用 MIB/OID 平台与无线勘测已删除，不得恢复代码、资源、依赖或入口；网络工具无线扫描是独立保留能力。

总体分层与不可回退边界见[当前架构](./ARCHITECTURE.md)。仓库布局、数据安全、测试和提交规则以根 `AGENTS.md`、本文及机器可读 Change Impact Matrix 为准。

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

- 永久交互契约见 [用户文件导入导出交互契约](./export/USER_FILE_INTERACTION.md)。
- 导出必须区分两层路径：Python Export Process 的内部 Artifact 路径，以及 Electron Main 当次授权的用户最终保存路径。
- 用户最终路径不进入 Python `ExportJob` 或业务数据库；`ExportJob.output_path` 只表示 Worker 的内部 Artifact 输出位置。
- Worker 只负责生成内部 Artifact，并保留临时文件、JSONL、取消和原子替换规则；Renderer 的共享协调器负责当前 session 中任务与授权路径的绑定。
- Electron Main 负责按 Artifact 元数据流式复制、大小与 SHA-256 校验及安全替换。只有 Main 返回 `saved` 才能提示已保存。
- 新任务型导出必须先在 `exportActionRegistry.ts` 登记固定动作，通过 `submitExportAfterDestinationSelected(...)` 先选路径再创建任务；取消不得创建任务。
- 现成文件和历史 Artifact 只在用户点击时调用 `downloadBackendResource(...)` 另存，不得在页面或任务恢复时自动弹窗。
- 页面不得自行维护 destinationPath、session storage、Artifact 轮询、自动保存或失败重试状态机。
- 取消、失败和进程异常必须清理临时文件、Job 文件和取消文件。
- Excel 列宽按表头和采样内容自适应，长字段有上限，保留横向滚动/查看能力。
- XLSX 保持 WPS/Excel 兼容、冻结表头、筛选、文本格式和中文字段。
- 目标文件被 WPS/Excel 占用时提供明确关闭文件后重试提示。

## 导入统一规则

- Browser `File/FileList` 导入只能由用户点击触发；取消不调用 prepare/preview/import API，处理后清空 `input.value`，保证同名文件可再次选择。
- `multiple` / `webkitdirectory` 只处理用户实际选择的 FileList，不扫描默认目录或上次目录。
- Electron 路径导入必须复用 `selectFile`、`selectDirectory`、`selectSitePackage` 等现有专用选择器，只使用 Main 返回的当次授权路径，不接受 Renderer 任意文本路径。
- 选择器 filter/accept 仅改善交互，不能替代 Backend 对扩展名、文件头、契约、schema、必要字段/Sheet/manifest、非空、重复内容和 ZIP 路径穿越的校验。
- OmniPeek、局点包、SFTP 受管下载等例外以永久交互契约登记为准；新增例外必须同步静态审计。

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
- 源码树只保存源码、版本化配置、资源、测试样本、文档和维护脚本；数据库、原始回显、抓包、采集会话、报告、缓存、安装包和构建产物不得写回源码目录。测试必须使用显式 `RuntimeMode.TEST` 与 `D:\study\NetConsole-Workspace\test-data\NetConsole\<run-id>`。
- 迁移必须在所有相关进程退出后执行 dry-run；发布前用 SHA-256 和 SQLite `quick_check/integrity_check` 复核，目标已有不同内容时写入 `migrations/conflicts/`，不得覆盖目标。每次 apply 都生成 manifest，源目录在核验和留存策略确定前不得删除。
- 清理只能处理已白名单的缓存、临时文件和轮转日志，并先解析绝对路径确认位于允许子树；不得对未知目录递归删除，不得把“迁移报告中的可删除”当作单阶段删除授权。

提交前必须检查 `git status`、目标目录是否符合本规则、是否产生未跟踪的运行文件，并在文档/脚本中说明受影响的数据根、迁移 manifest、冲突保留和回滚边界。

## 历史残留与 WIP 审计

审计 stash、WIP 标签、snapshot refs 或 unmatched patch 时，目标是判断当前价值，不是把历史内容恢复到 `main`。每一项历史改动必须根据当前主线、现行架构和可重复验收条件归类为：

- `建议移植`：当前需求仍存在，主线确实缺少能力，旧实现无安全风险、符合现行分层和数据目录规则，且移植收益高于重新实现。
- `已被主线替代`：主线已有等价或更完善实现；记录替代代码路径和依据，不重复合入。
- `建议弃用`：依赖旧目录、旧架构、旧 UI、旧数据模型、绝对路径、敏感配置或已删除接口，或无法说明业务目的和可靠验收标准。
- `等待人工确认`：价值、需求或唯一性证据不足；暂不合入，也不得阻塞主线。

仅有历史代码、没有当前入口、已被新方案覆盖、会重新引入架构债务、包含本地环境假设或与产品规划冲突的内容，默认建议弃用。标记为建议移植的内容只能按功能最小范围手工移植，并补充定向测试、文档和回滚边界；禁止整体恢复旧提交或 stash。确认不含唯一有效代码、必要文档或尚未迁移的数据结构后，建议弃用项才可进入引用清理候选；凭据轮换和引用清理必须分开执行。

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

- [AP Identity](./AP_IDENTITY.md) 是模型、索引、解析优先级、消费者状态、诊断、真实局点观测、导出与回滚的唯一活动 SSOT；不得从历史 Assessment 恢复过期阶段结论。
- `ap_uuid`、表内 `id`、AC 原生 `apid/ap_id`、AP MAC、Radio MAC、BSSID/BBSSID 和 Peer MAC 是不同语义。Peer MAC 是日志观测；站点、区间和里程是位置证据；交换机 `device_uuid + interface` 是拓扑身份，均不得直接折叠为物理 AP 身份。
- Resolver 必须返回 `matched`、`unresolved` 或 `ambiguous` 并保留来源、规则、confidence 与 revision；多候选不得静默选第一条，失败不得创建 AP 实体。只有现有来源写入流程可以创建或刷新主身份。
- 普通 GET、页面刷新、历史查询和导出只读统一索引，不连接设备、不重建索引、不回写来源主数据。索引只在明确来源写事件或受控启动修复后刷新。
- MESH、Ground、Online/Vehicle MR、Wireless 与轨旁 AP 已接管的消费者必须保留原始观测和统一身份投影；未接管消费者保留显式白名单，不得复制新的私有 MAC 索引或推导规则。
- Identity 工具不承载采集、主备链、光衰、拓扑、RSSI、Channel Busy、页面或报告业务规则。Adapter/shadow/diagnostics 失败必须表达为 unavailable/warning，不得改变 Job、Export、加载或写入终态。
- 新生产消费者接管前必须执行 L3 Consumer Audit、旧/新对照、批量 revision 固定、真实局点脱敏观测和单模块回滚验证；部分消费者接管不等于全系统接管。
- 真实局点观测只保存聚合指标；完整 result/items/evidence、raw log、数据库和 xlsx 不得进入仓库，MAC/IP/名称/路径必须使用 campaign HMAC 或不可逆 token。展示层使用严格允许列表，未知字段和明文样本丢弃，开关缺失视为关闭。
- Identity diagnostics 不得成为字段删除、SQL 修改或报告语义变化的依据。导出 golden 比较 Sheet、表头、关键行值、筛选、冻结窗格、样式和列宽，不依赖不稳定的 XLSX 二进制哈希；诊断失败时原导出继续按既有契约完成。
- 诊断模型与导出适配不得依赖 Renderer、Electron、网络或数据库连接，也不得保留原始 result 引用。任何可见诊断只能接入当前 Job Center 或具名 Vue 页面，禁止恢复 Qt 宿主或第二套任务持久化。

## 提交前检查

- 新增/修改 Python 文件通过 `python -m py_compile`。
- 对应 pytest 覆盖成功、失败、空数据、取消。
- 搜索 UI 页面是否出现网络连接、Excel 保存、大文件解析和长查询。
- 搜索 Worker 是否导入 UI page。
- 检查生产调用只使用永久 `TaskApplicationService / TaskRuntime / LocalProcessAdapter / ExportJob` 入口，不恢复已删除的 Qt Manager/Helper。
- 说明是否影响数据库结构、导出模板、编码策略、日志和中文显示。
