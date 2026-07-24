# MR/Mesh 日志分析规则

## 1. 适用范围

本文描述 MR 原始 MESH 日志的导入、解析、链路区段、切换/乒乓、质量规则、页面和 Excel 报表。原始日志是事实来源；目录库、单文件 parsed SQLite、缓存、图表和报表都是可重建产物。

解析兼容性以实际行格式为准，不按“Comware V5/V7/V9”名称做无条件保证。没有 Peer Name 时仍可依据合法 Peer MAC 解析；名称、物理 AP 或站点归属无法解析时必须保留空值/未解析状态，不能猜测。

## 2. 导入与存储

- 原始文件归档到当前数据根的局点 MESH MR `raw/` 目录，重名使用防冲突归档名；路径由 `PathResolver` 解析，不写死仓库或历史 `.local` 位置。
- `catalog.sqlite` 和目录型 `mesh.sqlite` 管理文件目录与入口；明细数据可能在 `source_files.parsed_db_path` 指向的单文件 parsed SQLite。
- `raw/` 永不因解析失败而删除；`parsed/` 和 `outputs/` 可重建。
- 解析保留源文件、源行号和必要原始证据，便于从报表回溯。
- 当前派生库 schema/parser 版本为 `meshlog_compact_v3_tagged_samples`。同一毫秒内日志携带的 `(2)`、`(4)` 等 `timestamp_tag` 属于采样身份的一部分，解析、唯一键、链路分组、质量分析和报告不得把它们合并。
- 正式启动和查询不兼容旧派生 schema，也不自动移动、删除或清空用户数据。检测到旧版或损坏的 `mesh.sqlite` 时返回需要重建的明确错误；常规处理通过应用内 `mesh_schema_rebuild` Job 从受保护 raw 重建，`scripts/maintenance/rebuild_mesh_parsed_data.py` 仅保留为维护 CLI 适配器。重建只归档派生数据库和 `parsed/`，不移动或删除 `raw/`、`outputs/` 与 catalog，失败时恢复旧派生数据。
- 设备文件下载链路不得为归档原始 `meshlog` 而初始化派生 SQLite；旧 schema 只能影响后续导入/查询状态，不能阻止 raw 文件落盘。
- 正式资产来源是当前局点基础资料/设备管理中的车载 MR。打开导入时由显式 ApplicationService POST 按 `linked_device_id → device_uuid → 规范化名称` 幂等准备内部 Profile；设备改名只更新显示名，稳定 `safe_folder_name` 和已有数据目录不变，普通 GET 不隐式写库。
- ZIP、单个/多个 LOG/GZ 和文件夹统一为“安全预览 → 自动确认唯一列车号/CT-CW/正式 MR 映射 → `mesh_bundle_import` Job → 隔离 Profile/SQLite 导入 → 路径复验 → 原子目录提交 → 成功 manifest”。非 ZIP 上传只在运行时缓存封装为受保护 ZIP 后复用同一链。Preview 使用有 TTL/总容量限制的随机 ID，Renderer 不接收绝对路径；检查成员数、单文件/总解压量、压缩比、加密、符号链接、路径穿越、重复显示名和扩展名。整批成功前不得发布成功 manifest，失败或取消恢复原 Profile/catalog。
- `source_files` 保存 `raw_relative_path`、`parsed_relative_path`、bundle/archive SHA 与成员 ID/SHA。读取优先使用当前 MR 相对路径，其次安全文件名、SHA、bundle 归档，最后才读旧绝对路径。当前来源重建走 `mesh_source_rebuild`，只恢复/替换一个 detail SQLite；`mesh_schema_rebuild` 是高级 Profile 全量重建，两者不能混用。
- API 来源摘要明确区分三个标识：`source_file_id` 是索引库 `source_files.id` 数字值，用于分析查询、重建和导出；`source_action_id` 是受控 raw tail/来源操作的安全 ID，可以是哈希值；`bundle_member_id` 仅用于 ZIP manifest 成员恢复。旧 `source_id` 仅作为等同 `source_action_id` 的兼容别名，新客户端不得将其转换为导出 ID。
- 同一 ZIP SHA 默认幂等。真实 12 文件包已在系统临时数据根验证：6 列车/12 MR、353,035 条解析记录、0 个解析问题；最终 353,033 条链路中 ACTIVE 129,524、STANDBY 223,509。重复导入同一 SHA 返回 12 个 duplicate，不重复写入；manifest 不含临时根/staging 路径，退出后无 staging/backup 残留。该结果证明当前样本闭环，不等同于所有 H3C 版本现场兼容。
- 2026-07-20 使用同一真实包复验统一入口与来源恢复：12/12 自动匹配，raw/parsed 各 12 份；移走一个 raw 后从 bundle 恢复并重解析 39,160 条，SHA 一致。宁波地铁 1 号线既有 06/34 四个 missing 来源使用现存 raw 原位修复为 ready，合计解析 189,468 条；未移动或删除 raw，也未重建同 MR 其他来源。

