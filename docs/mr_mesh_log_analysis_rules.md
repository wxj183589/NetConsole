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
- 切换节点由 Query Service 在估算采样间隔容差内映射到真实 ACTIVE RSSI，并作为强制锚点加入当前返回折线。红色节点只能使用同一返回点的 `timestamp/local_rssi`，不得用事件自带 RSSI 形成第二套坐标；未进入当前返回点集、缺失 RSSI、RSSI 为 `0` 或异常采样只保留事件事实，不绘制普通切换节点。黄色切换时刻线仍按事件时间显示，默认关闭，与默认开启的真实切换节点互不依赖。
- 站点/区间时间带由完整 ACTIVE 序列生成，按 `source_file_id + Radio` 分界，连续相同位置才合并；来源变化、Radio 变化、大时间间隙、未匹配位置和往返后的再次经过均拆成独立区段。
- 表格列偏好使用稳定表 ID，不包含 session、来源、MR 或局点；Electron 只通过白名单 UI preference Bridge 持久化，Renderer 不获得路径或任意文件能力。
- Rate 图直接读取 `mesh_links.local_rate_raw/peer_rate_raw` 并明确标注原始值，不猜单位。Retry/Error 图由 Python Query Service 使用同 source、Radio、session/peer 的采样顺序计算非负增量；首样本、缺值和计数器回退/重置返回空值，Vue 不重算。切换 RSSI 复用正式 `switch_events.before_rssi/after_rssi` 事件事实，只展示前后散点，不伪装为连续趋势。
- MR/源文件切换使用防抖、懒加载和 repository 缓存，避免重复解析和重复查询。
- RSSI 与空口负载使用独立响应和视口状态。全部 ACTIVE 主链 RSSI 与轨旁信号图由父级维护唯一的完整日志时间域、绝对毫秒 viewport、来源和 revision；完整时间域优先使用会话 `first_sample_time/last_sample_time`，两个图的 `xAxis.min/max` 和 `dataZoom startValue/endValue` 完全相同，不按各自采样点吸附。用户缩放只产生一次父级状态变更，镜像图以静默 `dispatchAction(dataZoom)` 应用相同 revision，不反向回写；重置、建链顺序、链路明细和切换定位统一更新该 viewport。两图还共享绝对 axis pointer 时间；当前时刻没有本图采样时明确显示无有效采样，不跳到另一采样时刻。
- Online MR 主链图、离线 ACTIVE 主链图和轨旁信号图复用 `apps/web/src/components/charts/multiSeriesTimeChart.ts` 的 Canvas 初始化、图例、网格、坐标轴、dataZoom、toolbox、Tooltip 基础样式和大数据符号策略。ECharts 显式使用 Canvas `useDirtyRect`；普通数据保留系统 DPR，5,000 点以上上限 1.5，20,000 点以上上限 1.0，图片导出仍使用 pixel ratio 2。Electron 不关闭 Chromium 硬件加速；开发模式只记录 `app.getGPUFeatureStatus()` 的 feature 状态，读取失败时继续软件渲染且不阻止启动。
- 轨旁 payload 到达时只校验一次序列顺序并建立非深度响应式缓存；viewport、位置带、主题和 resize 复用原 series data，dataZoom 不执行完整 `setOption`，不再重复复制或排序全部 AP 序列。小数据下 ACTIVE 使用实心圆、STANDBY 使用空心圆；5,000 点以上关闭 animation、symbol、emphasis、每点 label、切换 scatter 和大量 markLine。轨旁图接近可视区域时才初始化 ECharts，但数据请求仍提前完成，初始化后立即应用当前共享 viewport。系列颜色使用 Peer Radio MAC、AP MAC、Peer MAC、序列身份与 Radio 的稳定优先级计算，不含点角色。
- Peer、切换线、切换节点、位置带、主题和 resize 属于纯展示更新，必须保持当前视口。页面内锁定范围不持久化，切换会话、来源、Radio、ACTIVE/Peer 模式或 AP 经过区段时解除。
- `active-path` 和 `trackside-signal` 的 RSSI 请求始终读取当前 Radio 的完整日志范围；建链顺序、链路明细、切换定位和图表拖动只改变前端共享 viewport，不把该 viewport 作为 `time_from/time_to` 重新裁剪 RSSI API。锁定范围后的同期空口负载查询仍保留既有 `time_from/time_to` 语义。
- 固定规模转换回归由 `tracksideSeriesPerformance.test.ts` 覆盖 140 个主备混合序列、14,581 个链路点和 6,264 个链路存在区段；真实 Chromium Canvas 的 option 构建、首次 `setOption`、首次可交互、dataZoom、resize、主题更新、long task、heap 和 GPU feature status 可在 `apps/desktop_electron` 运行 `pnpm run profile:mesh-chart` 复验。需要复验更大真实统计量级时，可仅为该命令设置 `NETCONSOLE_MESH_PROFILE_SERIES_COUNT` 与 `NETCONSOLE_MESH_PROFILE_POINT_COUNT`；默认基线不变。该 smoke 使用隐藏窗口和脱敏合成序列，不访问现场日志或设备。
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
