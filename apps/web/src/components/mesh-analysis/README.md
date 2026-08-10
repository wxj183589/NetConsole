# Mesh 分析组件

本目录承载 Mesh 离线分析的图表组件，负责把已查询的序列数据呈现为 RSSI 等趋势，不在组件内解析原始日志或计算业务结论。

主要入口为 `MeshRssiChart.vue`、`MeshTracksideSignalChart.vue` 和 `MeshChannelBusyChart.vue`；它们通过 `meshChartViewport.ts` 共享毫秒时间视口契约。双图布局已下沉到相邻的 `../rail-timeline/RailRssiComparison.vue`，公共游标、选择时刻和两类锁状态由 `../rail-timeline/railTimeline.ts` 管理。MESH 和 Online MR 复用该框架，但公共层不依赖任一业务 API；数据语义仍由各自 Adapter/ViewModel 决定。主题来自统一 ECharts 配置。修改图表字段或语义时运行对应测试并检查空数据、单位、共享 DataZoom、游标和 selectedTime。

## 页面与报告口径

- 主链路建链顺序由 `MeshLinkAnalyzer` 经 `MeshMrRepository.query_active_link_build_order` 生成，页面 API、综合报告和链路明细导出不得各自重算区段、短时建链或乒乓结论。
- 链路明细由 `MeshMrRepository.iter_link_details` 读取 compact v3 标量列；`timestamp_tag` 是采样身份的一部分，报告不得合并同毫秒的不同采样块。
- 图表和 Tooltip 只消费解析事实层已接受的正数 `LinkCnt` 链路。`LinkCnt=0` 驱动占位行不进入 ACTIVE/STANDBY、RSSI、gap 或图表 payload；`LinkCnt=2` 保留正常曲线并以非故障 `△ 三角链路` 点标记，`>2` 同样保留原始值；仅无法解析或负数 `LinkCnt` 由解析器 diagnostic 后拒绝，组件不能以 `RSSI=0` 作补救判断。
- 全部 ACTIVE RSSI 和空口负载复用 `mesh_chart_payload` 的唯一 ACTIVE 路径结果。RSSI 图固定为 MR/Peer 两条序列，空口负载图固定为 MR 侧 TxBusy/RxBusy 两条序列，不按 AP 数量扩增图例，也不伪造 CtlBusy。
- 轨旁AP信号图独立采用 Trackside Link RSSI 语义：每个 frame 同时接收 ACTIVE 与 STANDBY 原始角色快照，RSSI 缺失也保留该角色并以 `null` 断线；序列按内部 Peer Radio/AP/Peer + 本地 Radio 身份保持稳定，角色只属于点。角色切换不拆序列或断线，链路消失后重现才开启新区段；Tooltip 通过外部 frame 索引显示同帧全部主备链路，并按 ACTIVE、STANDBY、AP/MAC 排序，同角色同 AP 的意外 gap/有效重复优先有效采样。底部全量图例默认关闭；点击点和当前范围列表只公开 AP 名称、AP MAC、Radio 与原始轨旁 RSSI，不公开内部 Peer/series/run/link 身份。
- 页面与报告通过 `MeshApLocationSnapshot` 共享 AP 名称、MAC、站点、区间、里程和线路方向解析；Export Job 只携带该快照的受控字符串字段。Excel 工作表保留完整业务数据，嵌入图表使用关键点和极值降采样，空 ACTIVE 不创建空图。
- 正式报告继续由 Export Process 生成：Worker 写临时文件，完成后原子替换目标 Artifact；Renderer 不读取全量链路，也不生成 Excel。
- 图表请求按 Radio/时间窗口使用 generation 防止迟到响应串回旧会话；单 AP 支持单次经过和全部经过时段，后者以 `gap_before` 强制断线。
- RSSI `0` 在后端按自然秒分类：同一自然秒内的一条或多条 0 属于无有效 RSSI，连续覆盖多个自然秒为持续无有效 RSSI；此规则只适用于正数 `LinkCnt` 的有效链路。图表保留这些角色快照和状态元数据，但展示值一律为 `null`，不绘制或合成 `0` 端点。恢复时刻仅归属新有效样本，缺口采用 `[start, end)`，降采样仍固定保留恢复点和关键边界。主用链路信号只跳过前后均为唯一有效 ACTIVE、且没有真实缺口的单个 `MULTI_ACTIVE` 歧义帧；`NO_ACTIVE`、连续歧义和真实缺口仍断线。
- 图表的 data/display/theme/resize/viewport/reset 更新分开处理：切换时刻线、切换节点、站点区间带属于 display，仅以已在内存中的 `events`、位置区段和 series 调用 `setOption`，不得触发主链或轨旁 RSSI 请求、清空缓存或进入 loading；显示 Peer 首次需要 Peer 曲线时只请求主链数据，之后仅显隐既有 series。所有 display、主题和容器尺寸变化都保留真实毫秒视口，不把 `dataZoom` 重置到全日志。主链保留点随 `backups` 携带同采样上下文的全部 STANDBY 链路，主图 Tooltip 与轨旁图共享这份事实口径，曲线降采样不得丢失其上下文。主用链路信号与轨旁AP信号图由父级提供同一个会话绝对时间域和带来源/revision 的 viewport，不按各自采样点吸附；程序化镜像更新使用静默 `dispatchAction`，组件通过 `getViewport/applyViewport/resetViewport/getVisibleTimeRange` 暴露同一契约。
- RSSI 工作区以宿主元素的真实顶部位置计算剩余视口高度。对比模式默认 50/50，分隔比例限制为 35%～65%；2K 可用空间下每个 pane 至少 400px，较矮窗口至少 320px，不足时只滚动工作区。标题、告警和统计保持单行，图表组件自身不再声明固定最小高度。页面内“沉浸对比”仅收起非必要顶部区域，左侧导航、共享 viewport、缓存和两个 ECharts 实例保持不变；布局与分隔拖动只 resize。
- 共享二维时间序列内核位于 `apps/web/src/components/charts/multiSeriesTimeChart.ts`。Online MR、离线主用链路信号与轨旁AP信号图统一 Canvas `useDirtyRect`、DPR 上限、图例/网格/dataZoom/toolbox/Tooltip 基础样式；轨旁大 payload 使用 `shallowRef + markRaw`，ECharts 点固定为 `[timestampMillis, rssi, metaId, roleCode]`，业务元数据只保存在外部 Map，不允许点引用完整 `meta`、`seriesMeta` 或原始 `points`。视口、位置带、主题和 resize 不重复排序或复制数万点。小数据用实心/空心圆区分主备点，大数据隐藏普通 symbol；不得为角色生成额外曲线或 scatter，唯一例外是复用原点元数据的 `LinkCnt=2` 非故障三角拓扑 overlay。
- 切换会话、来源、Radio 或重新请求前必须取消旧请求、拒绝迟到 generation、卸载旧图并清空 cache Map；组件卸载同时解除 ECharts、ZRender、Resize/Window 监听和计时器。父级在每个轨旁渲染阶段最多上报一次严格 workload 快照，禁止在 dataZoom 中高频上报。
- “锁定当前时间范围”只保存在当前页面运行期；切换会话、来源、Radio、ACTIVE/Peer 模式或 AP 经过区段时解除。锁定后查询空口负载会携带同一来源、Radio、模式、锚点、全部经过标记及 `time_from/time_to` 重新请求后端，RSSI 与 Busy 使用独立响应和视口状态。
- 图表 API 同时返回 requested、effective、首末实际采样、范围内总点数和返回点数。requested 是用户锁定边界，effective/first/last 是范围内真实样本边界；范围内没有 Busy 时显示明确空状态，不扩大范围、不补 `0`。
- 切换事件由 Query Service 按估算采样间隔映射到真实 ACTIVE 点；无有效采样间隔时只接受精确时间，找不到真实 RSSI 时不绘制节点。切换时刻线与切换节点分别控制，默认关闭时刻线、开启节点。
- RSSI 与空口负载直接消费 Query Service 生成的连续位置区段；区段按来源、Radio、时间间隙和站点/区间边界拆分，同一站点的多次经过不会跨时间合并。
- MESH 表格使用不含 session/source/MR/site 的稳定 ID。Browser 使用 `localStorage`，Electron 通过白名单 Bridge 写入当前 `userData` 下的受控 UI 偏好文件；恢复默认只清理当前表。
- 链路明细通过独立 `mesh_link_detail_export` Export Job 输出“链路明细”“主链路明细”“分析参数”三张工作表；综合报告不承载全量链路明细或全局 AP/Peer 聚合。
- 报告和链路明细导出使用同一分析参数快照（本次覆盖 > 来源快照 > 局点默认 > 系统默认），参数写入“分析参数”Sheet，并可由页面保存为当前局点默认。
- 报告列表中的删除只允许派生 `outputs` 文件；原始 raw、parsed SQLite 和 catalog 不可删除。删除由 Application Service 做路径白名单复验，前端只提交 opaque `artifact_id`。
