# NetConsole 更新日志

## v1.4.2 - 2026-07-24

### 工作区与桌面常驻

- 新增浏览器式工作区：主窗口与独立工作区窗口都支持标签打开、切换、关闭、固定、复制及“在新窗口打开”；设备详情与带稳定会话 ID 的 MESH 页面按资源身份隔离，普通导航复用已有标签。
- 新增受控窗口布局和标签恢复。恢复数据仅保存规范化内部路由、窗口布局和标签元数据；敏感 query、Token、密码、确认令牌和本机绝对路径会被过滤，损坏布局或多显示器越界安全降级。
- Windows 启动后创建通知区域图标。默认关闭主窗口只隐藏到托盘，Python Backend 和正在运行的业务任务继续运行；托盘菜单可恢复主窗口、新建工作区、打开任务中心，并显示 Backend 与当前局点状态。
- 系统设置新增“关闭主窗口后继续驻留通知区域”开关，托盘菜单与所有窗口同步。只有“退出 NetConsole”执行完整受控退出；托盘不可用时关闭主窗口不隐藏，避免留下无法恢复的后台进程。

### 界面与局点

- 主窗口顶部新增全局“当前局点”入口，直接读取现有局点 Registry 的真实显示名称；首次加载、未选择和读取失败均有明确状态，长名称自动省略并保留完整提示。
- 点击当前局点可进入现有“系统设置 → 局点与数据管理”并自动定位、短暂高亮目标区域；Backend 重启或局点切换期间清除旧名称，恢复后重新读取真实当前局点，不新增局点状态或切换机制。
- 局点数据包扩展为完整迁移包、现场采集包和采集回传包；跨电脑增量同步使用稳定局点 UUID、现场基准、文件 SHA-256 和来源电脑 ID 校验同一局点，不以局点名称或本地自增 ID 猜测关联。
- 采集回传包导入先预检文件、任务和数据库记录，冲突由用户逐项选择本机或回传值；文件按哈希追加，任务按稳定任务/事件 ID 合并，设备、FIT-AP 和 AP 记录仅在具有稳定 UUID 时执行三方字段合并。
- 合并前自动创建数据库恢复快照，失败时恢复主库；删除请求只进入审计而不自动执行，旧基础资料等缺少稳定身份的记录保持本机数据并列为未支持项。
- 正式 Electron 包改为固定生产功能集：不再显示或请求功能配置，包内基线缺失/损坏时回退稳定 Registry 默认；系统设置、局点管理、任务中心和日志不再受 customer profile、本地 override 或 `client_package` 误关影响。
- 正式生产基线补齐设备写入/采集/导入导出、设备与文件桌面动作、SFTP 浏览下载、列车在线、Online MR 分析、MESH 导入/报告和轨交任务控制；构建与 Electron package smoke 会拒绝缺少必要生产能力的包，internal/development 项仍保持关闭。
- 普通局点包新增非秘密凭据重录状态：导出继续清空密码、SNMP community 和隧道密码，导入后设备明确显示 `needs_reentry`，连接任务在创建前阻断；当前电脑重新保存凭据后恢复可用。本次不引入凭据加密，也不改变现有本机凭据存储格式。
- 修复 Worker UTF-8 JSONL 在汉字多字节中间分块时被 `errors="replace"` 提前破坏的问题；stdout/stderr 使用增量解码，新任务消息、progress、log 和 finished 保持 Unicode，旧历史中的 U+FFFD 只提示不可恢复而不猜测改写。
- 系统设置新增正式包环境自检，覆盖 Backend/构建标识/生产 Feature policy/局点/数据根/任务库/设备库/凭据状态/fping/iPerf3/Electron Bridge，并用真实 REST 与任务 WebSocket 中文探针验证端到端 Unicode。
- 局点切换改为先核对真实任务宿主：终态历史、死 PID 和无宿主残留任务不再永久阻塞；真实活动任务返回名称、状态和 ID，并可从设置页直接打开任务中心。Backend health ready 后先完成 IPC 再刷新 Renderer，重启失败会恢复原局点并解除按钮 loading。

### 轨道交通基础资料

- 修通桌面端线路站点模板下载白名单和真实文件保存链路；模板升级为线路参数、线路节点、区间配置、字段说明四个工作表，兼容旧三表模板，导入预览只进入当前草稿，正式导出明确排除未保存修改。
- 站点新增多选轨道设施、中心里程和端点延伸字段；MAIN 新普通站默认地下/岛式但不覆盖已有明确结构，旧 `turnback_type` 继续兼容映射并保存在原 `raw_payload_json` 边界内。
- 新增基于当前草稿的双向区间生成预览，使用稳定节点身份和 `generation_key`，下行名称保持物理低序站对而起终节点反向；MAIN 两端使用不同端点身份生成四个延伸方向，支持逐项取消。
- 自动生成只更新匹配的自动区间，人工区间受保护，过期区间默认保留；AP 数量和里程范围继续按轨旁 AP 正式归属实时统计，模板导入值被忽略。
- 自动区间在基础资料解锁后允许编辑，并按字段记录人工调整；再次生成时保留人工值，支持在草稿内恢复自动建议值。端点延伸区间按线路低序端/高序端固定物理节点顺序，正式字段只保存“端点”，下拉辅助说明不再写入数据库。
- 区间改名继续在同一事务内级联轨旁 AP 引用；除精确起止节点和线路侧更新外，同名 AP 的区间名称也会同步，避免另一线路侧残留旧名称。
- 区间新增独立物理里程范围，按站台中心里程和端点规则为上下行生成相同的 `0–152 m`、`152–1801 m` 或 `45574+ m`；开放终点不伪造数值，缺失/重复/反向里程进入生成预览提示。物理范围与 AP 实际里程统计分离，支持草稿人工覆盖、恢复自动值、metadata 持久化及新旧模板兼容往返。
- 明确车载 MR 的固定物理语义：`MR-CT` 固定为 `CT / 1车厢端`，`MR-CW` 固定为 `CW / 6车厢端`；基础资料新增 `mr_position_code`、`physical_end`、`car_number` 和站序递增方向头端基准 `increasing_direction_leading_end`。
- 新增独立运行端位计算模型，按实际站序方向、编组方向基准和 MR 物理端位计算“行驶方向头端 / 行驶方向尾端”；折返过渡期间暂不判定，RSSI 信号模型不用于静默交换 CT/CW。
- 当前版本先完成数据模型、基础资料展示和计算规则；完整行程重建、折返识别、双端联合分析及配置/信号冲突告警仍未接入。

### MR/Mesh 图表

