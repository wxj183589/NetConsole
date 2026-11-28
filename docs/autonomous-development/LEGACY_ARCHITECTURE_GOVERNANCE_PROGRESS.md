# 旧版桌面架构治理进度

产品分支 `codex-A/legacy-architecture-governance`，审计基线 `7d423a73`。每项的提交以本文件所在分支历史及 DevStatus 对应记录核对。阶段状态不代替安装态验收。

| 阶段 | 依赖 | 状态 | 当前证据 / 尚缺的验收 |
| --- | --- | --- | --- |
| A 全面审计 | 基线 | PARTIAL | [实现清单](../architecture/LEGACY_IMPLEMENTATION_INVENTORY.md)逐项索引 API、页面、Store 和静态表声明，业务真机行为待核验 |
| B 设计与开源研究 | A | PARTIAL | [源码研究](../architecture/OPEN_SOURCE_REFERENCE_STUDY.md)覆盖七个项目。设备详情复用 DeviceDetailApplicationService，文件与设备任务保留各自所有者 |
| C 安装与启动 | A | PARTIAL | 修正七处 NSIS 子进程调用，保留退出码、诊断 ID、日志与安装事务。细分功能、平台、无人值守和路由初始化；看门狗分别记录阶段上报时刻、无进展时长和总时长，保留原有硬截止时间 |
| D 控制台 | A | PARTIAL | Python 执行与 Vue 预览统一支持空格、默认暂停和 1–60000 毫秒的参数暂停。修正脚本累计等待的单位。13 项 Python 测试、31 项 Renderer 测试及 Renderer 构建通过。粘贴、同步目标与真实会话待验收 |
| E 设备资料 | B | PARTIAL | 设备档案入口按台账 UUID 分页，技术详情复用原聚合服务，详见[模块契约](../architecture/LEGACY_MODULE_CONTRACTS.md)。带历史事实的界面验收待验证 |
| F 设备任务中心 | B、E | PARTIAL | 查询、统计、详情、日志、批量告警确认与清理按当前 Site 隔离。保留后台事件归属索引。多局点、Web API 和清理 79 项通过。设备任务域、模板、重试和 UI 切换竞态仍待验收 |
| G 轨交与无人值守 | A | PARTIAL | WPS 新目标默认关闭；旧配置一次性关闭，重新启用后跨重启保留。关闭时拒绝连接、探针及同步。WPS 后端 115 项、轨旁业务页 72 项通过。活动 Run、回放和通断统计待验 |
| H 日志与文件 | B、F | PARTIAL | 本地受管文件与设备传输分开，打开目录沿用当前局点受管令牌。结构化日志与最终桌面验证进行中 |
| I 全局菜单 | B、D–H | PARTIAL | 已重组导航分区并保留旧路由与 Feature，导航、路由、设备、轨交和任务 116 项集成测试通过 |
| J 集成验收 | C–I | PARTIAL | 52bc48ec 两个候选完成构建及哈希核验，Portable 解压后到达 Renderer stable。最终集成提交、安装态与覆盖升级仍需对应证据 |

## 安装和启动的验证记录

- Windows NSIS 与 Backend 定向验证：`pytest -q tests/test_installer_build.py tests/test_electron_runtime.py`，55 passed，含 NSIS include 编译。
- Electron Backend 管理器和启动页：两个 Vitest 文件共 36 passed，Electron typecheck 通过。
- 截图中的 `last_stage_elapsed=1065.032ms` 来源于子进程累计时钟。它只能定位到两个已上报事件之间，不能从该数值确定现场是数据库锁、磁盘慢或依赖缺失。需要相同安装环境的阶段日志来关闭此问题。
- L4 共享契约涉及 Desktop 生命周期、安装事务、DataRoot 和 API 组装。写入端为 Backend 阶段协议，读取端为 Electron Main 和启动页。未改协议字段、Schema、业务路径或恢复流程。主仓库只有一个已注册工作树。集成后需复跑 architecture-guards、electron-contract、main-contract-smoke、python-full、renderer-full。
- 工作区布局检查发现 6 项历史例外，用户确认保留并允许在规范路径生成本专项产物。此次测试使用隔离测试根。
- 发布状态为未发布，生产数据修改 0，删除数据库 0。

## 本轮界面验证

### Sol 集成记录

| 产品提交 | 修改和验收范围 |
| --- | --- |
| `4b5697a5` | 合入 SQL 分页前设备域过滤、全历史统计、局点切换保护、设备档案入口、独立归档回放与通断状态。Renderer 定向 116 项和构建通过 |
| `163de51d` | 失败目标按历史模板重试，配置采集、诊断、连接测试、集中采集及远程下载复用设备锁。归档的筛选和日志行为套件 39 项通过。打开受管目录与设备任务后端集成复验 43 项通过，Renderer 构建通过 |
| `f5932d3b` | 选定终端同步输入和粘贴、脚本会话变量和协议条件。Sol 分支五组 Console 定向测试 41 项通过，独立 Electron 窗口和设备交互待验收 |

基线候选目录为 Workspace 下 `temp/build/legacy-governance-candidate-52bc48ec`。Installer SHA-256 为 `4aa0938c3964c982d2e70d0522997fc1784227295cea1fd99d2c7f74d1217af0`，Portable SHA-256 为 `f54a910ddfdcc9b83675ff3940c7b2833a3915c559afeebd5538f78e4f015593`。对应隔离启动、截图与构建日志位于 `reports/tests/legacy-governance-20261128`。这组制品早于 Sol 集成。

任务中心真实 Electron smoke 在隔离测试根完成，退出码 0。控制台原生粘贴、右键及快捷键共用确认入口，校验设备会话与连接，限制预览长度，支持关闭多行提示。控制台 Vue 7 个测试文件 48 项通过，Renderer 构建通过。未连接真实设备。多窗口同步输入、实际剪贴板端到端仍待验收。

## WPS 局点配置迁移与回退

局点专用 wps_sync.sqlite 从 user_version 0 迁移至 1。初始化事务持有写锁，同时重置历史默认开关并更新版本；异常时 SQLite 回滚事务。配置 URL、凭据密文、绑定、任务与历史表结构保留。旧版仍可读取配置，降级后保留关闭状态；如需恢复同步由用户在目标局点显式启用。Installer、Portable 共用 Repository，已在隔离 fixture 验证重复启动、凭据及目标 ID，安装态升级仍待验收。此次没有连接真实 WPS。
