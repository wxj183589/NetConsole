# NetConsole 项目规则索引与高频约定

本文保留旧 `08` 规则入口，但当前活动规则不再来自历史 Qt 文档。开发时以仓库根 `AGENTS.md`、[开发规则](DEVELOPMENT_RULES.md)、[仓库目录规范](development/repository-layout.md)和对应专题文档为准；旧 Qt/QThread/QWidget 规则只作为[Qt -> Electron 历史归档](archive/migrations/qt-to-electron/README.md)追溯材料。

## 事实来源顺序

判断状态或写文档时按以下顺序取证：

1. 当前生产代码、Feature Registry、PathResolver 和构建脚本。
2. 当前测试、架构 Guard、发布脚本和 fixture。
3. 当前专题文档、README、迁移矩阵和归档报告。
4. Git 历史和历史规划。

版本只读取 `src/netconsole/core/version.py`；用户可见功能只读取 `src/netconsole/core/feature_registry.py`；数据路径只读取 `src/netconsole/core/paths.py`。文档中的源码路径使用 `src/netconsole/...`，Python import 语境才写 `netconsole.*`。

## 活动架构边界

- 正式桌面产品只有 Electron Main + Preload + Vue + FastAPI/Python Core；Qt/PySide6/QFluentWidgets 源码、运行时、依赖、测试 fixture、启动探测和回退入口不得重新引入。
- `main.py` 无参数是源码态 Electron Desktop 入口；`--mode web|server` 只用于本机开发诊断，不代表第二套产品运行时。
- Vue 负责布局、输入、表格、图表和显示格式化；Electron 负责窗口、受控生命周期和白名单 Native Bridge；FastAPI Router 只做鉴权、DTO、Application Service 调用和响应映射。
- 设备命令、SSH/Telnet/SNMP、SQLite、Parser、导出、压缩、采集状态机、AP 匹配和轨交业务规则只能放在 Python Core 的 Application/Domain/Repository/Parser/Adapter 边界内。
- 超过 300ms 的 IO、CPU、网络、解析、压缩、大查询和批量任务进入 Job Center；所有正式导出进入独立 Export Process。

## 仓库与运行数据

- 业务代码进入 `src/netconsole`；Electron、Web、Agent 分别进入 `apps/desktop_electron`、`apps/web`、`apps/agent`。不得新增 `apps/desktop`、`src/netconsole/ui`、`frontend`、`desktop`、`netconsole`、`project` 等历史或模糊目录。
- 根目录只保留项目级配置、入口和白名单目录；运行数据、日志、SQLite、抓包、采集结果、临时导出和正式报告不得提交。
- 路径定位使用 `PathResolver`、资源 helper 或脚本自身位置；禁止用 `Path.cwd()` 定位源码、资源、配置或运行数据，禁止用临时 `sys.path` 掩盖包结构问题。
- 源码开发、Electron 开发、Python Backend、打包验证和正式安装包默认都读取安装器登记的 `HKLM\Software\NetConsole\DataRoot`；`NETCONSOLE_DATA_ROOT` 只作为显式覆盖，未配置持久根时停止启动，不回退到 LocalAppData、用户目录、仓库、安装目录或系统 Temp。
- 自动测试、发布 smoke 和安装包 smoke 必须显式使用 `RuntimeMode.TEST` 与唯一 `D:\NetConsoleTestData\<run-id>`，不得读取机器级指针、正式局点数据库、真实会话或报告；结束时只清理自己的 run-id。
- 历史数据迁移和清理必须 dry-run、manifest、白名单、SHA-256 和 SQLite `quick_check/integrity_check`；同路径异内容进入 `migrations/conflicts/`，不得静默覆盖或删除用户数据库、原始日志、会话或正式报告。
- 新增目录、移动文件或调整 Agent/工具/构建路径时，同步检查 import、测试、构建参数、前端工作目录、Agent 入口、文档链接和资源定位。

## 安装器、局点与数据包

