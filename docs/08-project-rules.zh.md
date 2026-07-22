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
- 开发数据使用受控本机数据根或 `.local/`；打包态使用系统应用数据目录或用户选择的导出目录。历史数据迁移和清理必须 dry-run、manifest、白名单，不得静默删除用户数据库、原始日志、会话或正式报告。
- 新增目录、移动文件或调整 Agent/工具/构建路径时，同步检查 import、测试、构建参数、前端工作目录、Agent 入口、文档链接和资源定位。

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
- AP Identity 当前仍是只读 shadow/diagnostics，不接管生产匹配、页面展示、导出字段或数据库写入；unavailable/failed 不能改变原 Job/Export 终态。

## 验证与发布

- 开发阶段先跑与改动直接相关的 pytest、Vitest、Ruff、Go 测试、Electron test/typecheck/build/smoke 或架构单门；全量 pytest、完整前端测试/构建、Package Smoke 和九个架构门只在最终真实代码组合上运行。
- 测试不得读取或写入开发态 `.local/data`、正式局点数据库、真实会话和报告；使用 `tmp_path`、Fake 服务或显式临时 `NETCONSOLE_DATA_ROOT`。
- Electron-only 发布门包括九个架构 Guard、无 Qt 依赖/资源/许可证残留、锁定 Python constraints、SBOM/Notice、白名单 fping/iPerf 本地工具、安装包 smoke 和 Windows 图形人工验收。
- 架构例外必须精确到 `rule_id + path`，含理由、责任域、创建时间、到期时间和测试；禁止目录级通配、陈旧例外或删除测试换通过。

## 本周新增高置信沉淀（2026-07-13 至 2026-07-20）

- Electron-only 收口已从“并行迁移”进入活动产品边界：Qt 只保留历史追溯，不再作为测试、依赖、运行时或 fallback。
- 统一任务窗口、受控 Artifact 下载和 Native Bridge capability 成为跨模块默认交互；本机路径和凭据不回传 Renderer。
- 77 张标准 Web 表格已迁移到公共表格组件，后续新增表格必须同提交补清单和测试。
- 数据根、局点 Registry、`.ncsite`、备份恢复和迁移由 Python Application Service 管理；安装/卸载/升级不得删除用户数据根或 Electron bootstrap。
- 轨交基础资料真实编辑闭环、固定通信拓扑和设备文件 SFTP 受控启用均已形成明确边界，但真实设备、真实局点和 Electron 视觉验收仍需单独记录，不能由 Fake 或单元测试替代。
