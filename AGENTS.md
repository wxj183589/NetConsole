# Codex 项目规则

## 项目概况

- NetConsole 是 Windows 本地网络设备采集与分析工具。当前运行形态仍包含 Qt6/PySide6，长期目标是 Python Core + FastAPI 永久业务层、Vue 永久主界面和 Electron 最终桌面外壳；Qt 只作为迁移期生产与回退入口并最终删除。
- 真实版本从 `src/netconsole/core/version.py` 读取，用户可见功能从 `src/netconsole/core/feature_registry.py` 读取，数据路径从 `src/netconsole/core/paths.py` 读取。
- Windows Go Agent V1 已位于 `apps/agent/`，包含独立 API、内嵌 Web、fping/iPerf、MR sidecar 和采集包；Traffic REST/WebSocket 与 Vue 流量测试页面已接入，CentOS 离线部署、主动注册和多 Controller 仍未实现。
- 开发前先读当前代码、测试和 `docs/README.md`，不依赖旧会话或旧项目假设。

## 语言与编码

- 默认使用中文回复，保留中文 UI、注释、日志和 MIB 描述。
- 源码、Markdown、JSON、TOML、YAML、CSV 和项目日志默认 UTF-8；Python 文本读写显式指定 `encoding="utf-8"`。
- 外部 H3C 回显、MIB、历史日志和导出文件按 `utf-8-sig / utf-8` 优先，失败后尝试 `gb18030 / gbk`。
- PowerShell/Codex 终端乱码不等于文件损坏；先检查原始字节和读取编码，不用默认 `echo`、`cat`、`Get-Content` 判断中文内容。

涉及中文、路径、日志、附件或设备回显前设置：

```powershell
chcp 65001 > $null
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
```

## 全局开发规则

- 先梳理目标、假设和验证标准；只改当前需求范围，优先复用现有组件、Service、Repository、Parser 和路径 helper。
- 不新增 Qt 业务页面或只供 Qt 使用的新业务逻辑；新用户功能默认按 Domain/共享规则 -> Application Service -> FastAPI -> Vue 建设，迁移期 Qt 只复用永久业务层。
- Vue、Electron 和 FastAPI Router 不得直接实现设备、数据库、采集或业务状态机；Router 只做 DTO、鉴权、Service 调用和响应映射。
- Electron 安全基础已进入实现期；只承载窗口、进程生命周期、后续托盘/升级和白名单 Native Bridge，不提供任意命令、路径或程序执行接口，也不建立第二套 Renderer 或业务 Core。
- 不执行 `git reset`、`git checkout --`、`git clean`、`git stash` 等破坏性操作，不覆盖用户未提交修改。
- 网络、磁盘、解析、压缩、大查询和批量任务不得阻塞 UI；超过 300ms 的 IO/CPU/网络任务进入 Job Center，所有导出进入独立 Export Process。
- UI 只负责布局、输入、轻量校验和状态绑定；Worker 不访问 QWidget，SQLite connection 不跨线程/进程共享。
- 不擅自修改用户要求保持的设备命令、顺序或原始文本；不静默删除数据库、原始日志、会话或正式报告。
- 新用户可见模块、页面、Tab、动作或按钮默认接入 Feature Registry；用户可见文本进入 i18n。
- SNMP Center 与无线勘测保持禁用并归入 `EXCLUDED/FUTURE_REBUILD`，不新增 Qt/Web/Electron 入口；网络工具无线扫描是独立能力。
- 页面、弹窗和弹出子页不得被窗口挤压；内容超出时提供纵向和必要的横向滚动，表格允许手工调列宽。
- 重要架构或状态变化同步 docs；区分已完成、兼容层、shadow/diagnostics、部分迁移和规划。
- 完成后运行适用验证并如实报告；提交/推送说明使用中文，未经用户要求不自动提交。

## 仓库目录约束