- 修复轨旁信号图在降采样连续折线上错误显示“当前时刻无有效采样”的问题：前端缓存一次性建立真实曲线覆盖区间，指针仅在连续线段内吸附到最近的已返回真实帧；遇到断线、空 RSSI、run 切换或范围外时隐藏提示，不跨缺口、不插值、不伪造采样时间。
- 轨旁 Tooltip 改为独立 Vue 浮层并按图表实际可用高度展示，ACTIVE/STANDBY、AP/Radio、轨旁/MR RSSI、站点/区间和主链持续时间保持完整排版；上方全部 ACTIVE 主链路 Tooltip 保持原业务格式。
- 新增“固定查看”轨旁链路详情面板，冻结当前真实 frame 的全部主备链路，支持独立滚动、范围外提示、AP 选择和 Esc 优先关闭；移动指针、缩放和切换对比/专注布局不会改变固定内容，也不会触发图表重建或重新请求。
- 优化大规模轨旁序列颜色：同帧、相邻帧、run 重叠和短间隔冲突序列使用稳定冲突感知配色，曲线、Tooltip、当前范围 AP 和固定详情共用同一颜色表。
- MR 原始 MESH 日志分析页启用单实例受控路由缓存：离开页面仅暂停轮询、Observer 和图表交互，返回后恢复原会话、Tab、时间轴、AP 选择、固定详情与滚动位置，并只对可见图表执行 resize；已加载的主链图、轨旁图和 series cache 不再重复请求、重建或释放。
- 主窗口新增浏览器式已打开页面标签栏，Dashboard 固定且不可关闭，普通业务页支持关闭当前、其他、右侧和全部可关闭标签；MESH 标签离开后持续可见，点击直接恢复同一缓存实例，只有关闭标签才释放图表、轮询、Observer 和轨旁 series cache。

### 车载 MR 收集分析

- 会话选择、刷新、重新解析、打开本地目录、生成 XLSX、任务窗口和删除统一收敛到页面顶部；会话表格与选择器同步当前行，底部重复报告卡片已移除，业务表按窗口剩余高度展示。
- 新增 Electron 专用会话位置动作：Renderer 只提交稳定 `session_id`，Main 通过受管回环后端解析正式包、raw、会话目录或关联报告，不向 Renderer 暴露路径，也不接受任意路径、URL 或命令。
- 新增后台会话删除任务，与解析、报告共享会话资源锁；删除前二次确认并拒绝活动会话，目录先原子隔离、数据库事务失败时自动恢复，后续文件清理失败返回部分成功，不删除 Agent 远端包、外部导入源或其他会话。

### 稳定性与性能

- 轨旁指针更新、Tooltip 和固定详情的打开、滚动、关闭不调用 ECharts `setOption/clear/resize/dispose`，不重建 series cache、不改变共享 viewport；真实 Electron Canvas 画像中无清空像素、Renderer/GPU/Utility 子进程退出或持续 Heap 增长。
- Windows 正式目录包固定生成 `NetConsole.exe`，package smoke 直接读取 Electron Builder 的 `build.win.executableName`，配置缺失时立即失败，避免产品显示名与正式 EXE 名称再次漂移。
- PyInstaller `NetConsoleBackend.exe` 明确保持为 Electron 受管后端；冻结环境无参数运行时记录日志、显示原生提示并返回非零状态，不再误入源码 Electron 开发链。品牌 ICO 同步补齐 256px 层，目录包 smoke 与 NSIS 安装包构建已通过。
- 软件版本升级到 `v1.4.2`，同步 Electron 打包版本、窗口标题、Web Shell、发布文档和内置更新日志。

## v1.4.1 - 2026-07-22

### 设备文件

- 设备文件页改为分阶段加载，设备列表和最近 20 条下载任务不再阻塞首屏；临时文件递归清理移到宿主启动后的后台线程，下载任务使用 SQL 组合过滤和批量事件读取。
- 恢复一次点击的受控 SFTP 流程：只在 SSH 已认证且 SFTP 子系统明确不可用时确认启用，主机密钥确认保留原连接意图，连接/认证/主机密钥/启用/重连/根目录错误使用稳定分类。
- 文件管理 WinSCP 动作默认在 Python 主进程传入 URL 编码的设备 SSH 密码，并复用受控 SFTP 实际成功目标；Web DTO、Electron IPC 与安全日志仍不含密码或认证 URL。

### AC / FIT-AP

- FIT-AP 资源页移除顶部说明框，补齐“固化新 AP”“开启 AP 远程登录”两项固定动作计划闭环；动作任务与资源刷新状态分离，并通过 AC 级 resource key 防止并发配置写入。
- 新增当前 AC/勾选 AP 范围的 OmniPeek 名称表预览与 Export Process `.nam` 导出，复用共享 MAC 推导、异常校验、Artifact 清单和任务恢复；设备管理车载 MR 默认不进入该入口。
- FIT-AP 行右键菜单新增桌面版受控外部终端，复用系统外部终端程序路径设置，并固定以 Telnet 23 直连 AP IP；不再提供 FIT-AP 登录配置、SSH、端口、用户名或密码输入，也不查询设备管理中的同 IP 记录。Browser/Server、离线/无 IP/未配置终端程序场景失败关闭，API 不接受可执行文件、参数、协议、端口、用户名或密码。
- FIT-AP 详情光衰区域新增 AP 侧收光、交换机侧收光和 Tx Power 独立状态透传；当前值按真实分侧判定着色，避免整体告警把正常 AP Rx 或未判定 Tx Power 一起标红。
- 光衰异常说明补充分侧来源和真实收光数值，数据过期时继续保留状态但不计为当前异常。
- 已知安全收口项：动作页面未渲染或持久化 `confirm_token`，但当前计划 DTO 仍将其返回 Renderer 并由确认请求回传；后续需移出前端可见数据边界。

### 设备管理

- 未保存表单连接测试改用一次性内存凭据，只在 Worker 启动时消费并清零；任务参数、结果和日志不保存密码或 SNMP 团体字。连接过程补充分阶段进度、耗时和稳定失败分类，便于区分地址解析、端口拒绝、握手、认证和跳板机问题。

### 车内通信检测

- 车内通信检测页改为结构化业务表查询，“无线统计”不再走旧指标接口。
- 修复当前会话回落与业务表分页链路，未生成 parsed 数据库时仍可继续查看原始日志和已结构化业务区。
- 列车列表改用 `/train-communication/trains`，合并基础资料、点表和车载 MR 所属列车；`/online` 继续服务真正需要在线过滤的页面。
- 增加统一列车身份规范化，`列车01`、`01车`、`01`、`1`、`train-01`、`train:01` 和 `LC01` 等常见格式会归并到同一 `canonical_train_id`，用于在线状态、点表、拓扑和诊断结果匹配。
- 点表管理完成“生成预览 -> 保存点表 -> 原子替换 -> 重新读取 revision -> 通知父页面 -> 刷新拓扑 -> 允许开始检测”的闭环；当前列车无点表时可直接生成六节点骨架，MR 节点优先绑定正式 CT/TC MR。
- 解除在线状态硬门槛：没有快照、数据过期或双端离线时仍可按有效点表提交任务；AC/Mesh-Link 只作为辅助信息，真实结论继续由点表节点 SSH/Ping、VRRP 和跨 TC 检测给出。
- 软件版本同步升级到 `v1.4.1`，Electron 打包版本与发布入口保持一致。

### 轨道交通基础资料