## 3. 解析模型

解析器按时间和 Radio 识别 ACTIVE/STANDBY/DOWN 等链路记录，规范化 MAC、RSSI、Tx/Rx Busy、链路计数、建立时间和持续时间。缺失指标写空值/N/A；RSSI 最小值、分位数或抖动只从真实有效样本计算，禁止用 0 或默认值补齐。

MR 端位资料与运行结论必须分离：`MR-CT` 固定为 `CT / 1车厢端`，`MR-CW` 固定为 `CW / 6车厢端`，二者都不是固定“车头/车尾”。行程分析接入后，当前运行角色只能由“实际运行方向 + `increasing_direction_leading_end` + `physical_end`”得到 `leading_end / trailing_end / turnback_transition / unknown`；RSSI 不得用于静默交换 CT/CW。届时切换信号模型使用 `LEADING_END_FAST_DROP`（行驶头端型快速衰减）和 `TRAILING_END_SMOOTH_CROSSOVER`（行驶尾端型平滑交叉）等代码，这些模型用于一致性验证而不是覆盖基础资料结论。

相邻同一物理 AP 的双 Radio 可按参数合并。默认参数：

| 参数 | 默认值 |
| --- | --- |
| 链路分析基准时间 `link_time_window` | 4000 ms |
| 切换阈值 `link_switch_threshold` | 10 RSSI |
| 维持链路阈值 `link_hold_rssi` | 22 RSSI |
| 发现链路阈值 `link_establish_threshold` | 4 RSSI |
| 建链信号阈值 | 26 RSSI（22 + 4） |
| 主链路切换基准 | 4000 ms |
| 短区段容差 | 500 ms |
| 乒乓临界容差 | 500 ms |
| 乒乓返回窗口 | 500 ms |
| 同物理 AP 双 Radio 合并 | 是 |
| 边界区段纳入异常 | 否 |
| PIS 返回窗口下限 | 10000 ms |
| 其他业务返回窗口下限 | 8000 ms |

返回窗口若未显式配置，取业务下限与 `3 × (切换基准 + 容差)` 的较大值。短区段阈值为 `max(切换基准 - 短区段容差, 0)`。

区段持续时间根据首末样本并结合采样间隔计算；跨大间隙不得硬连为连续区段。

## 4. 切换与乒乓

- 相邻主链路从 A 到 B 形成切换事件。
- A-B-A 且返回在窗口内形成 AP return/乒乓候选。
- 若 B 的驻留时间小于 `切换基准 - 容差`，判为异常乒乓；落在基准附近的临界区间单独标记；更长驻留为常规返回。
- 同一物理 AP 的 Radio 切换归类为 `same_ap_radio_switch`，不直接计为异常 AP 乒乓。
- 事件严重度必须附诊断原因和证据 ID，不只输出一个布尔值。

## 5. 质量规则

规则源为 `resources/mesh_quality_rules.json`。当前主要 profile：

| Profile | RSSI 优/良/警告/差 | Busy 警告/差 | 无备链 | 差链持续 | fping 丢包警告/差/严重 |
| --- | --- | --- | --- | --- | --- |
| `PIS_WIFI6_40_80_STANDARD` | 42/32/26/20 | 60/75 | 5 s | 3 s | 1%/3%/10% |
| `DCS_WIFI6_DOT11A_20_REMOTE` | 35/28/22/18 | 55/70 | 15 s | 5 s | 0.5%/2%/5% |