- 新业务代码不得直接建立在仓库根目录；新增顶层目录前必须先更新 [仓库目录规范](docs/development/repository-layout.md) 并说明唯一职责。
- Qt Legacy、Electron、Web、Agent 分别进入 `apps/desktop`、`apps/desktop_electron`、`apps/web`、`apps/agent`；共享 Python 业务代码进入 `src/netconsole`。本阶段不移动或改名现有 Qt 目录，`apps/desktop_electron` 只放 main/preload/shared，不复制 Vue 或 Python Core。
- 不为符合架构示意图创建空的 `domain/application/infrastructure` 层，也不机械搬移现有包；按真实用例逐步收敛依赖。
- 配置、版本化资源、测试 fixtures 和脚本分别进入 `config`、`resources`、`tests`、`scripts/build|dev|maintenance`，不得创建 `misc`、`temp`、`new`、`project` 等模糊目录。
- 运行数据、日志、数据库、抓包、采集结果、缓存、临时导出和正式报告不得写入或提交仓库；开发态使用 `.local/`，打包态使用系统应用数据目录或用户选择的导出目录。
- 移动文件后必须同步检查 Python import、测试、构建参数、批处理、前端工作目录、Agent 入口、文档和资源定位。
- 禁止使用 `Path.cwd()` 定位源码、资源、配置或运行数据；禁止用临时 `sys.path` 修改掩盖包结构问题。
- 不允许提交 `.venv`、缓存、日志、数据库、安装包、构建产物和临时导出文件；`resources/builtin_mibs` 中明确版本化的 MIB 归档和 `resources/tools` 中已记录来源与许可证的 fping/iPerf 运行依赖是已审计例外。根 `tools/` 只用于开发、诊断和维护，`apps/agent/tools/` 禁止作为运行时工具来源。
- `apps/agent` 二级目录只保留 `cmd`、`internal`、`mr_collector_py`、`web`、`scripts`、`resources/config` 和项目元文件；示例配置命名为 `config.example.json`/`targets.example.json`，真实配置不得回写源码目录。Agent 开发运行数据使用 `.local/agent/`，构建产物使用 `dist/agent/`；禁止保留 `apps/agent/bin`、`data`、`dist`、`logs`、`packages`、`tmp` 和 `apps/agent/tools` 作为运行目录或工具来源。
- 文档中的源码文件路径必须使用 `src/netconsole/...`；只有 Python import、模块或包名语境可以写 `netconsole.*`，不得写成 `src.netconsole.*`。除标准 `apps/desktop`、`apps/web` 和 `src/netconsole` 归位外，不得新建旧根目录 `agent/tools`、`apps/agent/tools`、`frontend`、`desktop`、`netconsole`、`profiles` 或 `project`。
- 修改 Agent 构建、工具、配置或路径时，必须同步检查 `apps/agent/README.md`、`docs/AGENT.md`、`docs/BUILD_AND_RELEASE.md`、`resources/tools/README.md` 和 `docs/development/repository-layout.md`；重要文档链接必须在提交前验证。
- 目录职责不明确时先审计内容、Git 跟踪状态和引用关系，不得先新建目录或静默删除数据。

## Skill 路由

项目级 Skills 位于 `.agents/skills/`，完整说明见 `docs/CODEX_SKILLS.md`。

| Skill | 何时使用 | 不适用范围 |
| --- | --- | --- |
| `qt6-polished-ui-skill` | 新建或系统性优化 Qt6 页面 | 单点遮挡、纯后端 |
| `qt6-ui-fix-skill` | 修复遮挡、滚动、表格、主题、UI 卡顿 | 全新页面、纯 Excel |
| `qfluentwidgets-netconsole-ui-skill` | Fluent Shell、主题、CommandBar、fallback | 普通布局、业务逻辑 |
| `netconsole-qt6-ui-taste-skill` | UI 审美、状态、按钮归属只读审查 | 默认不实施修改 |
| `netconsole-job-center-skill` | 普通后台 Job、JSONL、取消和迁移 | 文件导出、轻量 UI |
| `netconsole-export-report-skill` | ExportJob、本地 XLSX/CSV/PDF/ZIP 报告 | 实时采集、普通表格样式 |
| `netconsole-online-mr-skill` | 车载 MR 实时采集、Ping/iPerf、会话打包 | 离线 MESH 分析 |
| `netconsole-agent-skill` | Windows Go Agent API、构建、工具、配置、targets、MR sidecar 和运行目录 | CentOS 离线部署；纯流量语义；纯 MR 命令规则 |
| `netconsole-mesh-analysis-skill` | MR 原始 MESH 离线分析、图表和报告 | 在线 SSH 采集 |
| `netconsole-ap-identity-skill` | AP/Radio/BSSID/Peer 身份与 shadow | 普通 AP 展示 |
| `h3c-snmp-mib-skill` | H3C MIB、OID、模块、参考表 | SNMP 请求调度、CLI parser |
| `snmp-collector-design-skill` | SNMP GET/WALK/SET、并发、缓存、取消 | MIB 文件修复 |
| `network-command-parser-skill` | H3C/Comware 命令回显 parser | SNMP MIB、UI |
| `traffic-test-skill` | fping、iPerf、TCP/UDP、阈值 | 普通 SSH/路由 |
| `windows-encoding-skill` | Windows/H3C/文件/子进程编码 | i18n 词条设计 |
| `netconsole-data-safety-skill` | SQLite、Repository、目录、备份和清理 | 纯 UI/parser |
| `netconsole-project-docs-skill` | README/docs/架构状态同步 | 一次性用户报告 |
| `netconsole-change-review-skill` | 当前 diff 的项目级只读评审 | 直接实现或自动修复 |

只在当前任务跨领域时组合相关 Skills，不无条件加载全部 Skills。