- 完成线路与站点基础信息第一阶段：总览新增主线路径、站序递增/递减方向、站点来源分组和固定来源字段；站点模型扩展来源值/来源键、节点类型、路径、方向参与、结构、站台、端点、折返、启用和来源状态，继续复用 `__base_station__`/`raw_payload_json` 兼容旧 AP 派生站点。
- 新增设备管理站点来源只读预览，只读取当前局点中设备分组名精确为“车站”的 `devices.station` 字段；设备名称、系统名、位置、地址、设备类型和 IP 不参与站点识别。相同 station 合并统计来源设备数，空 station 只返回警告，停车场/车辆段默认不加入主线路径。
- 新增站点基础资料 XLSX 模板下载、导入预览和当前导出，模板包含线路参数、线路节点和字段说明。设备来源预览和模板预览都只应用到前端草稿，最终仍通过全局 `validate` + `changes`、`base_revision` 和单事务保存；来源消失只标 `stale`，不删除站点，不修改 `devices/device_groups`，也不覆盖结构、站台、顺序、折返和备注等人工字段。

### 配置采集与任务中心

- 修复配置快照勾选状态与实际对比输入脱节：同一设备勾选恰好两条快照时直接形成左右对比对；超过两条只禁用对比，不影响批量导出和删除；切换设备、类型或刷新后不复用不可见勾选。
- 轨旁 AP 光衰任务详情增加独立业务结果、成功/失败/跳过数量和原因展示，调度 `COMPLETED` 不再在详情中等同业务全部成功。任务列表和顶部警告计数尚未通用消费业务结果，仍可能漏标部分成功，列为后续代码缺口。

### MR/Mesh 性能

- MESH 链路、ACTIVE 点和切换事件补充兼容旧库的查询索引，链路明细批量读取改用稳定顺序的 keyset 分页，避免深分页随数据量增长反复扫描；业务字段、主备链和 Radio 语义保持不变。
- 纠正“轨旁信号图”曾被实现为 ACTIVE-only 主链图的问题：现在按完整采样帧返回全部真实 ACTIVE/STANDBY 轨旁链路，角色作为点属性，同一物理 AP/Peer/Radio 主备切换时保持同一图例、颜色和连续区段；按 frame 降采样会完整保留选中时刻的所有链路，并分别报告 frame、主备链路点、序列、存在区段、角色切换和缺失轨旁信号统计。轨旁专用只读查询不再为 10 万级行构造未消费的 synthetic metrics，AP 位置快照也改为一次性轻量读取。
- 轨旁图移除每点携带完整 `meta/seriesMeta/points` 的递归引用，改为浅层原始 payload、数字元组和外部只读索引；会话/来源/Radio 切换会取消旧请求并释放旧图与缓存。Electron 增加带会话、规模、heap 和渲染阶段的严格 workload 诊断，Renderer 与 GPU/Utility 退出分开记录，并为轨旁图提供不自动重载的进程内安全恢复。
- RSSI 分析新增“对比 / 主链 / 轨旁”三种工作区布局；对比模式在一份实际可用高度内上下展示两图并支持可拖分隔条，专注模式保留隐藏图实例、数据缓存和共享时间视口，布局切换只触发 ECharts resize，不重新查询或重建 series。
- RSSI 对比工作区改为按宿主顶部位置占满剩余视口，页面标题、来源、告警和统计在 RSSI 模式中自动紧凑；上下 pane 默认 50/50 且只允许 35%～65%，2K 每 pane 最低 400px、较矮窗口最低 320px，不足时由工作区内部滚动。“沉浸对比”保留左侧导航与一行工具栏，只通过 resize 放大两图，不重新请求、重建或销毁图表。
- 修正离线 MESH RSSI 图错误标注为 `dBm`：全部 ACTIVE 主链路与轨旁信号图纵轴统一显示 `RSSI`，Tooltip 保留设备日志原始数值且不追加单位，不进行正负号转换。
- 轨旁信号图默认隐藏数百条 AP/Radio 全量图例并回收底部空间；点击真实采样点可查看 AP 名称、AP MAC、Radio 和该点轨旁 RSSI，可选范围列表只显示当前时间窗口内有采样的序列并使用二分检索，内部物理射频和链路标识不再出现在图表界面。

### Online MR 实时收集

- Online MR 分析页业务表改为 `main_link`、`link_detail`、`channel_busy`、`switch_history`、`switch_realtime`、`interface_rate`、`fping_1s`、`iperf` 和 `diagnostics` 固定 key；旧 `mesh_link`、`mesh_detail` 仅作为短期 API 入参兼容别名，`radio_statistics` 不再作为独立业务表公开。
- 新生成的 Online MR 解析业务库使用 `online_mr_business_tables_v9_no_source_fields` schema，业务表、指标维度和切换 RSSI API 不再返回 raw/source 文件路径或行号字段；原始日志仍保留在会话 `raw/` 目录并通过原始日志页查看。
- 分析页页签和列名同步为主链路信息、链路明细、主链路切换历史、主链路切换日志、接口速率、fping 1s 聚合和打流测试，前端类型改为按业务表 key 约束返回行结构。

## v1.4.0 - 2026-07-21

### 设备管理与车载 MR

- 设备类型正式增加 `MR`，车载 MR 归一化为 `mobile_router` 并使用独立 H3C/Comware 只读设备详情 Profile；历史误存为 `Cloud-AP` 的“车载-MR”分组设备仅在名称符合 `列车<编号>-MR-CT/CW` 时受控迁移为 `MR`，迁移前自动备份当前局点数据库，真实 Cloud-AP 继续失败关闭。
- 设备管理批量更新详情增加确认、独立 loading、重复提交保护和即时提交提示，提交成功后继续打开统一任务窗口；CSV 模板、导入、筛选、新建/编辑和 Demo 数据同步支持 `MR`。

### Mesh 原始日志分析

- 轨旁 AP 业务页与光衰更新动作进入客户包默认启用；旧运行时 feature 文件中的历史默认关闭状态会被窄迁移为启用，不重置其他 Feature 配置。更新全部、更新站点和更新 AP 继续复用正式 Job Center 与 `collect_trackside_optical()`，单 AP 更新改为 UUID/MAC/名称交叉校验且不再回退站点或全局。
- 新增统一 `MeshLinkAnalyzer` 入口，报告、主链路建链顺序和链路明细导出共享同一参数快照；默认基准时间 4000ms、切换阈值 10、维持链路 22、发现链路 4，首个主链路忽略建链信号阈值。
- 链路明细导出增加导出前参数配置、局点默认保存、PIS/CBTC 模板和“分析参数”Sheet，导出与综合报告记录同一组有效参数。
- 报告与来源列表增加派生报告删除，删除前必须确认且只清理 `outputs` 中的报告/sidecar/临时文件，原始 MESH 日志、parsed SQLite 和 catalog 保留。
- 修复 RSSI 图切换节点与降采样折线使用两套坐标的问题：有效切换采样点优先进入返回折线，超出请求点数时自动提高有效预算，超过 2,000 点安全上限时明确告警并按时间抽样；红色节点只使用同一折线点的时间和 `local_rssi`，缺失、`0`、异常或未对齐采样不再画成普通切换节点。

### Online MR 实时收集

