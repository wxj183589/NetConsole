# NetConsole 项目规则

> 已被仓库根 `AGENTS.md`、`docs/DEVELOPMENT_RULES.md` 和当前架构文档取代。本文件只保留历史阶段规则，不作为当前产品状态事实源。

本文档用于沉淀 NetConsole 的长期项目约定。新增功能、优化现有功能、修复问题或编写自动化任务时，应优先参考本文件，避免每次依赖临时口头提示。

## 适用范围

- 适用于当前 NetConsole 仓库内的代码、文档、测试和打包相关工作。
- 适用于 NetConsole 的本地 Windows 桌面应用形态。
- 适用于轨道交通 PIS / DCS 车地无线 WLAN 子系统相关运维、诊断、数据整理和报表能力。
- 适用于 H3C 设备调试、采集、分析和辅助运维场景。

## 自动复盘范围

NetConsole 的每日/每周自动复盘只服务于项目开发过程，不用于建立通用个人画像。

应复盘和沉淀：

- 项目开发约定
- 代码实现细节
- 业务规则边界
- 目录、命名、文档和测试规范
- 功能开关、导入导出、报表、打包发布等项目内统一规则
- 后续 Codex 开发代码时需要自动遵守的细节

不应复盘和沉淀：

- 用户个人职业、背景或项目外偏好
- 与 NetConsole 无关的自动化建议
- 泛化到其他项目的个人工作习惯
- 未经确认的业务推断

## 总体原则

- 优先解决当前业务目标，不扩展无关功能。
- 优先采用最小、清晰、可验证的实现。
- 改动范围应精准贴合需求，不顺手重构无关模块。
- 新增能力应有明确验证标准，至少覆盖关键业务路径。
- 优先使用项目内虚拟环境 `.venv`；没有可用虚拟环境时，再使用系统环境。
- 仓库提交信息、推送说明和面向用户的变更说明默认使用中文。

## 开发入口和文档边界

- 非简单改动前，先读取 `README.md`、`docs/README.md`、`docs/DEVELOPMENT_CONVENTIONS.md` 和 `docs/CODEX_WORKFLOW.md`。
- 涉及打包发布时，同时读取 `docs/BUILD_AND_RELEASE.md` 和 `docs/THIRD_PARTY_DEPENDENCIES.md`。
- 涉及数据目录、站点隔离或运行时路径时，同时读取 `docs/DATA_LAYOUT.md`，并以 `PathResolver` 和当前代码为准。
- 文档整理任务原则上只修改 `README.md` 和 `docs/`，不要顺手改业务代码。
- 当历史编号文档与当前专题文档或代码冲突时，先标注“当前实现与待统一事项”，不要在文档任务里附带业务迁移。

## 仓库目录和包结构