- NSIS 安装器必须先在零写入状态下分类候选数据根，再执行候选根内部唯一临时文件的写入、flush/close、同目录重命名、回读和清理探测；探测成功后不得再按“普通目录非空”拒绝。
- 数据根页面允许不存在路径、空目录、合法旧根和含无冲突普通文件的目录；不得自动拼接 `NetConsoleData` 子目录，不得重命名数据根、跨卷移动、覆盖 manifest 或读取/修改现有数据库与采集文件。
- 写入注册表指针前必须由打包 Backend 原子初始化标准目录和 `config/storage-manifest.json`，或验证既有 manifest 兼容；损坏、根不一致或版本不兼容时安装失败且原文件保留。
- 局点 Registry 的稳定 `site_id` 和跨电脑 `site_uuid` 是同步事实源，显示名称只用于展示；导入、回传和合并不得按显示名称或本地自增 ID 覆盖数据。
- v4 `full_migration` 是不加密普通 ZIP，无需迁移密码，直接包含局点数据库及设备 SSH/Telnet 密码、SNMP community 和隧道凭据；只保存到可信位置。脱敏分享、现场采集、采集回传和旧无凭据包必须清除秘密并标记需要重录。
- `collection_return` 只在匹配同一 `site_uuid` 后按稳定 UUID、任务/事件 ID、文件 SHA-256 和预检冲突策略合并；删除请求默认只记录和展示，不自动删除设备、AP、列车、原始文件、报告或历史数据。
- 托盘“快速切换局点”只把目标 `site_id` 意图交回设置页，必须复用局点切换 preflight、活动任务阻塞、工作区快照、Backend 重启和回滚流程；Electron Main 不接受 Renderer 提供的局点名称或清单。

## 功能、UI 与表格

- 新用户可见模块、页面、Tab、动作或按钮必须进入 Feature Registry；页面通过 FeatureGate/配置控制可见性，Feature 状态不替代后端鉴权和安全校验。
- 用户可见文本进入 i18n；凭据、Token、community、私钥、设备密码和未脱敏身份样本不得进入 API 响应、任务结果、localStorage 或普通日志。
- 新表格默认使用 `NcDataTable + NcTableColumn`，缺失值显示为 `—`，事实零值保留 `0`。不得新建直接 `el-table` 页面；新增或迁移表格要同步更新 `docs/ui/TABLE_INVENTORY.md` 并补定向测试。
- 表格列宽由公共组件按表头、抽样内容、图标/Tag/按钮 chrome 和可视区二阶段计算；容器不足时横向滚动，不压缩表头，不用字符串长度乘固定像素。
- 状态色、主题、侧栏、Element Plus 和 ECharts 使用 Design Token；自动测试不能替代 Electron 多尺寸、多缩放、浅色/深色/跟随系统的视觉验收。

## 任务、Artifact 与 Native Bridge

- 任务 DTO 和结果不得泄露本机绝对路径、任务秘密、设备凭据或后端 Token。任务窗口只接受受控 `taskId/module/status`。
- Electron Native Bridge 只允许白名单动作：选择文件/目录/保存路径、下载受控 Artifact、打开临时 capability、外链 HTTPS、设置页工具选择和受控设置动作；不得提供通用命令、任意路径、任意 URL/Header、完整 `ipcRenderer` 或 shell 参数。
- Renderer 不能自行打开本机路径。Artifact 下载由 Electron Main 注入内存令牌、流式写入 `.part`、成功后原子替换，再按类型签发短期 capability；保存型文件可不签发打开/定位能力。
- 导出、设备文件、配置快照、MESH、Online MR 和网络工具等下载只能复用正式 Artifact endpoint，Electron Main/Preload 不读取数据库、不生成报告、不解释业务文件。

## 命令、SNMP 与设备文件

- `resources/command_reference.json` 和命令说明页面只是只读展示目录，不是执行白名单。
- 生产执行命令必须进入版本化 Command Profile，绑定 Operation、step、selector、parser/DTO contract、风险级别和验证证据；未知厂商、角色、平台、软件版本或未验证 Profile 必须失败关闭。
- 当前稳定 Profile 包含只读 `device.inventory.collect` 和受控写操作 `device.sftp.enable`。除明确 Profile 外，不得从页面、Router 或通用 Service 执行任意 CLI。
- SNMP 只作为设备管理 v1/v2c 只读基础识别存在；禁止 SNMPv3、RW community、SET、Trap、通用 MIB/OID 字典、通用采集平台和 SNMP Center。
- 设备文件页面保持只读 SFTP：连接、断开、目录浏览、刷新、选择和下载。自动启用 SFTP 是独立受控 `config_write` 设备操作，必须有用户授权、明确不可用事实和精确 `device.sftp.enable` Profile，不能作为文件浏览的隐式副作用。

## 轨道交通业务边界