- 实时页只展示活动 Task/Session Mapping 对应的唯一当前 Session，不再回退最近历史 Session，也不接受历史 `session_id` 路由；终态后立即清空，历史查询、解析和报告统一进入“车载 MR 收集分析”。
- 当前 Session、采集项、轻量 preview 和日志增长每 5 秒更新；采集项由 Python 按 30/120 秒阈值标记异常和采集中断，fping/iPerf 写入原子轻量快照。主链路 view/结构化 sample 缺失时仅解析 raw 尾部 128 KiB，原始日志展开后每 3 秒读取一次；H3C 正数 RSSI 幅值由 Python 规范化为负 dBm。
- 修复现场 `display wlan mesh-link` 字段块格式未进入轻量预览的问题：`Peer Name/Peer MAC/RSSI/BSSID/Interface/Link state/Online time` 可从 raw tail 识别 `Active(ax)`，站点未匹配时仍显示主链路、Peer MAC、接口、链路状态和 RSSI。
- 实时页合并“当前采集状态”和“文件增长明细”为一张表，并固定并列显示主链路原始日志与 fping v5 原始输出；其他日志仍可切换查看，展开后保持 3 秒 tail。
- LOCAL Worker 在 Session 创建后异步启动 fping/iPerf，提前记录 `startup_timeline` 阶段耗时；SSH collector 命令文本和顺序保持不变，启动失败时同步回收已启动的 Traffic 子任务。
- 增加 `REAL_DEVICE_TEST=true` 服务端保护：仅允许宁波12号线01车，fping 固定 1000/4000 ms，iPerf 固定本地回环 TCP 2 Mbps；本地 server 随采集生命周期托管，历史业务数据保持只追加、禁止清理或覆盖。

### 验证范围

- 已执行 Mesh Python 定向测试、Mesh Vue 视图测试、Ruff 和 Web 生产构建；真实设备、真实 Electron 窗口和正式业务数据未在本轮操作。
- 已执行 Online MR Query/Web Control/Traffic 定向 Python 测试、实时 Store/页面/控制组件 Vue 测试和 TypeScript 检查；真实 01 车结果以本轮现场验收记录为准。

## v1.3.9 - 2026-07-18

### MR 分析可用性修复

- MESH 离线分析表格改用跨日志稳定列偏好；Electron 通过受控 UI preference Bridge 持久化，Browser 保留本地 fallback。RSSI 图将切换时刻线与真实切换节点拆为独立开关，并增加来源/Radio/时间间隙严格分段的站点区间带和基于接收信号事实字段的安全 Tooltip。
- 移除 MESH 页面 AP 统计入口和请求；新增独立链路明细 Export Job。综合报告移除全量链路及全局 AP/Peer 聚合，新增逐参数展示报告覆盖、来源快照、局点配置和默认值的“分析参数与阈值”大表。
- 修复车载 MR 收集分析页中裸 `Search`/`Document` SVG 被全局样式放大、覆盖页面的问题；内联图标统一使用有界 `el-icon`，报告区限制为局部滚动的紧凑卡片。
- Online MR 会话详情不再依赖 parsed SQLite 成功：STOPPED、ABORTED、强停、partial、缺库、旧库或损坏库仍可查看 metadata、原始日志和采集日志；解析状态明确区分 `ready/missing/legacy/stale/unreadable/parsing`，报告仅在 `ready` 时进入 Export Process。
- Online MR 分析页增加请求 generation 与 AbortController，切换会话、局点或查询窗口时先清空指标、时间线、切换窗口、raw tail 和报告任务展示，迟到请求不能把旧会话曲线写回新会话。
- 恢复“解析当前会话、重新解析、强制重新解析、打开任务窗口”操作，继续复用现有 `online_mr_parse` Job Center handler；解析失败保留原始会话。
- MESH 查询按会话隔离旧 schema、缺表和损坏 SQLite；概览和会话列表不会再被单个旧库拖垮，缺少诊断表时异常数量显示为未知而非伪造 `0`，旧绝对路径失效时只读使用当前 MR parsed 目录同名结果。
- 新增受控 `mesh_schema_rebuild` Job：从受保护 raw 日志归档并重建派生数据库，原始日志不删除，失败或取消恢复旧索引与 parsed；页面各指标区独立降级，兼容区域、会话信息和原始来源继续可用。
- MESH 离线分析完成主链路建链顺序、完整链路明细、单 AP/全部 ACTIVE RSSI、空口 Tx/Rx Busy、切换点和全部经过时段图表闭环；同一采样点 STANDBY 备链严格按来源/时间/tag/Radio 匹配，图表和报告共享 AP 位置快照。
- 图表服务端按 Radio/时间窗口降采样并返回实际点数，切换事件索引优化后真实 34-CW ACTIVE 图约 3.3 秒、目标 1200 点；报告嵌入图硬上限 5000 点，完整业务 Sheet 不截断。报告支持显式 typed 临时分析参数，不写回来源或局点配置。
- MESH RSSI 与空口负载建立共享毫秒时间视口契约：Peer、切换线、切换节点、站点区间带、主题、窗口缩放和侧栏变化不再重置当前缩放。RSSI 可锁定当前时间范围并以相同 Radio、ACTIVE/Peer 模式、锚点和全部经过语义重新查询同期 TxBusy/RxBusy；两类图表使用独立响应状态，API 明确返回 requested/effective 与实际采样边界，切换会话或分析上下文自动解除锁定。正常持久化 Electron 的 `列车06-MR-CT / 6CTmeshlog.log` 人工点击验收仍待本机执行，自动化不替代该项。
- 收紧 MESH 详情界面：移除 Rate 原始值、Retry/Error 增量和异常摘要三个 Web 页签，主链路、链路明细、RSSI 与空口图按可视区域自适应，RSSI 二级 Tab 不再撑出中间空白；页面内任务结果改为紧凑摘要。
- Electron 任务中心改用独立 `/desktop/tasks` 精简布局并复用原 `JobCenterView/useTaskStore/Task API`；加载状态、交互就绪、超时、失败重试和主窗口回退均返回真实 IPC 结果，不再打开纯色空白子窗口。
- 修复 AC/FIT-AP 光衰统计将“AP 离线”错误作为告警前置条件的问题：在线 AP 的一般/严重光功率告警现在进入概览、异常列表、轨旁 AP 当前异常导出和报告；离线与光模块健康保持独立。当前异常按 AP 去重，明确“无光模块”不计入，24 小时过期样本保留历史但不作为实时正常或当前异常统计；详情页增加在线状态、光衰判定、告警等级和数据新鲜度。

### 本次验证

- Python 全量 `2236 passed, 1 skipped`；Vue 全量 `84` 个测试文件、`317` 项通过；Web TypeScript 与生产构建通过。
- 全仓 Ruff 通过；Electron-only 架构九门 `9/9` 通过且新增 finding 为 `0`；目录 README 门禁通过。
- 使用开发数据只读核验杭州地铁 4 号线 A/B 网与宁波地铁 12 号线共 22 个 Online MR 会话，覆盖 STOPPED、ABORTED、强停及 ready/legacy/missing parsed，基础详情失败为 `0`。宁波地铁 12 号线 `列车07-MR-CT` 旧 MESH 结果可读取 `113,954` 条链路并识别迁移后的 parsed 路径。
- Electron 亮色/暗色真实窗口截图和现场交互仍需本机人工确认；自动化结果不替代视觉验收。

### 在线列车车内通信检测

