# Codex 项目规则

## 项目概况

- NetConsole 是 Windows 本地网络设备采集与分析工具。正式桌面产品为 Electron Main + Preload + Vue，FastAPI/Python Core 是永久业务层；Qt/PySide6 源码、运行时和回退入口已退出活动架构，不得重新引入。
- 真实版本从 `src/netconsole/core/version.py` 读取，用户可见功能从 `src/netconsole/core/feature_registry.py` 读取，数据路径从 `src/netconsole/core/paths.py` 读取。
- Windows Go Agent V1 已位于 `apps/agent/`，包含独立 API、内嵌 Web、fping/iPerf、MR sidecar 和采集包；Traffic REST/WebSocket 与 Vue 流量测试页面已接入，CentOS 离线部署、主动注册和多 Controller 仍未实现。
- 开发前先读当前代码、测试和 `docs/README.md`，不依赖旧会话或旧项目假设。

## 语言与编码

- 默认使用中文回复，保留中文 UI、注释和日志。
- 源码、Markdown、JSON、TOML、YAML、CSV 和项目日志默认 UTF-8；Python 文本读写显式指定 `encoding="utf-8"`。
- 外部 H3C 回显、历史日志和导出文件按 `utf-8-sig / utf-8` 优先，失败后尝试 `gb18030 / gbk`。
- PowerShell/Codex 终端乱码不等于文件损坏；先检查原始字节和读取编码，不用默认 `echo`、`cat`、`Get-Content` 判断中文内容。

使用 PowerShell 执行 Windows 管理、PyCharm 启动配置或其他明确依赖 PowerShell 的命令，且涉及中文、路径、日志、附件或设备回显时设置：

```powershell
chcp 65001 > $null
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
```

## 开发环境与命令

- 目标开发环境是 Windows 11，不假设 WSL、`python3` 或 Linux 包管理器可用。
- Codex 集成终端默认使用 Git Bash，默认生成 Bash 兼容命令；Windows 管理、PyCharm 启动配置、`.ps1` 脚本或命令输出明确需要 PowerShell 时使用 PowerShell。不使用 CMD，除非用户明确要求。
- Git Bash 路径使用 `D:/...` 或 `/d/...`，含空格路径必须加引号；不得混用 PowerShell、Git Bash 和 CMD 语法。
- 优先使用项目 `.venv`，例如 `.venv/Scripts/python.exe -m pytest`、`.venv/Scripts/python.exe -m pip` 和 `.venv/Scripts/python.exe -m ruff`；仅在 `.venv` 不存在或不可用时使用系统 Python。
- Python 模块和工具统一通过 `python -m ...` 语义运行，不直接假设 `pytest`、`pip`、`ruff` 等可执行文件在 `PATH` 中。
- Vue 与 Electron 依赖和脚本以各自 `package.json`、`pnpm-lock.yaml` 为准，使用 `pnpm`，不擅自切换包管理器或重写锁文件。

## 安装目录与业务数据根

- Windows 安装包的程序目录只保存 EXE、DLL、Python/Electron 运行时、前端资源、内置工具和只读默认配置；SQLite、局点文件、MESH 日志、报告、缓存和用户配置必须位于独立业务数据根。
- 业务数据根的唯一持久化指针是安装器写入的 `HKLM\Software\NetConsole\DataRoot`；源码、Electron 开发、Python Backend、打包验证与正式安装包都通过同一解析器读取。`NETCONSOLE_DATA_ROOT` 只可作为显式覆盖，未配置持久根时停止启动，绝不回退 LocalAppData、用户目录、仓库、安装目录或系统 Temp。
- 安装器必须拒绝系统盘、网络/可移动盘、程序目录、用户 Profile 与 NetConsole 必需路径发生真实冲突的目录；允许含无冲突普通文件的目录并保留原内容。升级和修复默认沿用既有根。更改根必须先完成受控迁移，再更新指针；普通卸载保留业务数据和指针。
- 自动化测试必须显式 `RuntimeMode.TEST` 和 `D:\study\test-data\NetConsole\<run-id>`，不得读取机器级指针或真实根。

## 全局开发规则