- 轨道交通基础资料统一在 `/rail-transit/base-data` 维护，页面默认锁定；写入必须同时满足 Feature、环境/会话授权、目标范围、revision 校验和后端事务。正式资料、导入来源和运行态数据不得相互伪装。
- 基础资料不建立第二套数据库；站点/区间、轨旁 AP、车载 MR 和规划写入复用当前局点 `devices.db`，失败必须完整回滚并保留前端编辑区。
- `/rail-transit/train-communication` 是固定车载 TC1/TC2 六节点通信检测页，不是无线综合看板；不得聚合轨旁 AP、RSSI、fping、iPerf、Online MR、Agent 或 Mesh-Link。
- 车内通信点表每列车只能包含 `TC1-MR/TC1-SW/TC1-SRV/TC2-MR/TC2-SW/TC2-SRV` 六节点；保存使用 SHA-256 revision。生成点表任务只返回编辑区预览，固定 `save_result=false`，`COMPLETED` 不等于预览可用，缺失或无效节点必须保留当前编辑内容。
- 地面无人值守是独立 `/rail-transit/ground-unattended` 页面和 `web.ground_unattended` Feature，不复用人工 Online MR 页面状态，也不把全天无人值守塞入单一 Online MR Session；页面卸载只停止轮询，托盘隐藏时 Backend、AC 轮询、全车 Ping 和深度采集继续。
- 地面无人值守调度必须用结构化正线分类、多目标 fping 分片、Online MR 强类型请求、并发预算、覆盖轮次、ZIP 原子归档和启动恢复；真实 AC/MR、长时 fping、托盘隐藏持续运行和进程残留仍是人工现场门禁。
- AP Identity 当前仍是只读 shadow/diagnostics，不接管生产匹配、页面展示、导出字段或数据库写入；unavailable/failed 不能改变原 Job/Export 终态。

## 验证与发布

- 开发阶段先跑与改动直接相关的 pytest、Vitest、Ruff、Go 测试、Electron test/typecheck/build/smoke 或架构单门；全量 pytest、完整前端测试/构建、Package Smoke 和九个架构门只在最终真实代码组合上运行。
- 测试不得读取或写入 `D:\NetConsoleData`、正式局点数据库、真实会话和报告；使用 `D:\NetConsoleTestData\<run-id>`、Fake 服务或显式测试 `NETCONSOLE_DATA_ROOT`。
- Electron-only 发布门包括九个架构 Guard、无 Qt 依赖/资源/许可证残留、锁定 Python constraints、SBOM/Notice、白名单 fping/iPerf 本地工具、安装包 smoke 和 Windows 图形人工验收。
- 正式 NSIS 构建必须从已提交、工作区 clean 且 `HEAD` 已推送到 upstream 的状态开始；最终安装包文件名包含 Git short commit，PE 身份、内嵌 installer manifest、数据根 include 哈希、Backend/Frontend commit 和两次 SHA-256 必须与本轮输入一致。
- 自动发布清单中的 `real_windows_install_status` 在隔离 Windows GUI 完成不存在目录、空目录、含普通文件目录和合法旧数据根等安装验收前必须保持 `PENDING`；单元测试、Backend smoke 或 unpacked Electron smoke 不能推断为 `PASS`。
- 架构例外必须精确到 `rule_id + path`，含理由、责任域、创建时间、到期时间和测试；禁止目录级通配、陈旧例外或删除测试换通过。

## 本周新增高置信沉淀（2026-07-20 至 2026-07-27）

- 统一数据根从开发、Electron、Backend、打包验证到正式安装包形成硬边界：机器级 `DataRoot` 是唯一持久指针，自动测试只用隔离测试根。
- 安装器数据根校验以“先分类、后探测、再初始化/发布指针”为固定流程，允许含普通文件目录且不得覆盖已有内容。
- v4 完整迁移包明确改为无密码、不加密、保留凭据的可信位置 ZIP；其他包类型保持脱敏和重录凭据边界。
- 工作区标签、多窗口和托盘驻留已成为 Electron 正式交互的一部分，但局点切换仍必须回到受控设置流程。
- 轨道交通地面无人值守成为独立 Feature 和数据目录；真实长时运行、真实 AC/MR 和托盘隐藏持续执行仍需人工门禁。
- 车内通信点表生成是预览契约，不是保存契约；任务完成只能说明调度结束，页面必须校验返回节点结构后再展示。

## 本周新增高置信沉淀（2026-07-13 至 2026-07-20）

- Electron-only 收口已从“并行迁移”进入活动产品边界：Qt 只保留历史追溯，不再作为测试、依赖、运行时或 fallback。
- 全局任务中心（抽屉与完整页面）、受控 Artifact 下载和 Native Bridge capability 成为跨模块默认交互；本机路径和凭据不回传 Renderer。
- 77 张标准 Web 表格已迁移到公共表格组件，后续新增表格必须同提交补清单和测试。
- 数据根、局点 Registry、`.ncsite`、备份恢复和迁移由 Python Application Service 管理；安装/卸载/升级不得删除用户数据根或 Electron bootstrap。
- 轨交基础资料真实编辑闭环、固定通信拓扑和设备文件 SFTP 受控启用均已形成明确边界，但真实设备、真实局点和 Electron 视觉验收仍需单独记录，不能由 Fake 或单元测试替代。