- 恢复点表驱动的固定六节点拓扑配置，增加点表缺失、无效、重复和 revision 冲突校验。
- 将点表维护和检测执行挂接到正式在线列车车地通信页面，并保留 Task Center 任务链路。
- 区分点表未配置、节点未检测、检测中、正常、异常和数据过期；IP-only 服务节点不再因缺少 `device_id` 被误报为未配置。
- 点表缺失或不完整时，VRRP 与跨 TC 状态统一显示为未配置。

### 局点与数据存储

- 修复软件运行日志三天保留失效：自动任务只处理 `runtime/logs` 固定白名单，按记录时间流式清除 72 小时前内容，malformed 行保留，失败不替换原文件；运行日志按跨天或 25 MB 轮转并支持跨文件分页/导出。自动提交增加同数据根单飞、成功后 24 小时节流和持续运行复查；缓存与临时文件只保留手工确认入口，局点业务 `logs/`、MESH/MR raw/parsed、报告和 Artifact 明确禁止自动清理。
- 新增 Legacy/Demo 局点只读审计、Task Center 审计任务和 `audit_sites` 维护命令；审计记录文件哈希、SQLite 完整性、业务数据及 Registry/bootstrap 引用。空壳回收改为 prepare/apply 二阶段，执行前复核 manifest，只移入带 tombstone 和配置备份的受控回收区；受控 Demo 通过当前 Schema、Repository 与 parser 在 staging 重建，不预置任务历史并强制小于 `50 MB`。`isolated_test` 继续拒绝上述持久写操作，真实数据回收和 Electron 人工验收需单独执行。
- 完成仓库根历史 `data/` 与正式开发数据根的 dry-run 对照：根目录仅含旧 `demo` 配置、SQLite 和瞬态 sidecar，所有正式目标均已存在且没有仅根端存在文件；旧副本按逐文件 SHA-256 清单移出仓库归档，未覆盖正式数据库。构建清理工具新增 `build-temporary` 固定白名单，只回收可重建的 `dist/_build/`，保留版本 Backend、Electron 和 Agent 交付目录。
- 修复 Codex、任务窗口和打包冒烟把临时数据根/`demo` 写入正式 Electron bootstrap 的问题：隔离运行现在同时使用独立 data root 与 `userData`，禁止局点/迁移/导入导出写操作，正式 bootstrap 在测试前后保持不变；新增无效临时引用拒绝、字节备份和显式维护修复命令，Python 环境失败不再影响存储状态。
- 新增 Electron 系统设置中的局点 Registry、稳定 `site_id`、中文显示名称、新建/切换和活动任务门禁。
- 新增全局数据根校验、staging 迁移、SQLite 完整性检查、旧数据保留和 Electron bootstrap 原子配置。
- 新增 `.ncsite` manifest/checksum 导出导入、凭据清洗、路径穿越/符号链接/压缩大小防护、替换前自动备份和失败恢复。
- 长操作统一进入 Task Center；真实设备和人工桌面点击验收仍待执行。

### Electron 功能对等