- 新业务代码不得直接堆到仓库根目录；新增顶层目录前先更新 `docs/development/repository-layout.md` 并说明唯一职责。
- Desktop、Web、Agent 分别放入 `apps/desktop`、`apps/web`、`apps/agent`；共享 Python 业务代码放入 `src/netconsole`，导入名仍是 `netconsole`。
- 配置模板和 feature profiles 放入 `config/`；构建、开发和维护脚本分别放入 `scripts/build`、`scripts/dev`、`scripts/maintenance`。
- 开发运行数据写入 `.local/`；打包态优先使用 `%LOCALAPPDATA%\NetConsole\`，不得依赖当前工作目录或把运行数据写回源码树。
- 路径定位优先使用 `PathResolver`、资源 helper 或脚本自身位置；禁止用 `Path.cwd()` 或临时 `sys.path` 掩盖包结构问题。
- 移动目录后必须同步检查 Python import、pytest 配置、构建脚本、批处理、前端工作目录、Agent 入口、README/docs 链接和资源定位。

## 中文和编码规则

- 源码、Markdown、JSON、TOML、YAML、CSV 和日志导出默认按 UTF-8 处理。
- Python 读写文本必须显式指定 `encoding`；JSON 写入中文时使用 `ensure_ascii=False`。
- Windows / PowerShell 下涉及中文、路径、日志、H3C 回显、MIB、CSV 或 XLSX 时，先初始化 UTF-8 终端编码。
- 不用 PowerShell / Codex 终端中的乱码显示直接判断文件损坏；必要时检查原始字节和实际读取编码。
- 读取 H3C 设备回显、历史日志、MIB 文件和外部 CSV 时，优先尝试 `utf-8-sig` / `utf-8`，失败后尝试 `gb18030` / `gbk`。
- 优先复用 `src/netconsole/utils/text_encoding.py` 中的统一读取和清洗函数，不在各模块散写编码兜底循环。
- 不删除中文描述、MIB 中文字段或 UI 中文文案来规避解码问题。

## 新功能和优化规则

### 用户可见功能必须接入功能开关

新增用户可见模块、页面、标签页、动作、按钮或入口时，默认接入集中式功能开关系统。

要求：

- 在 `src/netconsole/core/feature_registry.py` 注册新的 feature ID。
- 通过现有功能开关配置页面和 profile 流程暴露配置项。
- 使用 `FeatureGate` 控制 UI 创建、入口显示或动作处理。
- 避免在页面内散落一次性的 `if` 判断。
- 功能状态统一使用 `visible`、`enabled`、`client_package`、`internal_only` 四个布尔字段。
- 客户版有效状态必须沿父级级联；父级隐藏、内部功能或未进入客户包时，子功能也不能显示或启用。
- `module.feature_switch` 和 `system.feature_flags` 是受保护内部功能，客户模式不能通过本地 override 打开。

例外：

- 纯内部重构、非用户可见修复、测试辅助代码可以不新增 feature ID。
- 若需求明确要求永久基础能力，可在说明中写清楚不接入开关的原因。

### Fluent 命令栏和页面动作边界

Fluent 主窗口中的模块级动作应通过 `NCCommandBar` 统一承载，并转发到原始页面按钮或处理函数。

要求：

- 命令栏按钮必须有中文文本和图标，避免只保留旧页面隐藏按钮。
- 模块级命令栏只放跨页面主动作；标签页内、表格内、文件列表内的上下文动作保留在原页面局部。
- 文件管理模块级命令栏只保留连接类动作：连接、断开、刷新连接状态、打开 WinSCP。
- 配置采集中心模块级命令栏只保留保存配置、下载配置、配置对比、打开目录、刷新；快照、差异导出、删除等动作保留在局部面板。
- AC 管理、轨道交通等多标签模块不得把标签页专属动作混入全局命令栏。

验证时应检查命令栏文本、图标、旧按钮隐藏状态，以及点击命令栏按钮是否触发原始页面真实逻辑。

### WPS 相关范围边界

默认不新增、修复或保留以下在线文档能力，除非需求明确要求：

- WPS 云服务
- WPS API
- KDocs
- 在线表格同步
- 在线文档同步

仍然在范围内的能力：

- 本地 `.xlsx` 导出
- 便于 WPS Office 或 Microsoft Office 打开的格式优化
- 表头冻结、筛选、列宽、自适应、文本格式、工作表命名等本地 Excel 体验优化

判断原则：

- 如果用户只说“WPS 打开效果”“WPS 兼容”，默认理解为本地 `.xlsx` 文件体验。
- 不要自动扩展成云文档、在线协作或 API 集成。

### 车内通信和点表规则

车内通信检测、车载网络诊断和点表生成应优先采用统一规范化规则。

要求：

- 不为了兼容历史不一致结果而新增生产迁移逻辑，除非需求明确要求。
- 点表生成和全局规则应用时，不保留旧的 `remark` 描述。
- `remark` 应从当前节点身份、节点类型、端别和规则重新生成。
- 多列车之间应尽量保持一致的描述规则。

判断原则：

- 如果旧数据和新规则冲突，默认以当前统一规则为准。
- 如果需要保留历史输出，必须在需求或提交说明中明确这是兼容性需求。

### 本地优先

NetConsole 是本地 Windows 桌面工具。默认优先本地数据、本地文件和本地运行时。

要求：

- 不引入云同步、在线账号、远程文档服务作为默认依赖。
- 项目数据默认保存在项目或发布包可控目录下。
- 导出、导入、分析、诊断优先围绕本地文件和现场设备连接。

### UI 线程和后台任务全局规则

NetConsole 全局强制遵守 [UI 线程全局规范](ui_thread_policy.md)、[后台任务规范](background_task_policy.md) 和 [导出进程规范](export_process_policy.md)。

要求：

- UI 线程只负责创建控件、响应点击、启动任务、接收信号、显示进度、结果和错误。
- 耗时任务、网络任务、数据库大查询、文件扫描、解析、压缩、图表生成、设备连接必须使用后台线程或独立进程。
- 所有导出类任务必须使用独立进程；按钮回调不得直接执行 `Workbook.save()`、`df.to_excel()`、`matplotlib.savefig()` 等重型导出逻辑。
- Worker 不得访问 QWidget、QTableWidget、QLabel、QPushButton、FigureCanvas 或 QFluentWidgets 控件。
- UI 线程、Worker 线程、导出进程必须各自创建 SQLite 连接，不得跨线程或跨进程共享连接。
- 大表必须分页、分批或懒加载，不得在 UI 线程一次性加载和渲染全量数据。

验证时应说明是否遵守 UI 线程只做 UI、是否使用 QThread/Worker 或独立进程、是否有进度/取消/失败提示/日志。

### AP 扩展归属导入规则

FIT-AP 扩展信息、轨旁 AP 布点表和信号 A/B 网布点表统一沉淀到 AP 扩展归属字段。

要求：

- 标准模板和导出模板应保留 `归属类型`、`归属站点`、`归属区间`、`区间起点站`、`区间终点站`、`场段`、`区域` 等字段。
- `归属类型` 使用统一枚举语义：站点、区间、场段、未知；可由站点、区间、场段、区域信息推断。
- 智能导入信号 A/B 网布点表时，工作表名 `A网` / `B网` 决定网络域；相邻标题推断区间起终点，车辆段/停车场标题推断场段和区域。
- 旧版只包含 `AP名称`、`归属站点`、`里程`、`点位说明`、`上下行` 的元数据匹配模板不再作为有效导入模板；需要走当前扩展信息模板。
- AP MAC 匹配仍以规范化 MAC 为主；无在线资源但有扩展点位时按扩展未上线类状态处理。

验证时应覆盖 A/B 网识别、区间/场段推断、标准模板表头、旧模板拒绝和资源匹配结果。

### AP Identity 只读接入边界

AP Identity 当前只允许作为 shadow/diagnostics 观测能力，不接管生产匹配、页面展示或业务结论。

要求：

- resolver、adapter、shadow 和 diagnostics 不得回写 AP 主身份、业务数据库、Repository 结果、导出 workbook 或页面字段。
- `identity_shadow`、`detail_identity_shadow`、`export_identity_diagnostics` 只能作为附加诊断 metadata；unavailable、failed、unresolved 或 ambiguous 不得改变原 Job/Export 终态和成功提示。
- `identity_changed` 只表示旧/新结果或候选差异，用于阻断未来接管评估，不授权覆盖旧生产 key。
- 可见 UI 必须默认关闭、internal-only、只消费脱敏聚合 ViewModel；没有统一 Job 详情宿主前，不得为了展示改多个业务页面或保存完整 result。
- 未经真实局点观测、独立评审和用户明确批准，不得让 AP Identity resolver 接管生产匹配。

验证时应覆盖旧业务字段不变、异常只降级诊断、导出/页面契约不变，以及敏感明细不进入展示或日志。

### 车载 MR 在线采集和分析规则

车载 MR 在线采集、原始日志、实时缓存、解析缓存和图表时间轴必须保持可追溯。

要求：

- 原始采集任务日志写入各自任务 raw 文件，不默认镜像到 `collector_output_raw.log`。
- `collector_output_raw.log` 只记录采集器过程日志；`terminal_monitor_raw.log` 只记录设备终端监控回显，二者不得混写。
- repeat 采集连接只执行必要的流式采集准备命令，不重复执行完整初始化命令；停止状态下不得再启动新的 repeat 连接。
- 在线 MR 解析 RX 流时，应按已识别命令切分采样块，并以主采样命令时间作为样本时间。
- 解析缓存发现 mesh-link 样本塌缩、主链路 MAC 拼接异常或时间轴异常时，应判定为 stale 并重新解析。
- fping 原始采样必须保留本地时间；当可从 `display clock` 计算设备时间偏移时，同时写入设备对齐时间，并优先按设备秒桶生成 1 秒汇总。
- 无设备时间偏移时，fping 汇总回退到本地秒桶，并明确保留 `offset_source=none`。
- 主链路切换实时日志只来自 `terminal_monitor_raw.log`；`switch_history` 文件不得反向填充 active-link switch 实时事件。
- 动态图表增加 hover/参考线时，不得改变原始坐标轴范围。

### MR 原始 MESH 大数据规则

MR 原始 MESH 日志可能是大文件或多文件导入，解析、图表和报告必须优先考虑可追溯和性能。

要求：

- 源文件目录型 `mesh.sqlite` 只作为目录和入口时，明细解析库以 `source_files.parsed_db_path` 指向的单文件 parsed SQLite 为准。
- 图表、详情和报告按源文件过滤时，必须解析到对应明细库，不能假定目录库包含全部 `mesh_links` 明细。
- compact v2 解析库的 RSSI、信道繁忙度、速率、重传和错误计数等指标优先使用标量列；兼容旧库时才回退到 `metrics_json` / `deltas_json`。
- 大样本图表只绘制可见窗口或下采样结果，并保留切换点、锚点等关键样本；不要一次性绘制全部采样点。
- 页面切换、MR 选择和表格刷新应使用防抖、懒加载和 repository 缓存，避免同一 MR 被重复加载。

验证时应覆盖单文件 parsed DB 查询、compact v2 标量指标、源文件过滤图表/报告、可见窗口绘制、全量视图下采样和重复加载防抖。

### IPERF 随采集打流规则

车载 MR 随采集 IPERF 打流默认跟随采集生命周期，不使用短时固定测试作为正式采集时长。

要求：

- 在线 MR 预设默认端口为 `5201`。
- 随采集模式使用 `FOLLOW_COLLECTION_PROTECTION_DURATION_SECONDS`，当前保护时长为 `86400` 秒。
- 开始采集和重连前执行 1 秒 preflight，preflight 不启用 `follow_collection`。
- TCP 低带宽场景缺省 block size 时使用现有 `16K` 兜底。
- IPERF 日志需记录 `duration_mode=follow_collection` 和保护时长，便于后续分析解释。

### Web / Agent / Traffic 阶段边界

NetConsole Web 演进采用渐进式接入，不重建第二套 Python Core，也不把业务执行下放到浏览器或路由层。

要求：

- Qt 主程序仍是正式生产入口；Server Mode、Web Shell、任务中心和 Agent 管理控制面不得描述为已完成的可交付服务版。
- Agent 配置与运行状态写入每局点 `agents.db`；Token 只保存在 Controller 进程内的会话凭据中，不进入 JobSpec、SQLite、事件、日志、命令行或 DTO。
- Agent 能力判断只使用 Runtime Snapshot 和 capability，不按操作系统名称猜测；浏览器不直接访问 Agent。
- 统一 Traffic 业务只能通过 `TrafficTestApplicationService` 启动、停止和恢复；本地/Agent 执行差异留在 Adapter 层。
- Traffic Run、Agent mapping 和独立 Ping 样本写入 `traffic_runs.sqlite`；iPerf interval 继续以既有 `iperf_results.sqlite` 为事实源，不复制到 Traffic 库。
- 阶段 4C 只能在现有应用服务上增加受控 Traffic REST API、独立 WebSocket 和 Vue 页面；不得新增任意 Shell/命令执行接口，不得把高频样本塞入全局 `/ws/tasks`。
- SNMP Center、通用 MIB/OID 平台和无线勘测已在后续阶段删除；设备管理 SNMP v1/v2c 与网络工具无线扫描是独立保留能力。

验证时应覆盖 Token 不落库、Agent/Controller Task ID 独立、远端同步状态不伪造 Task 终态、阶段限制与 docs 状态一致。

### 数据路径和局点隔离

业务数据路径应通过 `PathResolver` 或既有路径服务获取。

要求：

- 不在正式代码、测试或文档规则中写死用户本机路径。
- 局点数据必须隔离，设备、报表、采集记录和缓存不能跨局点混用。
- 原始采集日志、解析结果、报表输出和备份文件应分区保存，不混放在同一目录。
- 文档任务不得直接修改目录逻辑；目录结构变更应先更新实现、迁移策略和测试。

### UI 表格规则

新增或修改表格类页面时，遵守 `docs/ui_table_guidelines.md`。

要求：

- 批量选择列必须使用 `CheckBoxOnlyDelegate`，不使用 `setCellWidget(QCheckBox)`。
- 全选、反选、清空选择必须同步表格 `CheckStateRole` 和内部选择状态。
- 表格列宽按内容初始化，允许用户拖动；不默认使用 `QHeaderView.Stretch` 强行压缩所有列。
- 超宽表格使用横向滚动条；路径、错误、备注、命令输出等长文本应有省略和 tooltip。

### 构建和发布边界

打包发布以 `docs/BUILD_AND_RELEASE.md` 和 `scripts/build/` 下构建脚本为准。

要求：

- 发布输出必须进入 `dist/` 下的版本目录，不污染项目根目录。
- 发布包只允许白名单内容进入：`NetConsole.exe`、`_internal`、`data`、`runtime`、`tools`。
- `docs/`、`tests/`、`scripts/` 和源码形式的 `src/netconsole/` 不得进入用户发布包。
- 内部版和客户版通过既有 `--build-editions` 与 feature profile 机制处理，不临时复制两套代码。
- 打包前检查 `fping`、`iperf3` 等外部工具源文件；运行时工具路径不得写死用户本机路径。
- 非交互构建跳过 smoke test 时必须说明原因。

### 第三方依赖边界

- QFluentWidgets 只使用 `PySide6-Fluent-Widgets==1.11.2` 对应的 `qfluentwidgets`。
- 不混装 `PyQt-Fluent-Widgets`、`PyQt6-Fluent-Widgets` 或 `PySide2-Fluent-Widgets`。
- 不使用 QFluentWidgets Pro 组件；商业用途需要另行确认授权。
- Mica / Acrylic / 毛玻璃效果必须可降级；特效初始化失败不能阻断主程序启动。

## 验证规则

根据改动风险选择验证范围：

- 文档改动：检查路径、文件名、关键内容是否准确。
- 纯逻辑改动：优先补充或运行对应 pytest。
- UI 入口或功能开关改动：验证入口显示、隐藏、启用、禁用状态。
- Excel / 报表导出改动：验证本地文件可生成，并检查表头、列宽、筛选、冻结、格式。
- 车内通信、车载 MR、轨旁 AP、MESH、IPERF 等业务改动：验证核心解析、关键状态和异常分支。

## 不应沉淀为项目规则的内容

- 一次性临时要求。
- 未经确认的用户偏好推断。
- 与 NetConsole 无关的通用个人偏好。
- 只对某次实验有效的兼容代码。

## 后续维护

- 当用户明确确认新的长期项目偏好时，应更新本文档。
- 当代码实现和本文档冲突时，应优先确认是文档过期还是代码偏离规则。
- 新增规则应短、准、可执行，并尽量包含判断边界。
