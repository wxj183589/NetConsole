# NetConsole

NetConsole 是面向网络工程现场维护与诊断的 Windows 桌面工具，当前重点覆盖 H3C/Comware 设备管理、AC/FIT AP、轨道交通车地无线、SNMP/MIB、网络测试、配置采集、文件管理和日志诊断。

当前版本：`v1.3.8`。版本唯一来源为 `src/netconsole/core/version.py`；本文不单独维护版本号。

## 仓库地址

| 仓库 | Git 推送地址 | 浏览器地址 |
| --- | --- | --- |
| GitHub | `git@github.com:wxj183589/NetConsole.git` | `https://github.com/wxj183589/NetConsole.git` |
| NAS | `ssh://git@nas.love-ok.com:3022/mengyou/NetConsole.git` | `https://nas.love-ok.com:3021/mengyou/NetConsole.git` |

关于页只使用浏览器地址，Git 操作只使用 SSH 推送地址，二者不得混用。

当前开发技术栈为 Python 3.13、Qt 6、PySide6、QFluentWidgets、SQLite、Netmiko、openpyxl、FastAPI、Pydantic、Vue 3、TypeScript、Vite、Element Plus、Pinia 和 Vue Router。阶段 3 已提供实验 Qt Web Shell、任务中心和 Agent 管理控制面；阶段 4B-2 已建立统一流量测试应用服务、本地/Agent 执行适配、任务映射、持久事件和远端恢复，但尚未创建 Traffic REST/WebSocket 路由或 Vue 流量页面。Python 依赖以 `requirements.txt` 为准，前端依赖以 `apps/web/package.json` 和 `pnpm-lock.yaml` 为准。

## 当前能力

| 一级模块 | Feature key | 主要能力 |
| --- | --- | --- |
| 设备管理 | `module.devices` | 设备、分组、连接测试、批量采集、SecureCRT/OmniPeek 导出 |
| AC 管理 | `module.ac` | FIT AP 资源、扩展、光衰、历史和命令 |
| 轨道交通 | `module.rail_transit` | 车载 MR、Online MR、MR/Mesh 离线分析、轨旁 AP、车载网络点表 |
| 无线勘测 | `module.wifi_survey` | `DISABLED`；代码和数据保留，等待独立重构 |
| 配置采集 | `module.config_collection` | 配置快照、比较、批量采集 |
| 文件管理 | `module.file_management` | 局点文件、下载、复制和整理 |
| SNMP Center | `module.snmp_center` | `DISABLED`；代码、数据库和 MIB 保留，等待独立重构 |
| 网络工具 | `module.network_tools` | Ping/fping、iPerf3、工具箱和用户配置的可选外部 IPOP v4.1 |
| 命令参考 | `module.command_reference` | 命令、参数、解析器与消费者索引 |
| 日志 | `module.logs` | 应用日志查看与导出 |
| 系统设置 | `module.system_settings` | 局点、主题、工具路径、磁盘清理和版本信息 |

模块、页面、Tab、动作和按钮的真实启用状态以 `src/netconsole/core/feature_registry.py` 为准。新增用户可见能力必须先登记 Feature key，再由页面通过 `FeatureGate` 控制。

## 仓库结构

```text
apps/       独立应用：Agent、Desktop Web Shell、Web 前端
src/        可安装的 Python 包（src/netconsole）
config/     开发和构建配置模板（含 feature profiles）
docs/       项目文档和长期工程规则
resources/  版本化静态资源、命令参考、MIB 归档和随包运行工具
scripts/    build、dev、maintenance 脚本
tests/      自动化测试和脱敏 fixtures
tools/      独立开发、诊断、维护和协议分析工具，不作为运行时工具来源
```

根目录只保留项目级配置、说明、许可证、`main.py` 兼容入口和上述白名单目录。完整规则见 [仓库目录规范](docs/development/repository-layout.md)。

## 架构摘要

```mermaid
flowchart LR
    UI["Qt6 / PySide6 / QFluentWidgets UI"] --> SVC["Services"]
    WS["Qt Web Shell / Browser"] --> VUE["Vue Task Center / Agent 管理"]
    VUE --> API["FastAPI Task / Agent API + WebSocket"]
    API --> SVC
    SVC --> REPO["Repositories"]
    REPO --> DB["SQLite / 文件数据"]
    UI --> JOB["Background Job Process"]
    UI --> EXP["Export Process"]
    JOB --> REG["Job Registry / Domain Handlers"]
    EXP --> WRITER["Export Handlers"]
    REG --> SVC
    WRITER --> REPO
    API --> CTRL["AgentControllerService"]
    CTRL --> AGENT["Windows Go Agent HTTP API"]
    AGENT --> AGENTDATA["Agent tasks / raw / packages"]
    SVC --> TRAFFIC["TrafficTestApplicationService"]
    TRAFFIC --> JOB
    TRAFFIC --> CTRL
```