- 修复系统设置工具路径按钮在窄窗口和缩放场景下重叠的问题，统一为可换行的独立按钮组和字段级反馈；PuTTY 白名单新增大小写不敏感的 `putty64.exe`，同时保留 `putty.exe`，Electron Main、Python 保存和真实启动点继续拒绝其他程序。
- 统一任务窗口完成取消竞态、终态收敛、日志脱敏、Artifact 授权、受管下载、打开文件与定位目录闭环；任务子窗口保持单实例并可在加载失败或崩溃后安全重建，关闭窗口不停止后台任务。
- 设备管理完成真实 CRUD、凭据保持/替换/清除三态、导入预览、诊断与设备导出 Artifact、统一任务摘要以及 SecureCRT/Xshell/PuTTY 严格白名单桌面契约；真实设备连接和外部终端点击仍待现场验收。
- 新增设备快速详情抽屉与 `/devices/:deviceId` 完整详情页，共用 Device Detail Application/Query Service、分页 DTO/API 和 Vue presentation；开页只读最近快照、页签懒加载，刷新通过 Task Center 的 `device.inventory.collect`。当前命令执行只允许可执行 Profile 匹配的 H3C/Comware 交换机，H3C AC/MR 仅关联现有业务查询，Huawei/ZTE 与未知或未验证平台失败关闭。设备详情不提供独立 Health 契约；LLDP 公开 DTO/页面移除邻居能力和型号；接口移除入/出速率、错误统计及最后变化；光模块移除采集状态和阈值来源，正常状态不展示原因，异常原因继续中文显示并按后端严重性使用语义告警色；关联业务公开契约移除重复的 AC/AP、交换机、光模块严重性及 MR 会话字段。完整页按剩余视口高度伸展，抽屉继续限制独立滚动高度。被删除的公开字段不保留 DTO/TypeScript/API 别名或双读兼容；存储层本轮未改 schema，仍按各业务的现行事实字段读写。定向自动测试已通过，Electron 视觉交互和真实设备验收前状态保持 `IMPLEMENTED_UNVERIFIED / REAL_DEVICE_PENDING`。
- 设备详情的轨旁 AP 关联业务按后端光衰状态显示中文和语义颜色；光模块页与关联业务中的 `no_module` 统一为中性“无光模块”，不再把未安装模块的功率占位符标红或视作光衰异常。
- AC/FIT-AP 完成 AC 信息、资源、Radio、光衰、写操作、单 AP 深度更新、元数据导入/保存、历史查询和 AC Web 入口；光衰导航与重复 Tab 已并入 FIT-AP 资源，列默认按连接交换机和端口自然升序，站点缺失时只提供唯一 LLDP 交换机站点建议，未经人工保存不写库。Mesh-Link 对外契约硬删除链路状态/信道/带宽/AP 状态/光衰状态旧字段，改为展示轨旁 AP 室外侧和室内侧收光，不保留 API/TS fallback。普通更新与 verbose 深度更新保持分离，真实 AC/AP 验收仍待现场执行。
- 轨道交通按历史有效业务契约拆分车内点表、轨旁 AP 规划与业务、在线列车 CT/TC、连续采集、Online MR 实时/分析、强停恢复、离线 MESH 导入分析与报告，不再以只读聚合页代替业务闭环。轨旁 AP 业务表已改为内容居中、自动表格布局和通用接口简称，后续刷新保留上一次成功数据；光衰状态按 Python 严重性事实源中文化并着色。“无光”属于光衰异常，“无光模块”仅表示模块缺席，不计入异常数量或“仅光衰异常”筛选，并以中性状态色展示。新增的业务导出只通过 Export Process/Task Center/Artifact 执行，保留原 8 个业务 Sheet 与 `_netconsole_meta`，并统一 `A2` 冻结、筛选、居中和采样自动列宽。
- 轨道交通“基础资料”升级为默认锁定的统一维护入口：站点、区间、轨旁 AP、车载 MR 和轨旁 AP 规划共用数据库哈希 revision、Python 校验和单 SQLite 事务，保存失败保留修改，路由离开/刷新/锁定受未保存保护。独立规划页面、AC/轨交重复导航和 AC 资料页重复规划卡片已移除，旧路由重定向到基础资料规划页签；规划导入预览、导出和 Task Center 继续复用既有服务。基础资料父页面和规划页签建立草稿时统一把 Vue reactive DTO 转为普通对象，修复 `structuredClone` 抛出 `DataCloneError` 后页面立即回到锁定状态的问题。
- 轨道交通基础资料增加线路名称、项目类型、网络类型和备注的正式编辑入口；revision 同时覆盖 SQLite 与 `site_meta.json`，metadata 使用原子替换并在 SQLite 失败时补偿恢复，补偿失败会返回独立错误而不是静默吞掉。正常 `persistent` Electron 受管短期会话可显式启用当前局点写入；`isolated_test` 返回 `ISOLATED_TEST_READONLY` 并显示明确原因，普通 Server/浏览器默认仍拒绝。真实 Electron 已完成 MESH 菜单进入、解锁、站点/规划/列车页签控件启用和重新锁定验收；当前活动局点为宁波地铁 1 号线，按数据保护要求未切换局点，宁波地铁 12 号线真实保存与重启持久化仍待人工执行。
- MESH 派生库升级为 `meshlog_compact_v3_tagged_samples`，同一毫秒的日志序号进入样本唯一身份，避免多块数据被合并或误报多 Active；旧派生 schema 不在正式代码中兼容，新增默认 dry-run 的外部维护工具，从受保护 raw 显式重建并在失败时恢复旧派生数据。
- MESH ZIP 导入增加安全 preview、人工列车/端位/Profile 映射、独立 Job、隔离 Profile/SQLite 解析、Windows 原子目录提交和成功 manifest；真实 12 文件包完成 353,035 条记录解析与重复 SHA 幂等复验，manifest 和公开 DTO 均不暴露临时或服务端绝对路径。动态图新增本端/对端 Rate 原始值、后端计算的 Retry/Error 非负增量及切换前后 RSSI 事件散点，不再保留永久占位图。
- Online MR 分析页改用真实 Radio Statistics、历史/实时切换 RSSI 事件和按总量封顶的分页指标契约；保留旧 `/metrics` 列表响应，新增分析页专用 `/metric-page`，时间轴查询不再先全量读入。图表卸载时统一释放 ECharts、ResizeObserver、主题订阅和轮询；真实 MR 会话与现场设备时钟对齐仍待验收。
- 修复局点 Registry 只显示 `demo` 的问题：启动时幂等补登记已有的中文/历史局点目录，生成稳定内部 ID 并保留原目录；切换和 Backend 重启按 Registry 解析真实目录，不重命名、不重建旧局点数据库。
- 打通 MR 原始 MESH 日志正式导入闭环：导入弹窗从当前局点 VehicleMr 显式幂等准备内部归属，修复 500/200 分页不一致和双数据源互相拖垮；ZIP、LOG/GZ 与文件夹统一安全预览并自动匹配 CT/CW，确认后由 Job 原子归档、解析并返回新 Session。来源保存相对 raw/parsed 与 bundle provenance，主按钮只恢复/重建当前来源；真实 12 文件包复验 353,035 条解析记录、12/12 raw/parsed 与重复 SHA 幂等，宁波 1 号线 06/34 四个 missing 来源从现存 raw 修复为 ready。
- AC 管理下独立 Mesh-Link 在线监控已合并到“轨道交通 / 列车在线情况”：每列车一行聚合 CT/TC 两端 MR、当前轨旁 AP、MAC、Radio、RSSI、站点/区间/里程、方向、匹配状态、两侧收光和更新时间；综合状态、数据过期和匹配结论由 Python Query Service 返回。旧页面、Store、导航和页面 API Client 已删除，旧 URL 重定向；Parser、Repository、历史快照、raw、Query Service 和受控 `ac_mesh_link_refresh` Task 保留，底层旧 API 标记 deprecated。
- 在线列车车内通信检测收口为 TC1/TC2 固定六节点拓扑状态页，只保留节点/链路、VRRP、跨 TC、刷新和车内通信诊断 Task；移除本页的轨旁 AP、RSSI、fping/iPerf、光衰、Online MR、Agent、Mesh-Link 及综合统计入口。缺少 SW/SRV 关联或检测事实时明确显示“未配置/未检测”，不由 Vue 猜测正常状态；独立底层业务模块不删除。
- 配置采集完成真实采集/保存、跨设备快照选择、左右双栏差异、删除回滚、导出 Artifact、取消和恢复；文件管理完成本地/设备双栏、受控 SFTP、持久下载队列、重试/清理/恢复、MR 日志归档与导入。
- 设备文件下载完成 Qt 历史 SFTP 行为取证、主备地址/凭据复用、受控命令 Profile 和设备侧只读边界；新增应用内主机密钥首次信任/仅本次信任/密钥变更阻止、数据根下原子 known_hosts、结构化错误和下载页兼容重定向。SFTP 自动启用固定为独立 `config_write` 操作，仅在用户授权、SSH 登录成功、明确确认子系统不可用且命中 H3C Comware V7 精确 Profile 时进入统一任务链；交换机、无线 AC 和车载 MR 均保持 `REAL_DEVICE_PENDING`，Huawei/ZTE/未知版本失败关闭。全局确认统一收口到 `NcConfirmDialog/useConfirm`，外部终端密码传递使用 `SECURITY` 确认；自动启用、真实 SFTP、主机密钥和桌面动作仍待现场验收。
- 网络工具完成 Ping/fping/TCP、持续探测增量结果、iPerf、无线扫描分页/状态/详情和安全导出；命令参考完成实时搜索、共享任务窗口导出和取消收敛。
- 系统设置整合主题、语言、工具路径、中央功能 profile、预览和原子保存；应用日志与安全维护完成日志展示、脱敏、受控清理、取消、日志/许可证导出及 Artifact 闭环，不再保留第二套独立功能开关页面。

### 桌面与发布

