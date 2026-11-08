# 地面无人值守 V2 效果图差距审计

日期：2026-11-07。基线：`8dfe8d7d`，分支 `codex-A/ground-unattended-v2-20261107`，PR #105。

## 图片与现场证据

逐张查看了 `D:/下载/` 中的六张目标图：`无人值守，心跳检测.png`、`无人值守，心跳检测1.png`、`02AC-Mesh-Link 效果图.png`、`03 快ping.png`、`04 syslog.png`、`05深度采集e.png`。图中的数字和地址只代表目标布局。

在 Downloads 和附件目录未找到 `image(20261107-065338).png`、`image(20261107-065409).png`。因此当前实现依据本分支源码与后续实际运行截图复核；不宣称已对照这两张缺失图片。浏览器合成 Fixture、真实后端测试与真实设备验收分别记录。

## 页面对照

| 页面 | 基线实现与主要差距 | 目标结构及修改组件 | 数据来源 | 验收标准 |
| --- | --- | --- | --- | --- |
| 心跳主页面 | 五张统计卡；仅有运行快照才出现列表；MR 名称弱化；无同步预览/独立清理，缺少端别筛选 | `HeartbeatPage.vue`：六统计、紧凑工具栏、CT/CW 双卡车辆组、空端提示、同步预览与清理确认 | 设备管理经基础资料 Query 的稳定 MR UUID；Ground inventory、心跳快照；AC 仅辅助身份/位置 | 未探测为 UNKNOWN；统计来自服务端；缺端明确；组合筛选；同步不启动探测、不丢历史；清理不删资产/其他模块 |
| 心跳详情 | 已有综合监控、Ping、丢包、Peer、Mesh 证据抽屉；主卡缺少最近探测与身份信息 | `MrMonitoringDrawer.vue` 与主卡：保留覆盖式抽屉，增强 MR 身份和车辆上下文、空状态 | Ground monitoring、真实 Ping series、WMESH/AC 证据及时间戳 | 无历史显示空；不造曲线；打开抽屉不启动任务；关闭释放轮询/图表 |
| AC-Mesh-Link | 六统计、四视图、MR 按车组；关系图固定 viewBox + max-height，长图整体缩小且页面滚动代替平移 | `AcMeshLinkPage.vue`、轻量 SVG 画布组件：填满主体、连续鼠标中心缩放、拖动、适配/重置/全屏、选中高亮 | 现有 AC mesh query 的当前页 MR/Peer 与真实关系；独立标记过期关系 | 无新增图形框架；坐标变换同时作用节点/连线；自动刷新不复位视图；点击节点详情可用；明确页范围 |
| 快速 Ping | 已有多 MR/多 IP、占用互斥、参数和历史；选择区/参数区层次不够集中 | `QuickPingPage.vue`：上方 MR 多选/端别/主备地址、参数、已选标签；下方任务历史与详情 | Ground train endpoints、quick-ping runs/target runtime/statistics | 保持 IP 互斥和执行机制；任务统计缺失显示空；选择不重复；长标签可读；历史列可扫读 |
| Syslog | 已有六统计、多条件筛选、列设置分页、原始及解析详情；筛选和诊断条较松散 | `SyslogPage.vue`、领域 CSS：两层筛选、压缩统计和操作条、密集表格与覆盖详情 | 所选 run 索引统计、syslog-records、raw 片段及解析结果 | 不隐藏数据来源/截断/失败；筛选及列设置可用；原始日志可读；不同宽度无页面横溢 |
| 深度采集 | 已有主任务、独立采集项目/日志/文件/参数抽屉；统计、任务信息和进度层次需要收紧 | `DeepTasksPage.vue`、领域 CSS：统计/筛选/操作/表格分区，右侧多子项独立进度 | 现有 deep-tasks 与 records API；每 MR/AP 主任务和实际 item 状态 | 保留多子项目；持续采样不伪造完成百分比；主子状态独立；日志/文件/参数可见；不改引擎 |

## 统一视觉检查

第一轮检查布局、可用高度、车辆分组、表格密度、抽屉覆盖与画布占用；第二轮检查字号、间距、状态色、溢出、按钮反馈与键盘操作。覆盖 1920×1080、2048×1100、1440×900，并单列浏览器 125% 仿真；原生 Windows DPI 不能由 deviceScaleFactor 代替。

## Consumer Audit

风险为 **L4**（删除操作、领域 schema/Feature 动作）；不是调度或通用共享组件重构。

| 契约 | 写入/读取/缓存/展示 | 兼容与回归 |
| --- | --- | --- |
| Ground inventory | 设备管理/基础资料写资产；Inventory Service 差异写 Ground；Supervisor、Syslog、深采、Quick Ping 读取 | 心跳清空不得删除共享库存；不写设备资产；重复 UUID/端位返回冲突，不能挑第一条 |
| 心跳控制/状态 | Site 级控制独立保存；现有资格配置读取；心跳 API/抽屉展示 | 默认兼容旧库存；清空后保持显式停用，只有生成操作恢复；运行中清理阻断；不改 Worker/锁/并发 |
| 心跳 API/DTO | Application Service 聚合，Router 薄适配，Renderer 自有 Abort/generation 轮询 | 新字段默认值兼容旧客户端；无快照 UNKNOWN；历史请求不得回灌当前资产状态；增加 API/同步/清理安全测试 |
| 画布 | 当前页 query 提供数据；组件只维护坐标与选中态 | 真实关系、明确分页；刷新保留变换；resize/listener/unmount 成对释放；交互/规模/截图测试 |
| Feature/i18n | Registry 是可见操作事实源；页面能力判断；本地化字典 | Full/Customer、Feature contract、API guard、Renderer 及 Electron 回归 |

基线只有一个 Git Worktree，工作树 clean；已结束的历史并发任务不再修改本轮文件。后端与后续前端按文件所有权隔离，公共 DTO 先固定再接 UI。未修改导出契约、设备命令、DataRoot 或退役 HistoryStore。

最低回归：Ground Python/API/同步/清理/现有并发专项；Renderer 全套/typecheck/build；Electron contract；architecture、main smoke、docs/path/diff、Feature consumers 与完整 Python 门禁。禁止合并 PR，因而 main 集成后复验仍待实际集成时运行。

Phase 0：旧提交保留，PR #105 OPEN，旧 HEAD 的八项 GitHub 门禁均 SUCCESS（run `42314141149`）。DevStatus 有无关 Next 并行本地提交，不能随本任务误推。