RSSI 数值按规则文件既定口径比较。两套 profile 当前 fping 平均延迟阈值为 50/100/200 ms，jitter 警告/差阈值为 20/50 ms。规则变更必须同时更新 JSON、规则加载测试、诊断说明和本文，不能只改 UI 标签。

## 6. 大数据与图表

- 页面按源文件解析到实际的 compact v3 tagged samples 明细库，直接读取版本化标量列；不在正式查询路径回退旧 JSON 指标列。
- 主链 RSSI/Busy 图按时间窗口和 Radio 查询，默认按请求目标点数降采样，硬上限为 2,000 点。服务端保留首尾、有效切换/异常/无 ACTIVE 断点和极值；有效切换锚点超过请求目标时自动提高本次有效点数，超过硬上限才按时间均匀抽样切换锚点。DTO 返回 `total_points/returned_points/downsampled`、请求/有效点数和必要的 `downsample_warning`。
- 轨旁信号图的业务语义是 Trackside Link RSSI（轨旁链路 RSSI）：每个采样帧同时展示真实 `ACTIVE` 主链和 `STANDBY` 备链在轨旁侧观测到的信号。结构化 `run_segment.rows` 是首选来源；旧结果仅在缺少结构化 STANDBY 行时使用真实 `standby_links_by_index/backups` 回退并按帧和物理身份去重，不从 ACTIVE 猜测备链。轨旁值优先读取 `peer_rssi_db`，缺失时回退 `peer_signal_dbm`，两者都缺失则跳过并计数，禁止使用 MR 侧字段代替。
- 轨旁物理序列身份依次使用 `peer_radio_mac`、`peer_ap_mac`、规范化 `peer_mac`、规范化 AP 名称，再与本地 Radio 组成 `series_key`。`ACTIVE/STANDBY` 是点属性；角色变化不拆图例、不换色、不开始新 run。来源、Radio、Peer Radio/物理身份变化、链路在有效采样帧中消失、连续性大间隙或明确日志缺口才开始新的链路存在区段，前端仅在新区段前插入空值断线。
- 轨旁接口的 `max_points` 表示目标采样时刻数，兼容字段 `requested_max_points/effective_max_points` 与新的 `requested_max_frames/effective_max_frames` 同值，不是链路点硬上限。后端先按 `(source_file_id, sample_time, timestamp_tag, local_radio)` 建帧，再选择首末、序列/区段边界、角色/主链切换、异常、缺口前后和区段 RSSI 极值等关键帧；一旦选中某帧，必须返回该帧全部有效主备链路。DTO 分别报告 frame、链路点、序列和链路存在区段数量，关键帧超过请求目标时提高有效 frame 预算，不截断整条 AP 序列或同帧链路。
- 单 AP 选择以正式建链顺序区段为边界；同一 AP 的全部经过时段可以合并显示，但 run 切换强制插入空值断线，不跨经过时段连线。
- 链路明细导出进入独立 Export Process，并以只读 Repository 打开 compact v3 派生库；导出阶段不得初始化 schema、写回解析结果或触发 WAL/checkpoint。
- ACTIVE/STANDBY 主链图 Tooltip 的备链按来源、采样时间、`timestamp_tag` 和 Radio 严格匹配；“MR / 轨旁 AP 接收信号”按业务展示要求只读取 compact v3 的 `local_rssi_db / peer_rssi_db` 差值，不得回退 `local_signal_dbm / peer_signal_dbm`。主链、备链和可选切换事件使用一个 Tooltip 与主题分隔线；原始 MESH 页面不展示不可靠的切换耗时和事件类型。图表切换事件仍携带前后 AP 与区段序号，点击可定位建链顺序。
- 切换节点由 Query Service 在估算采样间隔容差内映射到真实 ACTIVE RSSI，并作为强制锚点加入当前返回折线。红色节点只能使用同一返回点的 `timestamp/local_rssi`，不得用事件自带 RSSI 形成第二套坐标；未进入当前返回点集、缺失 RSSI、RSSI 为 `0` 或异常采样只保留事件事实，不绘制普通切换节点。轨旁图复用 ACTIVE 主链图 `chartData.events` 这一唯一事件事实源：节点按真实对齐时间、Radio、ACTIVE 角色和目标 AP/Peer 匹配轨旁缓存点，纵坐标只取 `peer_rssi` 或其 `peer_signal` 回退值；时刻线按 `render_point_timestamp -> point_timestamp -> event.timestamp` 保留真实毫秒坐标。上下图共用默认关闭的黄色时刻线开关和默认开启的红色节点开关，轨旁兼容字段 `events` 保持为空，不重复计算或传输事件。
- 站点/区间时间带由完整 ACTIVE 序列生成，按 `source_file_id + Radio` 分界，连续相同位置才合并；来源变化、Radio 变化、大时间间隙、未匹配位置和往返后的再次经过均拆成独立区段。
- 表格列偏好使用稳定表 ID，不包含 session、来源、MR 或局点；Electron 只通过白名单 UI preference Bridge 持久化，Renderer 不获得路径或任意文件能力。
- Rate 图直接读取 `mesh_links.local_rate_raw/peer_rate_raw` 并明确标注原始值，不猜单位。Retry/Error 图由 Python Query Service 使用同 source、Radio、session/peer 的采样顺序计算非负增量；首样本、缺值和计数器回退/重置返回空值，Vue 不重算。切换 RSSI 复用正式 `switch_events.before_rssi/after_rssi` 事件事实，只展示前后散点，不伪装为连续趋势。
- MR/源文件切换使用防抖、懒加载和 repository 缓存，避免重复解析和重复查询。
- RSSI 与空口负载使用独立响应和视口状态。全部 ACTIVE 主链 RSSI 与轨旁信号图由父级维护唯一的完整日志时间域、绝对毫秒 viewport、来源和 revision；完整时间域优先使用会话 `first_sample_time/last_sample_time`，两个图的 `xAxis.min/max` 和 `dataZoom startValue/endValue` 完全相同，不按各自采样点吸附。inside/slider dataZoom、轴最小间隔和共享 viewport helper 共同将最小可见范围限制为 1,000 ms；小于 1 秒的交互或程序化范围按真实毫秒中心扩展并在完整日志边界内平移，日志自身不足 1 秒时保持完整范围，不对采样或事件时间取整。轴标签显示到秒，Tooltip 和事件详情保留毫秒。用户缩放先静默纠正当前图，再只产生一次父级状态变更；镜像图以静默 `dispatchAction(dataZoom)` 应用相同 revision，不反向回写。重置、建链顺序、链路明细和切换定位统一更新该 viewport。两图还共享绝对 axis pointer 时间；上方主链图保持自身既有 Tooltip 规则，轨旁图只响应本图本地指针，来自另一图的共享指针仅保留参考线。
- RSSI 页使用 `ResizeObserver + getBoundingClientRect()` 按宿主元素真实顶部位置计算剩余视口高度，并提供“对比 / 主链 / 轨旁”三种布局。对比模式的页面标题、来源、日志摘要和工具栏自动进入紧凑状态，pane 内标题、告警摘要和统计标签固定为单行；告警完整文本通过 Popover 查看。工作区默认 50/50，Pointer Events 拖动以 RAF 合并，比例严格限制为 0.35～0.65；2K 可用工作区中每个 pane 至少 400px，较矮窗口至少 320px，图表组件自身 `min-height: 0`，空间不足只滚动工作区而不继续压缩曲线。专注模式以 `v-show` 保留另一图的数据、ECharts 实例、series cache、选择和 viewport；页面内“沉浸对比”只收起非必要顶部区域并保留左侧导航。恢复显示和拖动只执行 `resize()` 与静默共享 viewport 应用，不调用图表 API、不重建 series、不 dispose/init，也不修改共享时间域、pointer、切换标记和最小 1 秒视口。布局模式和合法分隔比例只通过白名单 UI preference Bridge 或浏览器 localStorage 保存，不进入业务数据库；旧的 0.25～0.75 偏好超出新范围时回退 0.5。
- 主窗口页面标签与组件缓存职责分离：标签 Store 以 route name 记录已打开页面，query/session 变化只更新同一个 `mesh-analysis` 标签；`AppRouteView` 只对路由声明的 KeepAlive 组件使用显式 include 白名单，普通页面即使保留标签也在离开时卸载。MESH 路由离开进入 `deactivated` 时只保存 `.app-main` 滚动位置、停止概览/任务轮询、断开轨旁 IntersectionObserver、清除瞬时共享 pointer 并将图表置为 inactive；不得 abort 已发出的只读图表请求、释放轨旁 cache、清空 payload、关闭固定 frame 或 dispose ECharts。点击仍打开的 MESH 标签返回后，等待 DOM 回插，刷新可用高度，对可见图表各执行一次 `resize()` 并静默应用原 viewport，再恢复滚动和轮询；不得调用 `openSession()`、重新加载已完成 RSSI 数据或重建颜色/cache。关闭 MESH 标签后从 include 白名单移除 `MeshAnalysisView`，触发真实 `onBeforeUnmount`，停止 timer/polling/Observer、dispose ECharts 和轨旁 series cache；再次从导航打开时创建全新实例。应用重启只能恢复轻量标签清单，内存图表按正常流程重新加载。
- 默认 MESH 页面使用稳定的 `singleton` 工作区身份和 `mesh-analysis` 组件缓存 key；`session_id` query 只表达待打开会话，不参与标签身份或 KeepAlive key。工作区命中已有 MESH 标签时先原子更新该标签的路由和身份再激活；页面在首次 mounted、query 变化和 KeepAlive activated 时统一消费会话意图。同一会话的重复点击复用进行中的请求且不重新加载，不同会话切换先 Abort 旧详情请求并按 generation 执行 last-wins，迟到响应不得更新详情、标签标题或轨旁缓存。进入新会话只加载基本详情和默认建链顺序，RSSI 与轨旁图继续按 Tab 懒加载。
- Online MR 主链图、离线 ACTIVE 主链图和轨旁信号图复用 `apps/web/src/components/charts/multiSeriesTimeChart.ts` 的 Canvas 初始化、图例、网格、坐标轴、dataZoom、toolbox、Tooltip 基础样式和大数据符号策略。共享初始化默认保留 Canvas `useDirtyRect=true`；离线 ACTIVE 主链 RSSI 与轨旁信号图因多层 overlay 和高频 axis pointer 显式使用 `useDirtyRect=false`，以完整重绘避免局部 Canvas 擦除。普通数据保留系统 DPR，5,000 点以上上限 1.5，20,000 点以上上限 1.0，图片导出仍使用 pixel ratio 2。Electron 不关闭 Chromium 硬件加速；开发模式只记录 `app.getGPUFeatureStatus()` 的 feature 状态，读取失败时继续软件渲染且不阻止启动。
- 轨旁 payload 使用 `shallowRef + markRaw`，到达时只遍历一次并建立非深度响应式缓存。ECharts 点固定为 `[timestampMillis, rssi, metaId, roleCode]`，不得携带完整 point、series、`seriesMeta` 或 `points`；Tooltip 必需的紧凑标量元数据、dataIndex 和 frame 索引保存在 ECharts 外部 Map。viewport、位置带、主题和 resize 复用同一紧凑 data，dataZoom 不执行完整 `setOption`，不再复制或排序全部 AP 序列。缓存构建时还按每条 series 的相邻有效点、`break_before`、run 身份和空 RSSI 生成真实渲染覆盖区间，再合并为全局有序区间。本地 pointer 精确命中已返回 frame 时直接使用该 frame；否则先二分确认其位于连续折线覆盖区间，再从有序 frame 时间中二分选择最近的真实 frame，等距时取前一帧。真实断线、范围外或无有效 entries 时隐藏 Tooltip，不显示空提示，不跨缺口吸附，不生成时间、不插值 RSSI，也不改变共享 pointer 原始时间。
- 轨旁 Tooltip 和固定 frame 详情都由 Vue 在 Canvas 外独立渲染。悬停框显示一次真实 frame 时间、分行的角色与 AP/Radio、轨旁/MR RSSI、站点/区间及有效 ACTIVE 持续时间；最大高度取图表可用高度与 640px 的较小值，同半区内固定在对侧上角，内容超高时内部滚动且滚轮不冒泡到图表。“固定查看”只复制当前 frame 的时间与紧凑 entries，右侧独立面板完整保留全部 ACTIVE/STANDBY 条目；指针、dataZoom 和布局变化不更新固定内容，离开 RSSI Tab 或更换缓存上下文才关闭。Tooltip、固定面板的打开、选择、滚动和关闭不得调用 `setOption`、`clear`、`resize`、cache rebuild、API 或 viewport 变更，来自上方主链图的共享指针只显示参考线而不打开轨旁 Tooltip。小数据下 ACTIVE 使用实心圆、STANDBY 使用空心圆；5,000 点以上仍关闭业务曲线 animation、symbol、emphasis 和每点 label，但切换信息始终只使用一个 scatter 数组和首条业务 series 上的一份 markLine，展示开关通过轻量 overlay `setOption` 更新，不重建缓存或业务 series。轨旁 series 颜色针对整个 payload 一次性建立同帧、相邻 frame、run 重叠和短间隔冲突图，再按冲突度、首次出现时间和 series ID 稳定贪心着色；扩展调色板至少 32 色，冲突节点不得使用相同颜色，同一物理 series 的角色和 run 变化不换色，viewport、pointer 和布局变化不重算。曲线、当前范围列表、已选 AP、Tooltip 和固定面板标记统一读取该颜色表，切换节点仍使用 danger 色。轨旁图默认关闭 ECharts 全量图例并释放其底部空间；点击真实点后只显示 AP 名称、AP MAC、Radio、稳定颜色标记和该点轨旁 RSSI，选择只更新 Vue 标量状态，不调用 ECharts `setOption/highlight` 或复制 data，避免 770-series Canvas 状态重绘。可选“当前范围 AP”列表按每条有序数字元组二分判断 viewport 交集，统一显示范围内最近一条有效值并明确标为“最新 RSSI”，不随 pointer 移动遍历数万点。Peer Radio MAC、Peer MAC、series/run/link 标识和数据来源只留在内部缓存、物理身份、去重和稳定颜色逻辑，不进入轨旁图例、选择条、范围列表、Tooltip 或固定面板。轨旁图接近可视区域时才初始化 ECharts，但数据请求仍提前完成，初始化后立即应用当前共享 viewport。
- 离线 MESH RSSI 图按设备日志和现有 DTO 的原始数值直接展示，纵轴统一标注 `RSSI`，主链与轨旁 Tooltip 不追加 `dBm`；显示层不得取负数、换算或修改 `local_rssi/peer_rssi` 等值，内部兼容字段名保持不变。
- 切换会话、来源、Radio 或重新请求轨旁数据时，前端先 Abort 旧请求、推进 generation、卸载旧图、清空外部 Map 和 payload 引用，下一次 tick 才安装新 payload；迟到响应不得重新挂回页面。组件卸载必须 dispose ECharts、解绑 ECharts/ZRender/Window/Resize 监听并取消 RAF/计时器。
- 每个 Renderer 同时处于加载或缓存状态的轨旁图最多两份，第 3 份请求必须在构建 cache/ECharts 前拒绝并提示先释放现有图表。会话切换和组件卸载按顺序释放 ECharts/Canvas、轨旁 series cache、颜色表及其冲突 Map/Set，并断开 metadata、frame、Tooltip 和选择状态引用；运行时同时统计 MESH 实例、活动详情请求、cache/chart 当前数与累计 build/dispose、series/point/metadata/conflict edge/Canvas/ECharts 数量。Electron 将该快照以 `MESH_MEMORY_PROFILE` 记录，并补充 `app.getAppMetrics()` 可获得的 Renderer private bytes 和 working set；当前 bridge 无法可靠取得 array buffer 时必须明确记录 unavailable，不得用 heap 或其他值代替。
- Peer、切换线、切换节点、位置带、主题和 resize 属于纯展示更新，必须保持当前视口。页面内锁定范围不持久化，切换会话、来源、Radio、ACTIVE/Peer 模式或 AP 经过区段时解除。
- `active-path` 和 `trackside-signal` 的 RSSI 请求始终读取当前 Radio 的完整日志范围；建链顺序、链路明细、切换定位和图表拖动只改变前端共享 viewport，不把该 viewport 作为 `time_from/time_to` 重新裁剪 RSSI API。锁定范围后的同期空口负载查询仍保留既有 `time_from/time_to` 语义。
- 固定规模转换回归由 `tracksideSeriesCache.test.ts` 覆盖 770 个主备混合序列、44,251 个返回链路点和 18,188 个 frame，并验证十次 cache 释放。真实 Chromium Canvas 的 API payload、浅层安装、cache/option 构建、首次 `setOption`、首次可交互、当前 frame Tooltip 100 次构建耗时、两批共 40 次纯 resize 布局切换、long task、heap、十次会话残留 heap、Renderer/GPU 退出和 GPU feature status 可在 `apps/desktop_electron` 运行 `pnpm run profile:mesh-chart` 复验；设置 `NETCONSOLE_MESH_PROFILE_SOFTWARE=1` 时只在画像进程中验证软件渲染。脚本默认使用上述真实规模和显式 GC，不访问现场日志或设备，正式应用不增加 V8 内存参数也不关闭硬件加速。
- 锁定 RSSI 后进入空口负载，必须使用相同来源、Radio、ACTIVE/Peer 模式、锚点、全部经过标记和 `time_from/time_to` 重新查询，不得只筛选前端降采样数组。响应分别报告 requested、effective、首末实际采样、范围内总点数和返回点数；无 Busy 样本时不扩大范围或伪造 `0`。
- 表格分页/按需读取，详情导出在独立进程中流式/分批查询完整数据；屏幕行数上限不能被误当成导出上限。