- 建立并完成全局表格与字段展示契约：新增强类型 `NcDataTable`、真实文本测量、字段类型宽度基线、稳定抽样、防抖、跨页宽度保持、手工列宽和按用户/路由/表格/语言隔离的视图偏好；强制 `baseWidth >= headerRequiredWidth`，容器不足时使用表格内部横向滚动。容器更宽时按 `priority/normal/fill` 和最大宽度分配剩余空间，状态、时间、操作与固定列保持边界，全部列达到最大值后列组居中；`ResizeObserver` 负责侧栏、窗口、抽屉、字体和语言变化后的重算。设备管理已显式配置站点、系统名、分组和地址的业务权重，固定名称列继续按内容基线计算。当前清单登记的 77 张标准表格均继承公共策略，旧表基线为 0，UI Guard 阻止页面自行测宽、平均分配或限制百分比宽度；真实业务页截图基线、中英文/浅深主题组合及 Electron 人工视觉验收仍待执行，不能据此宣称人工视觉验收完成。
- 统一 Vue/Electron 全局主题：浅色、深色和跟随系统现在同时驱动侧栏、顶部栏、内容区、Element Plus 浮层与 ECharts，不再默认固定深色侧栏；系统设置仍是唯一持久化来源。Renderer 只通过严格单向 IPC 报告解析后的 `light|dark`，Electron Main 只映射预定义窗口背景，不能接收任意颜色或窗口参数。历史页面状态色已收口到语义 Token；Guard 已收窄 `--nc-text-primary` 被误判为状态色的规则并增加单元测试。Electron 多尺寸/多缩放人工视觉验收仍为 `PENDING`，自动测试不代表视觉通过。
- 将 Windows x64 iPerf3 运行包升级并固定为用户提供的 `ar51an/iperf3-win-builds` 3.21 `win64-dynamic-auth`，补齐发行来源、四文件 SHA-256、GPLv3/LGPLv3/链接例外及 Cygwin 3.6.7-1 对应源码方案；fping 5.5/Cygwin 3.6.9-1 同步归档实际 ICMP 兼容补丁、构建配方、完整许可证与精确对应源码。Electron 与 Agent 打包复制前后只校验并复制仓库本地白名单工具，拒绝联网补齐、同名替换、来源篡改和额外文件；旧 3.20 来源不匹配文件不再保留。
- 新增 `pnpm dev:codex` 本机受控调试链：Electron Main 继续持有唯一 FastAPI 生命周期，Vite/FastAPI 固定绑定 `127.0.0.1:5173/8000`，每次启动生成短期 Session 与系统临时数据根；浏览器 Vue 可复用正式 REST、WebSocket 和下载契约。新增鉴权、回环限定且路径脱敏的 `/api/dev/runtime-status`；生产 Electron 不注册该接口、不接受固定开发端口，也不暴露令牌、OpenAPI 或 DevTools。
- 建立首个版本化网络设备命令 Profile：`device.inventory.collect` 以稳定 Operation/step/parser/DTO contract 接管 H3C/Comware 交换机详情采集，保持原命令原文、顺序与失败继续语义；Huawei/ZTE 和未知角色/平台失败关闭，真实设备仍待验收。
- 生产 Electron Backend 不再注册 `/docs`、`/redoc` 或 `/openapi.json`，开发诊断 Server 仍可提供 OpenAPI；生产 BrowserWindow 显式关闭 DevTools，开发 Vite 保持可用。主任务窗口与任务子窗口统一使用同一开发状态，不再读取错误的环境变量。
- 新增构建产物安全回收脚本：严格白名单、默认 dry-run、拒绝路径逃逸和符号链接；已按用户授权回收仓库 `dist/v1.3.8` 历史 Qt 临时终版 9,804 个文件（约 2.63 GB），未触碰 v1.3.9、Electron 构建或业务数据。
- Electron 启动链新增单调时钟时间线，区分状态页、Backend handshake/health、Vue mounted 和真实 interactive；Desktop 历史任务及 Agent/Traffic/File 恢复移出首屏关键路径，Netmiko/OpenPyXL 改为首次真实使用时加载。连续两次源码冒烟的可交互时间为 1991.2 ms 和 2068.2 ms，相对同口径 2926.8 ms 基线中位改善 30.6%。
- 源码开发数据根迁至 `%LOCALAPPDATA%\NetConsole\Development`，打包态使用 `%LOCALAPPDATA%\NetConsole`；Electron 明确向 Backend 传递运行模式和数据根，拒绝仓库/安装目录内写入。历史 `.local/data`、`.local/runtime` 与根 `data` 已通过无覆盖、哈希和 SQLite Backup API 迁移，冲突保留，明确测试残留按白名单清理。
- 删除 Python 启动壳中的 Qt Shell、Qt capability probe、旧 `--web-shell` 和提权 Qt 子入口；无参数 `main.py` 作为 PyCharm/源码开发入口启动项目本地 Electron 编排链，正式桌面生命周期仍统一由 Electron Main 管理。打包 Backend 使用内部 `--electron-backend` 分派受管 Runtime，源码 `web/server` 仅保留回环开发诊断。
- Electron 开发编排不再依赖调用方提供全局 `pnpm`：项目本地 Electron 可作为 Node 运行时完成 typecheck、main/preload 构建、Vite 和 Electron 启停；无参数 `main.py` 自动传入当前 `.venv` Python，并保留端口与子进程清理门。
- SNMP Center、通用 MIB/OID 字典、版本化 MIB 归档、Trap/Poll/拓扑、通用查询与批量采集，以及无线勘测/热力图链已从活动产品、源码资源、Job/Export、依赖和发布内容中删除；Pillow 与 pysnmp 不再作为产品依赖。设备管理只保留 SNMP v1/v2c 只读连接测试和基础识别，网络工具无线扫描独立保留。
- E1 回收无调用的 `apps/desktop` Qt WebShell、包标记、`src/netconsole/ui` 与 Qt-only 运行测试；历史行为统一由 Git 和最终迁移矩阵追溯。
- E10B 建立九个公开架构门和统一入口，覆盖分层、禁用依赖、Direct SQL、设备命令、UI 业务逻辑、移除功能、运行路径、孤儿模块与迁移映射。Direct SQL 已对 61 个文件精确分类且 `VIOLATION=0`；限时例外已由 42 条收敛为 38 条（Python 分层 14、孤儿候选 24、状态色 0），`check_ui_business_logic.py` 当前为 0 finding / 0 waived；目录门建立时 139 个维护目录 README 0 缺失。命令目录已登记 `device.inventory.collect` 和 `device.sftp.enable` 两个稳定 Operation；SFTP 自动启用已进入统一任务链，但 E11 命令平台、E12 API v1 以及 Electron/真实设备验收均不因本项提前完成。
- Electron main/preload 保持 sandbox、白名单 IPC、动态回环 FastAPI、会话令牌、下载退出屏障和受管 Python 生命周期；开发资源、生产资源和无效 Python 失败冒烟均通过且退出无 5173、Electron、Vite 或受管 Python 残留。
- Browser 模式只保留源码开发、联调和诊断；Electron 是唯一正式桌面产品。Qt 源码、运行时、入口、测试环境和发布链已经删除，历史行为仅通过 Git 与最终迁移矩阵追溯，不得恢复为回退入口。
- 清理并归档阶段性 Codex 任务、worktree 和本地分支；CentOS 7、Windows Legacy 兼容包及旧 Qt 临时终版明确放弃，不进入 `main`。完整归档见 [Electron 对等迁移第二波归档](development/electron-parity-wave2.md)。

### 数据库

- 基于真实 `devices.db` 的 SQLite Backup 副本和 `EXPLAIN QUERY PLAN`，为设备接口/光模块/LLDP 历史及 FIT-AP 资源/Radio/LLDP/光衰历史增加 7 个幂等复合索引；典型 100 行查询由全表扫描和临时排序降至索引搜索。旧库副本迁移保持行数、通过 `quick_check`，未删除表、字段或业务数据；Task、Agent、Traffic、iPerf、Online MR 与 MESH 未发现需要强制 schema 修改的证据。
- 新建 `devices.db` 只创建设备 SNMP v1/v2c、端口、RO community、超时和重试字段；活动模型、DTO、API 与导入导出不提供 v3/RW/Context 旧字段别名、双读或 fallback。如需从历史库物理移除退役列，只能通过独立维护脚本备份后重建/迁移，不进入正式启动路径。

### 验证