- UI 只负责交互和轻量展示；预计超过 300 ms 的 IO、CPU 或网络工作进入后台任务。
- 普通后台任务走 `Qt BackgroundProcessManager -> TaskApplicationService/TaskRuntime -> background_worker -> JobRegistry -> handler`。
- 任务快照和事件写入每局点 `tasks.db`；Vue 任务中心支持列表、详情、日志和协作取消。
- Agent 配置与运行状态分别写入每局点 `agents.db`；Token 仅保存在当前 Python 进程内，REST/WebSocket 不返回凭据。
- 所有正式导出走独立 Export Process，使用临时文件完成后原子替换目标文件。
- 可再次导入的 XLSX/CSV/JSON/ZIP 正式导出写入 NetConsole 文件契约；导入入口在业务层统一校验扩展名、模块、类型、schema、必要结构和非空数据，不能只依赖文件选择框过滤。
- `JobRegistry` 当前注册 86 个任务类型，已按 11 个领域 handler 模块分区；新增三个本地 Traffic handler，多数既有领域 handler 仍通过 `legacy_tasks.py` 薄适配，迁移尚未完成。
- 设备批量连接测试和批量详情采集仍使用专用 `QThread`/线程池，不应误写成 Job Center 已接管。
- AP Identity 当前仅为只读 shadow/diagnostics，不参与生产匹配、页面展示或业务结论接管。
- Windows Go Agent 仍是独立进程和数据根；`AgentTrafficSupervisor` 已把远端 iPerf/fping 状态、事件和结果映射到 Task Center，Token 始终留在 Controller 进程内。面向浏览器的 Traffic API 与页面尚未实现。

完整说明见 [架构文档](docs/ARCHITECTURE.md)、[Web 演进架构](docs/WEB_ARCHITECTURE.md)、[Job Center](docs/JOB_CENTER.md)、[导出进程规范](docs/export_process_policy.md) 和 [重构地图](docs/REFACTOR_MAP.md)。

## 开发与运行

开发前先阅读：

1. [项目文档索引](docs/README.md)
2. [开发规则](docs/DEVELOPMENT_RULES.md)
3. [架构约束](docs/ARCHITECTURE.md)
4. [数据与路径](docs/DATA_LAYOUT.md)
5. 与改动领域对应的专题文档

优先使用仓库虚拟环境：

```powershell
.\.venv\Scripts\python.exe -m pip install -e . --no-deps
.\.venv\Scripts\python.exe main.py
.\.venv\Scripts\python.exe main.py --web-shell
.\.venv\Scripts\python.exe -m netconsole.backend.api.main
.\.venv\Scripts\python.exe -m pytest
```

前端首次运行或依赖变化后执行：

```powershell
cd apps/web
pnpm install
pnpm test
pnpm build
```

Windows/PowerShell 涉及中文、日志、设备回显或路径时，先切换 UTF-8；源码和 Markdown 统一使用 UTF-8。读取 H3C 回显、MIB 和历史日志时，按 `utf-8-sig -> utf-8 -> gb18030 -> gbk` 顺序探测，不得因终端显示乱码直接改写业务数据。

## 数据与发布边界

- 开发运行数据默认位于 `.local/data/` 和 `.local/runtime/`；打包程序优先使用 `%LOCALAPPDATA%\NetConsole\`，不会依赖当前工作目录。
- 主应用数据库（尤其设备管理和 FIT AP 资源）默认保持兼容；会话解析库与可重建分析表可在明确任务范围内重构。
- H3C 私有 MIB 不随仓库分发，需由用户导入合法取得的官方归档或参考资料。
- `resources/tools/` 是主程序和 Agent 随包运行工具的唯一源码来源；构建后交付包内统一使用 `tools/windows-x64/{fping,iperf3}`。根 `tools/` 不再保存 fping/iPerf 运行依赖，IPOP 仅为用户自备外部工具，任何正式包都不得携带 `IPOP.EXE`。
- 发布包必须保留 `_internal`、`data`、`runtime` 目录，以及 PySide6、网络工具和 VC++ 运行库等运行依赖；这些目录是发布包内部契约，不代表开发数据写入源码仓库。
- 构建入口、版本来源、外部工具和 Windows 验证要求见 [构建与发布](docs/BUILD_AND_RELEASE.md)。

## 重点专题

- [Online MR 实时采集](docs/ONLINE_MR_COLLECTION.md)
- [Windows 独立 Go Agent](docs/AGENT.md)
- [Agent Controller](docs/AGENT_CONTROLLER.md)
- [Agent 流量测试协议](docs/AGENT_TRAFFIC_API.md)
- [统一流量测试架构](docs/TRAFFIC_TEST_ARCHITECTURE.md)
- [MR/Mesh 日志分析规则](docs/mr_mesh_log_analysis_rules.md)
- [SNMP Center](docs/SNMP_CENTER.md)
- [AP Identity](docs/AP_IDENTITY.md)
- [表格与 UI 规范](docs/ui_table_guidelines.md)
- [功能模块与 Feature key](docs/FEATURE_MODULES.md)

## 当前规划

Web 演进下一阶段 4C 只接入 Traffic REST API、独立 Traffic WebSocket 和 `/network-tools/traffic` Vue 页面，复用阶段 4B-2 的应用服务与数据边界。之后再依次推进 Online MR、MR/MESH/FIT-AP/轨旁 AP、设备/AC/配置采集。SNMP Center 和无线勘测保持 `DISABLED`，不得顺带迁移；AP Identity 继续只读。