- 先梳理目标、假设和验证标准；只改当前需求范围，优先复用现有组件、Service、Repository、Parser 和路径 helper。
- 不新增 Qt/PySide6/QFluentWidgets 代码；新用户功能按共享规则/现有 `src/netconsole/services` Application Service -> FastAPI -> Vue 建设。
- Vue、Electron 和 FastAPI Router 不得直接实现设备、数据库、采集或业务状态机；Router 只做 DTO、鉴权、Service 调用和响应映射。
- Electron 安全基础已进入实现期；只承载窗口、进程生命周期、后续托盘/升级和白名单 Native Bridge，不提供任意命令、路径或程序执行接口，也不建立第二套 Renderer 或业务 Core。
- 保留提交历史；不执行 `git reset`、`git checkout --`、`git clean`、`git stash`、`git push --force` 等破坏性或改写历史操作，不覆盖用户未提交修改。确需执行时必须先获得用户明确授权。
- 网络、磁盘、解析、压缩、大查询和批量任务不得阻塞 UI；超过 300ms 的 IO/CPU/网络任务进入 Job Center，所有导出进入独立 Export Process。
- Vue Renderer 只负责布局、输入、轻量校验和状态绑定；Worker 不访问 DOM 或 Electron 对象，SQLite connection 不跨线程/进程共享。
- 不擅自修改用户要求保持的设备命令、顺序或原始文本；不静默删除数据库、原始日志、会话或正式报告。
- 新用户可见模块、页面、Tab、动作或按钮默认接入 Feature Registry；用户可见文本进入 i18n。
- SNMP Center 与无线勘测已批准从活动产品删除，不得新增 Web/Electron/API 入口；网络工具无线扫描是独立能力，不属于无线勘测。
- 页面、弹窗和弹出子页不得被窗口挤压；内容超出时提供纵向和必要的横向滚动，表格允许手工调列宽。
- 重要架构或状态变化同步 docs；区分已完成、兼容层、shadow/diagnostics、部分迁移和规划。
- 完成后运行适用验证并如实报告；提交/推送说明使用中文，未经用户要求不自动提交。

## Change Impact 与共享层稳定窗口

- 开始任务时先按 [`docs/development/CHANGE_IMPACT_FRAMEWORK.md`](./docs/development/CHANGE_IMPACT_FRAMEWORK.md) 判断 L1-L4；计划路径使用 `python -m scripts.quality.check_change_impact --paths ...` 获取最低等级、共享契约、消费者和回归套件。语义只能上调风险，不能下调 Registry 命中。
- L1 是单页面 CSS/文案/局部展示；L2 是单领域 Service/Repository/Parser/页面；L3 是共享组件、Renderer API、Task/Job、Export、AP Identity；L4 是 Feature Registry、DataRoot、数据库迁移、Electron runtime、CI 和构建发布。
- L3/L4 编码前必须使用 `netconsole-change-review-skill` 完成 Consumer Audit，列出写入、读取、缓存、展示、导出、旧格式、并行修改和合并后复验；不得只跑当前目标模块测试。
- Electron-only 收敛后的 1～2 个开发轮次作为共享层稳定窗口：`api/client`、NcDataTable、动态图、Task/Job、Export、AP Identity、Feature Registry、Path/DataRoot、Electron runtime 和构建发布只接受必要 Bug/安全修复。同一时间最多一个大型 L3/L4 重构，解除冻结以新的 `main` baseline 为证据。
- 普通 worktree/分支尽量当天或 1～2 天完成。分支明显落后 `main` 时优先从最新 `main` 重建并移植本任务提交；同步 `main` 遇到不属于当前领域的共享文件冲突时标记 `out-of-scope conflict`，不得顺手解决后继续按原风险交付。
- L3/L4 在最终合并 commit 重新运行 Registry 指定 consumer suites；分支绿不等于 `main` 绿。交付必须报告 risk、contracts、consumers、兼容性、并行修改、合并后结果和 GUI/设备/制品缺口。

## 用户文件导入导出

