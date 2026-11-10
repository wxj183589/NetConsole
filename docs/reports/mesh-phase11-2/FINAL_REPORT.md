# Mesh Phase 11.2 最终实现与验收报告

日期：2026-11-09。基线ec174410dc3b491bcb3d3a29fc8df25012fee8f6；分支codex-A/mesh-analysis-scope-ui-optimization。本次与Phase11.3/11.4统一本地提交，按最新任务书不Push、不Merge、不Release。

## 已实现

- 共享NcColumnSettings与NcDataTable使用草稿，显隐/排序/固定/重置/适应列宽在应用时一次落盘与布局，取消不持久化。已有行足以展示列时不发业务查询。
- MESH链路明细、建立顺序、切换事件和业务Excel使用中文业务字段；不删除底层追溯数据，不改保存协调器和Export Worker。
- 主链路十二个图表覆盖本端/对端RSSI、CPU、内存、TxBusy、RxBusy、Rate、Noise、描述符空闲数、Tx/Rx、Retry、Err、GARP/MulJoin。
- 累计计数器在后端降采样前计算current/previous/delta/interval_seconds/per_second/status。真实毫秒时间差，缺失和断点保持null，不以累计或delta冒充每秒速率。
- ACTIVE最近点按窗口、Radio和AP条件定位；先读前后各一个候选，再读取有界身份上下文，避免为每次鼠标移动全量取历史。筛选后的counter仍检查真实角色与切换上下文。
- 图表按可见区域及240px预加载边界查询；同源busy/counter请求去重，成功数据缓存复用。图表和源缓存各限16项。只有真实finished才完成，错误和重试独立。

## 风险与消费者

L3：共享表格偏好和可选API元数据。偏好写入/读取/缓存/展示复用现有tablePreferences；消费者涉及设备、AC/FIT-AP、轨旁AP、MESH、Online MR、Ground、任务、配置、文件和网络表格。完整Renderer覆盖这些消费者。旧字段保留，新counter_samples默认空，不迁移SQLite schema，不改旧导出默认语义。无新worktree、无覆盖其他任务修改；未Merge，main组合门禁未执行。

## 自动验证

- 完整Renderer：206文件、1505/1505通过；2026-11-09 17:28:44开始，40.20秒。
- vue-tsc -b与Vite build通过；独立vue-tsc --noEmit通过。存在大于500kB chunk提示。
- 表格定向：3文件20项；主页面导航/缓存/刷新：3文件72项；最终图表/Tooltip/Workbench/指标：4文件82项，均通过。
- 后端组合141项通过；最后采样与nearest边界25项通过。后续文档guard与最终静态结果见本报告的收尾记录。
- 真实DB/raw只读三点：12counter全部元数据与独立手算一致，指纹不变；见REAL_DATA_VALIDATION.md及JSON。不能代替HTTP API或Electron验收。

## 未完成

当前源码真实Electron的1920×1080、原生DPI截图与交互未验收。原runtime退出，PowerShell Start-Process启动操作被自动审批拒绝，仅返回blocked by policy，无更具体原因；未换方式绕过。13类截图未提供，未用静态HTML或旧图代替。单AP/时间/Radio切换等真实GUI端到端仍待。

数据影响：仅源码、测试和报告；真实开发DB/raw以mode=ro与query_only读取，无完整数据复制、无Production和设备写入、无schema迁移。结论为PARTIAL / ELECTRON_UI_BLOCKED。

## 最终收尾记录

- 当前Service直接只读验证通过：三个nearest目标与普通counter查询及独立计算的12字段全部一致，窄窗口4条记录2.50ms。末尾五分钟465条→240条，首次2190.47ms、重复2306.04ms；首次raw零链路扫描影响其中一次nearest耗时至690.73ms。数据库与raw指纹不变。证据real-service-query-validation.json。
- 文档布局13/13、修改范围Ruff、Workspace布局及git diff --check通过。用户明确指定的四份审查报告精确登记，其他路径仍受guard约束。
- 架构12项中11项通过，device-command-hardcoding将基础HEAD已有docstring的display formatting or unit conversion当作设备命令。基础HEAD与当前文本已对照一致；该项保持FAIL，未放宽规则或修改无关文档串。
- 本轮没有执行完整Python、Electron测试套件、安装包/发布或main合并后门禁；完整Renderer已按共享表格消费者要求执行。
