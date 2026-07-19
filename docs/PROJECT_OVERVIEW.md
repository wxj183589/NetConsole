# 项目概览

> 本文描述当前 Electron-only 产品。正式桌面入口以 [README](../README.md)、[Electron Desktop](ELECTRON_DESKTOP.md) 和 [当前架构](ARCHITECTURE.md) 为准；Qt 历史行为只通过 Git 与[最终迁移矩阵](architecture/MIGRATION_MATRIX.md)追溯。

系统设置包含局点 Registry、全局数据根、迁移、备份恢复和 `.ncsite` 导入导出。正式逻辑位于 Python Core，Electron Main 不承载数据迁移；设计与安全边界见 [局点与数据存储](storage/README.md)。

## 项目定位

NetConsole 是面向网络设备运维的 Windows 本地桌面工具。当前重点服务以下场景：

- H3C 网络设备管理、连接测试、详情采集和配置备份。
- 无线 AC、FIT-AP、轨旁 AP、车载 MR 的采集、解析、诊断和报表。
- 轨道交通 PIS / 信号无线网络现场分析。
- 本地文件管理、网络工具、无线扫描、iPerf / fping 等辅助诊断。

项目不能把某个局点、线路、站点、车号、AP、AC、MR、MAC、IP 或用户本机路径写成规则。任何业务规则都应可跨局点复用。

## 当前技术栈

以当前代码为准：

- UI：Vue 3/TypeScript/Vite 由 Electron Renderer 承载；Electron Main/Preload 只提供桌面生命周期和白名单本机能力。
- 本地存储：SQLite、JSON 配置、站点隔离目录。
- 设备连接：Netmiko、SSH / Telnet、SFTP / SCP、外部终端集成。
- Excel：本地 `.xlsx` 导入导出，主要面向 WPS Office / Microsoft Office 打开体验。
- 图表：Vue 页面使用 ECharts 和 NetConsole Design Token；Python 无界面报告按既有服务使用 Matplotlib `Agg` 后端。
- 打包：Electron Builder 负责桌面制品，PyInstaller 只冻结受管 Python Backend；发布脚本位于 `scripts/build/`。

Electron + Vue + FastAPI/Python Core 是当前正式桌面架构。Qt/PySide6/QFluentWidgets 源码、运行时、入口和发布链已经删除，不得重新引入。

全局外观由系统设置中的 `theme / theme_color` 驱动，`applySystemAppearance -> NetConsole Design Token -> App Shell / Element Plus / ECharts` 是唯一 Renderer 主题链；解析后的 `light|dark` 再通过严格白名单单向 IPC 同步 Electron 窗口背景。浅色、深色和跟随系统统一作用于侧栏与内容区，不维护固定深色侧栏或第二套主题持久化。当前自动契约已建立，Electron 多尺寸、多缩放和 Windows 跟随系统的视觉验收仍待人工完成。

## 当前入口

- 正式桌面入口：`apps/desktop_electron/`
- PyCharm/源码桌面入口：无参数 `main.py`（启动同一 Electron 开发编排）；带内部参数时承接受管 Backend、Worker 和开发诊断
- 历史迁移映射：`docs/architecture/MIGRATION_MATRIX.md`
- 路径管理：`src/netconsole/core/paths.py`
- 站点管理：`src/netconsole/core/sites.py`
- 数据库初始化：`src/netconsole/core/database.py`
- 功能开关：`src/netconsole/core/feature_registry.py`、`src/netconsole/core/feature_flags.py`

开发环境启动示例：

```powershell
.\.venv\Scripts\python.exe .\main.py
```

这是开发环境示例，不是硬编码路径要求。

## 主要代码分层

| 目录 | 角色 |
| --- | --- |
| `src/netconsole/core/` | 启动、路径、站点、数据库、设置、功能开关、运行环境 |
| `src/netconsole/models/` | 数据模型 |
| `src/netconsole/repositories/` | SQLite 持久化访问 |
| `src/netconsole/services/` | 采集、解析、导入导出、业务规则、外部工具 |
| `src/netconsole/parsers/` | H3C / AC / Mesh / 文本输出解析 |
| `apps/desktop_electron/` | Electron Main/Preload、窗口与受管 Backend 生命周期 |
| `apps/web/` | 唯一 Vue Renderer、Element Plus/ECharts 与设计 Token |
| `src/netconsole/build/` | 构建辅助 |
| `scripts/build/` | 发布脚本、构建配置 |
| `tests/` | pytest 回归测试 |
| `resources/tools/` | 版本化的 fping/iPerf 运行工具唯一源码来源 |
| `tools/` | 开发、诊断、维护和协议分析工具，不作为运行时工具来源 |

独立应用位于 `apps/agent/`、`apps/desktop_electron/` 和 `apps/web/`。Agent 的示例配置位于 `apps/agent/resources/config/`，运行数据和构建产物分别位于 `.local/agent/`、系统应用数据目录和 `dist/agent/`。

## 模块边界

- Vue 页面只负责展示、交互、轻量校验和调用 API，不应承载设备、数据库、采集或业务状态机。
- 采集、解析、状态判断、导入导出应优先放在 `services/`、`parsers/` 或 `core/`。
- SQLite 访问通过 repository 层，不在 UI 里散写 SQL。
- 路径必须通过 `PathResolver` 或现有路径服务，不散落字符串拼接。
- 功能开关集中在 `FeatureGate` 和注册表中，不在页面内散落一次性开关判断。
- 主题基础色、状态色和图表色统一来自 NetConsole Design Token；页面不得重新定义全局 Element Plus 色板或把任意颜色通过 IPC 传给 Electron。

## 当前实现与待统一事项

- 旧编号文档中的部分数据库表说明早于当前 AC、轨道交通、在线 MR 和功能开关实现；后续以当前 `database.py`、repository 和专题文档为准逐步统一。
- 项目存在中文界面和部分英文技术名混合的历史内容；新增 UI 文案和文档默认使用中文。