- 新增或修改任何用户可见的导入、导出、模板下载、报告生成或 Artifact 保存入口前，必须先阅读 `docs/export/USER_FILE_INTERACTION.md`。
- 新增任务型导出必须先登记 `apps/desktop_renderer/src/platform/exportActionRegistry.ts` 的固定动作，再复用 `apps/desktop_renderer/src/composables/useUserSelectedExport.ts`；禁止页面自行实现路径选择、任务绑定、Artifact 轮询、最终保存或失败重试。
- 用户取消保存路径选择时不得创建任务、生成 Artifact 或提示提交成功。已有 Artifact 只在用户主动点击后另存，不得在页面加载、Tab 恢复或历史任务恢复时自动弹窗。
- 新增导入必须复用现有 Browser `File/FileList` 或 Electron Main 专用选择器；取消不调用后端，处理后清空 file input，Main 路径模式只使用当次授权路径且保留 Backend 文件契约校验。
- OmniPeek、局点包、SFTP 受管下载等新增例外必须同步永久规范和静态审计，写明不能使用通用协调器的技术原因并获得明确评审。

## 验证与交付

- 开发阶段先运行与改动直接相关的定向测试；Python 文件改动至少运行相关 pytest、修改范围 Ruff，并按需运行 `python -m py_compile`。
- Vue 改动在 `apps/desktop_renderer` 运行相关 `pnpm test` 和 `pnpm build`；Electron 改动按 `docs/testing/BASELINE.md` 运行对应 test、typecheck、build 或 smoke 命令。
- 完整 pytest、完整前端测试/构建、Ruff、文档链接检查和受影响的 Go 测试只在集成后的真实代码组合上作为最终门槛；单个并行任务不重复跑全量套件。
- 不得在未执行验证时声称完成；无法执行时说明原因、未验证范围和剩余风险。
- 修改前简述实施计划；完成后列出修改文件、执行过的验证、数据库/导出/耗时任务影响和已知限制。纯文档规则修改应明确未改业务代码。

## 仓库目录约束

- 新业务代码不得直接建立在仓库根目录；新增顶层目录前必须先更新 [仓库目录规范](./docs/development/repository-layout.md) 并说明唯一职责。
- Electron、Web、Agent 分别进入 `apps/desktop_electron`、`apps/desktop_renderer`、`apps/agent`；共享 Python 业务代码进入 `src/netconsole`。不得重新创建 `apps/desktop` 或 `src/netconsole/ui`；`apps/desktop_electron` 只放 main/preload/shared 和必要打包元数据，不复制 Vue 或 Python Core。
- 不为符合架构示意图创建空的 `domain/application/infrastructure` 层，也不机械搬移现有包；按真实用例逐步收敛依赖。
- 配置、版本化资源、测试 fixtures 和脚本分别进入 `config`、`resources`、`tests`、`scripts/build|dev|maintenance`，不得创建 `misc`、`temp`、`new`、`project` 等模糊目录。
- 运行数据、日志、数据库、抓包、采集结果、缓存、临时导出和正式报告不得写入或提交仓库；开发态使用 `.local/`，打包态使用系统应用数据目录或用户选择的导出目录。
- 移动文件后必须同步检查 Python import、测试、构建参数、批处理、前端工作目录、Agent 入口、文档和资源定位。
- 禁止使用 `Path.cwd()` 定位源码、资源、配置或运行数据；禁止用临时 `sys.path` 修改掩盖包结构问题。
- 不允许提交 `.venv`、缓存、日志、数据库、安装包、构建产物和临时导出文件；`resources/tools` 中已记录来源与许可证的 fping/iPerf 运行依赖是已审计例外。根 `tools/` 只用于开发、诊断和维护，`apps/agent/tools/` 禁止作为运行时工具来源。
- `apps/agent` 二级目录只保留 `cmd`、`internal`、`mr_collector_py`、`web`、`scripts`、`resources/config` 和项目元文件；示例配置命名为 `config.example.json`/`targets.example.json`，真实配置不得回写源码目录。Agent 开发运行数据使用 `.local/agent/`，构建产物使用 `dist/agent/`；禁止保留 `apps/agent/bin`、`data`、`dist`、`logs`、`packages`、`tmp` 和 `apps/agent/tools` 作为运行目录或工具来源。
- 文档中的源码文件路径必须使用 `src/netconsole/...`；只有 Python import、模块或包名语境可以写 `netconsole.*`，不得写成 `src.netconsole.*`。除标准 `apps/desktop_electron`、`apps/desktop_renderer` 和 `src/netconsole` 归位外，不得新建旧根目录 `agent/tools`、`apps/desktop`、`apps/agent/tools`、`frontend`、`desktop`、`netconsole`、`profiles` 或 `project`。
- 修改 Agent 构建、工具、配置或路径时，必须同步检查 `apps/agent/README.md`、`docs/agent/README.md`、`docs/release/BUILD_AND_RELEASE.md`、`resources/tools/README.md` 和 `docs/development/repository-layout.md`；重要文档链接必须在提交前验证。
- 目录职责不明确时先审计内容、Git 跟踪状态和引用关系，不得先新建目录或静默删除数据。