## 7. Excel 报表

正式报表走 Export Process，先写临时文件再原子替换。综合工作簿固定围绕：报告总览、分析参数与阈值、原始文件清单、数据质量总览、主链路建链顺序、主链路切换分析、全部 ACTIVE RSSI 分析、单 AP 分时段统计、空口负载分析、无备份链路风险、解析问题、原始证据。综合报告不再输出完整链路明细、全局 AP 聚合或 Peer 排名。

每个 `source_file_id`/原始日志独立生成和追溯报告，不得把不同日志拼成一份无法定位来源的结论。报告面向业主、项目经理和普通维护人员：总览先用可读语言说明有效数据、主要异常、影响范围和建议，再提供算法字段与证据表。AP 明细与问题 AP 必须尽可能带发生时间、归属站点、区间、MAC、里程和来源；缺失时明确“未解析”，不能猜测。WiFi 4/5/6、旧日志和只有 Peer MAC 的兼容结论只按实际 parser/fixture 覆盖范围声明。

报告只能读取当前来源的真实 raw、派生库和参数快照。示例、空模板或随机数据不得冒充现场分析；数据不足时生成“证据不足/无法判断”的真实结论或拒绝生成，而不是补造样本。

“分析参数与阈值”逐项记录最终有效值、单位、业务含义、来源和四级候选。优先级固定为：报告临时覆盖 > 来源快照 > 局点配置 > 全局默认；布尔值显示“是/否”，未配置值显示“未配置”，不得只写一段 JSON。链路明细导出额外写入“分析参数”Sheet，使用与综合报告相同的最终快照。

