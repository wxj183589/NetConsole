# 项目概览

## 项目定位

NetConsole 是面向网络设备运维的 Windows 本地桌面工具。当前重点服务以下场景：

- H3C 网络设备管理、连接测试、详情采集和配置备份。
- 无线 AC、FIT-AP、轨旁 AP、车载 MR 的采集、解析、诊断和报表。
- 轨道交通 PIS / 信号无线网络现场分析。
- 本地文件管理、网络工具、无线扫描、iPerf / fping 等辅助诊断。

项目不能把某个局点、线路、站点、车号、AP、AC、MR、MAC、IP 或用户本机路径写成规则。任何业务规则都应可跨局点复用。

## 当前技术栈

以当前代码为准：

- UI：PySide6 / Qt Widgets。
- 本地存储：SQLite、JSON 配置、站点隔离目录。
- 设备连接：Netmiko、SSH / Telnet、SFTP / SCP、外部终端集成。
- Excel：本地 `.xlsx` 导入导出，主要面向 WPS Office / Microsoft Office 打开体验。
- 图表：当前项目内既有 Qt / Matplotlib / 交互图表相关实现，具体以页面代码为准。
- 打包：PyInstaller / Nuitka 双后端，发布脚本在 `scripts/build/` 下。

历史上如讨论过 React、Electron、FastAPI 或其他原型，均不得写成当前架构。当前仓库的正式桌面主线是 PySide6。

## 当前入口

- 应用入口：`main.py`
- 主窗口：`src/netconsole/ui/main_window.py`
- 应用启动：`src/netconsole/app.py`
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
| `src/netconsole/ui/` | PySide6 页面、对话框、Worker、控件、主题 |
| `src/netconsole/build/` | 构建辅助 |
| `scripts/build/` | 发布脚本、构建配置 |
| `tests/` | pytest 回归测试 |
| `resources/tools/` | 版本化的 fping/iPerf 运行工具唯一源码来源 |
| `tools/` | 开发、诊断、维护和协议分析工具，不作为运行时工具来源 |

独立应用位于 `apps/agent/`、`apps/desktop/` 和 `apps/web/`；Agent 的示例配置位于 `apps/agent/resources/config/`，运行数据和构建产物分别位于 `.local/agent/`、系统应用数据目录和 `dist/agent/`。

## 模块边界

- UI 页面负责展示、交互和调度 Worker，不应承载核心解析规则。
- 采集、解析、状态判断、导入导出应优先放在 `services/`、`parsers/` 或 `core/`。
- SQLite 访问通过 repository 层，不在 UI 里散写 SQL。
- 路径必须通过 `PathResolver` 或现有路径服务，不散落字符串拼接。
- 功能开关集中在 `FeatureGate` 和注册表中，不在页面内散落一次性开关判断。

## 当前实现与待统一事项

- 旧编号文档中的部分数据库表说明早于当前 AC、轨道交通、在线 MR 和功能开关实现；后续以当前 `database.py`、repository 和专题文档为准逐步统一。
- 项目存在中文界面和部分英文技术名混合的历史内容；新增 UI 文案和文档默认使用中文。