## Skill 路由

项目级 Skills 位于 `.agents/skills/`，完整说明见 `docs/development/CODEX_SKILLS.md`。

| Skill | 何时使用 | 不适用范围 |
| --- | --- | --- |
| `netconsole-job-center-skill` | 普通后台 Job、JSONL、取消和迁移 | 文件导出、轻量 UI |
| `netconsole-user-file-interaction-skill` | 用户可见导入/导出、模板下载、报告保存、Artifact 另存和文件选择 | Worker 内部生成、SFTP 受管下载实现、数据库业务 |
| `netconsole-export-report-skill` | ExportJob、本地 XLSX/CSV/PDF/ZIP 报告 | 实时采集、普通表格样式 |
| `netconsole-ac-management-skill` | AC/FIT-AP、强类型动作、OmniPeek 名称表 | 普通设备管理、无 AC 作用域的 Identity |
| `netconsole-train-communication-skill` | 车内通信点表、TC1/TC2、离线可测、VRRP 边界 | Online MR 实时采集、列车在线页 |
| `netconsole-device-files-skill` | 只读 SFTP、主机密钥、下载队列和 `.part` | 普通 SSH、配置采集 |
| `netconsole-config-collection-skill` | 配置快照、两文件对比、裁剪和差异导出 | AC 快照、普通文本 diff |
| `netconsole-online-mr-skill` | 车载 MR 实时采集、Ping/iPerf、会话打包 | 离线 MESH 分析 |
| `netconsole-agent-skill` | Windows Go Agent API、构建、工具、配置、targets、MR sidecar 和运行目录 | CentOS 离线部署；纯流量语义；纯 MR 命令规则 |
| `netconsole-device-management-skill` | 设备 CRUD、连接/采集、CSV、凭据和外部终端 | AC/FIT-AP、SFTP、配置快照 |
| `netconsole-electron-desktop-skill` | Electron Main/Preload/IPC、Backend 生命周期、窗口与托盘 | 普通 Vue 业务、NSIS/发布制品 |
| `netconsole-rail-base-data-skill` | 轨交基础资料、站点/区间、轨旁规划、revision 和事务保存 | 轨旁运行态、Ground、Online MR 采集 |
| `netconsole-trackside-ap-skill` | 轨旁 AP 业务、LLDP/光衰/采集、Identity 消费和业务快照 | 普通 AC、无轨旁作用域 Identity |
| `netconsole-ground-unattended-skill` | 地面无人值守调度、资格、fping/Syslog、深采和归档恢复 | 普通 Online MR 或离线 MESH |
| `netconsole-release-packaging-skill` | PyInstaller/Electron/NSIS、Full/Customer、制品与发布门 | 普通业务功能和单个报告导出 |
| `netconsole-mesh-analysis-skill` | MR 原始 MESH 离线分析、图表和报告 | 在线 SSH 采集 |
| `dynamic-chart-stability` | ECharts 时间轴、Tooltip、指标单位契约、DataZoom、Resize、KeepAlive、沉浸式或动态图白块 | 静态图、普通表格、无图表 parser |
| `netconsole-ap-identity-skill` | AP/Radio/BSSID/Peer 身份与 shadow | 普通 AP 展示 |
| `network-command-parser-skill` | H3C/Comware 命令回显 parser | 设备管理 SNMP、UI |
| `traffic-test-skill` | fping、iPerf、TCP/UDP、阈值 | 普通 SSH/路由 |
| `windows-encoding-skill` | Windows/H3C/文件/子进程编码 | i18n 词条设计 |
| `netconsole-data-safety-skill` | SQLite、Repository、目录、备份和清理 | 纯 UI/parser |
| `netconsole-project-docs-skill` | README/docs/架构状态同步 | 一次性用户报告 |
| `netconsole-change-review-skill` | L3/L4 编码前 Change Impact Audit 与当前 diff 只读评审 | 直接实现或自动修复 |

只在当前任务跨领域时组合相关 Skills，不无条件加载全部 Skills。