宽列、原始行、诊断和建议使用受控列宽与换行，兼顾 Microsoft Excel/WPS。目标文件被占用时给出可操作提示；取消或失败不得保留伪完整 workbook。

独立“导出链路明细”使用 `mesh_link_detail_export`，创建“链路明细”“主链路明细”和“分析参数”三个工作表。链路明细分批读取完整来源数据，主链路明细直接复用 `query_active_link_build_order`，不得按当前页面分页截断或在导出器重算建链结果。

报告与导出列表可以删除派生 `outputs` 中的报告、sidecar 和临时文件，但必须显式确认；原始导入日志、raw、parsed SQLite、catalog 永远保留。

## 8. 验证清单

- UTF-8、GB18030/GBK 输入与 gzip/普通日志；
- 缺 Peer Name、未知 MAC、重复样本、乱序、跨大间隙和截断日志；
- 单/双 Radio、同物理 AP 切换、A-B-A 临界与异常乒乓；
- 缺失 RSSI/Busy 时不伪造统计；
- 目录库到 `parsed_db_path` 的正确解析；
- compact v3 `timestamp_tag` 唯一键、同毫秒多块顺序和旧派生 schema 显式重建；
- ZIP 路径/压缩安全、预览 TTL、人工映射、隔离提交补偿、manifest 时机、SHA 幂等和绝对路径脱敏；
- Rate 原始值、Retry/Error 回退空值、切换前后 RSSI 事件散点以及图表卸载资源释放；
- 可见窗口、全量下采样、切换锚点保留、请求点数自动提升、安全上限抽样告警和重复加载防抖；
- 大表导出取消、WPS/Excel 占用、临时文件清理和源证据回溯。