- 2026-07-19 在本轮所有并行改动提交到最终 `main` 组合后执行一次必要全量门。Electron 多尺寸/多缩放人工视觉验收仍待执行。
- Python 全量运行结果为 2128 项通过、1 项跳过、1 项失败；唯一失败是设备详情 API 旧断言仍期待全字段空端口为 `no_light`，已按已确认产品规则改为 `no_module`，随后只定向复验设备详情 API/Query Service 16 项全部通过，未重复运行 Python 全量。`pip check` 通过。
- Vue：69 个测试文件、249 项测试通过，TypeScript 检查与生产构建通过。本轮未修改 Electron Main/Preload，按定向优先原则未重复执行 Electron 全量。
- 全仓 Ruff 通过；Electron-only 架构九门 `9/9` 通过且新增 finding 为 0；目录 README `145/145`、文档/目录质量测试 14 项通过。
- Electron `win-unpacked` Package Smoke、NSIS 1.3.9 安装器生成、系统临时目录静默安装、受管 Backend 启动冒烟与卸载通过；Agent Windows x64 完整构建、Go 全量测试及交付目录本地工具复验通过。

## v1.3.8 - 2026-07-12

### 本次修复

- 网络工具 Electron 页面收口重复入口：Traffic 独立承载 TCP 端口、fping 与 iPerf，小工具独立承载 IP 计算和五类 Ping，无线扫描新增正式路由并接入网卡/扫描源、过滤、启停、自动刷新、历史、Raw、详情和 CSV/XLSX Artifact。网络任务恢复统一消费 tasks store，不再用组件 `localStorage` 保存任务 ID；IPOP 已接系统设置与语义 Native Bridge，仍不开放任意程序启动。
- 命令说明开放正式 Feature 与导航，接入共享动态语言、统一任务窗口模块筛选、真实取消和安全 Markdown Artifact；网络工具、命令说明与日志维护任务均复用现有 Task Center 和 Electron 下载白名单，不建立第二套任务模型或路径接口。
- 应用日志与安全维护完成 Electron 真实闭环：安全清理支持 1～365 天、扫描后按类别选择和二次确认，Worker 只处理运行日志、页面缓存与临时目录白名单，删除前重新校验年龄和路径，并保护 Job/Export 协议、导入预览、数据库、raw 与正式报告；取消保留未处理文件，标准进度事件可恢复已处理、删除、失败和释放空间计数。日志 CSV 与开源许可真实 TXT/XLSX 复用公共 Export Process/Artifact，公开名不含 UUID 或服务端路径；日志展示和导出补齐密码、Token、Community、私网 IPv4/IPv6 与 Windows/UNC 路径脱敏。自动测试已完成，Electron 人工确认、取消、保存和重启恢复仍待验收。
- 文件管理按 Qt 双栏事实源完成 Electron 纵向闭环：本地/设备目录导航、分组筛选、受控 SFTP、明确确认的 H3C SFTP 准备、多选串行下载、TaskRepository 持久队列、取消/重试/清理/重启恢复、`.part` 清理、MR Mesh 日志归档与自动导入均接入永久 Service；设备文件使用 `fd1_*`，不伪装 Artifact。新增 `fda1_*` 一次性桌面动作和 Electron main 固定回环白名单，可打开受控目录并启动固定 WinSCP；Renderer 不接收路径、程序或凭据，Electron WinSCP 参数不含密码。自动验证通过后状态为 `IMPLEMENTED_UNVERIFIED`，真实 SFTP/MR、大文件异常和桌面点击仍待验收。
- 设备管理 Electron/Qt 对等整改继续收口：删除旧只读校验链，编辑改为真实保存并同步详情；秘密字段增加保持、替换、显式清除三态且不回显；新增/编辑表单连接测试现已默认启用并接通共享 Job Runtime，一次性临时密码只经 stdin 敏感 bootstrap 注入，已保存密码由 Worker 按 `device_uuid` 解析，Job 参数、Task 数据库、响应和日志均不保存明文；任务提供验证、凭据解析、连接、握手、认证、会话验证和安全终态，弹窗可查看结果、失败分类、耗时并打开统一任务窗口。CSV 导入增加已有主地址重复行预览及拒绝/跳过/仍新增策略；诊断下载生成含摘要、真实诊断文件和 manifest 的受控 ZIP Artifact；CSV（含/不含凭据）、模板、SecureCRT、OmniPeek 均由独立 Export Process 生成并通过 Electron 受管下载，成功保存后可使用已授权路径打开文件或定位目录；SecureCRT/Xshell/PuTTY 继续由严格 DTO 和白名单本机 Adapter 以 `shell=False` 启动。设备页面已移除私有 `sessionStorage` 任务记录并接入统一任务窗口；人工桌面与真实设备验收前状态保持 `IMPLEMENTED_UNVERIFIED / REAL_DEVICE_PENDING`。
- 配置采集中心按 Qt `ConfigCollectionCenterPage`、`ConfigLifecycleWorker/Service` 和 `ConfigDiffViewer` 实现 Electron 纵向链：纠正 `save force` 与 saved-configuration 快照语义，增加跨设备独立左右快照篮、“设备名 · 类型 · 时间”比较标题、共享 raw log 引用安全与删除前原子隔离/DB 失败恢复、直接 config Job handlers、双栏 added/removed/modified 差异与导航、真实 Export Process/Artifact、项目边界取消和检查点重启恢复，并以 Vue mount 测试覆盖采集/保存/删除/比较/导出/统一任务窗口；未修改数据库 schema，也未连接真实设备，状态保持 `IMPLEMENTED_UNVERIFIED`。
- 收口第一批 Web 对等整改：设备管理补齐受控 CRUD、导入导出与诊断，网络工具补齐 Ping/fping/TCP、无线扫描与 Artifact 导出，配置中心补齐历史删除、`save force`、报告和目录动作，文件管理补齐只读 SFTP 下载，AC/轨交补齐 AP 扩展、车内诊断、MESH 导入和报告闭环。所有新增高风险入口均独立 Feature Gate、默认关闭且仅完成 Fake 验收；Qt 页面继续保留，真实 AC/MR/无线硬件验收未开始。
- 修复 Electron 开发态文件管理、配置快照与 MESH Artifact 下载仍落入 Vite 固定 `127.0.0.1:8000` 的问题：三类入口统一使用 Runtime Adapter；Electron main 通过当前动态回环后端与内存令牌流式保存并原子替换，Browser 继续使用相对代理下载。主窗口新增同源及编码 `/api`/`/ws` 导航拦截、非桥接 Chromium 下载拒绝、Renderer/preload 故障状态与脱敏诊断。退出时先拒绝新下载、取消并等待在途写入清理；Python 在 Uvicorn 完全退出后发送 `shutdown_ack`，Main 再发送 `exit`，全部受管清理完成后 Electron 才退出。默认菜单、窗口标题和迁移期页脚同步收口。本轮未启动 Online MR 完整操作闭环迁移，Qt 仍是生产与回退入口；人工原生对话框与关闭残留仍需在本地主工作区点击验收。
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
- 统一既有 Qt 窗口标题为 `NetConsole v1.3.8 by WXJ`，分离 Git SSH 推送地址与关于页 HTTPS 浏览地址；修复弹出模块错误复用“设备管理”的当前页归属。
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
