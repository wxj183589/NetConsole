# NetConsole 项目级 Codex Skills

## 1. 存放位置

仓库级 Skills 统一位于：

```text
.agents/skills/<skill-name>/SKILL.md
```

这些文件位于仓库目录，不写入用户全局 Skill 目录。本项目当前 Skills 默认是 instruction-only，不为完整感创建空的 `scripts/`、`references/`、`assets/` 或 `agents/`。

`.agents/skills` 已纳入 Git，用于在本地仓库、远端分支和其他开发环境之间共享同一套 Codex 工作流。

## 2. 与 AGENTS.md 的区别

- `AGENTS.md`：每次任务都应知道的稳定全局约束和简短路由。
- `SKILL.md`：特定领域被触发后才加载的详细流程、边界和验证方法。
- 本文：面向维护者的 Skill 清单、组合关系、调用和升级说明。

## 3. 当前 Skill 清单

| Skill | 职责 | 常见触发 | 不应触发 |
| --- | --- | --- | --- |
| `network-command-parser-skill` | H3C/Comware 命令回显、提示符和字段 parser | “解析 display wlan ap all” | 设备管理 SNMP、Excel、UI |
| `traffic-test-skill` | fping/iPerf、TCP/UDP、模板、阈值和生命周期 | “修复 fping 丢包”“增加 PIS UDP 模板” | 普通 SSH/路由 |
| `windows-encoding-skill` | Windows 控制台、H3C 输出、文件和 JSONL 编码 | “中文乱码”“GBK 日志导入失败” | i18n 设计、纯解析规则 |
| `netconsole-job-center-skill` | 普通后台 Job、handler、JSONL、进度和取消 | “迁移到 Job Center”“取消后仍运行” | 导出文件、轻量 UI |
| `netconsole-user-file-interaction-skill` | 用户可见文件选择、任务绑定、Artifact 最终保存和导入取消边界 | “导入文件”“下载模板”“另存 Artifact”“Save As 失败重试” | Worker 内部生成、SFTP 受管下载实现、数据库业务 |
| `netconsole-export-report-skill` | Export Process、本地 XLSX/CSV/PDF/ZIP 与文件恢复 | “导出卡 UI”“Excel 列宽不合适” | 实时采集、普通表格样式 |
| `netconsole-ac-management-skill` | AC/FIT-AP、强类型动作、确认审计和 OmniPeek 名称表 | “固化新 AP”“导出 .nam” | 普通设备管理、无 AC 作用域的 Identity |
| `netconsole-train-communication-skill` | 点表、TC1/TC2、离线可测、部分失败与 VRRP 边界 | “离线列车不能检测”“VRRP 主端残留” | Online MR 实时采集、列车在线页 |
| `netconsole-device-files-skill` | SSH/SFTP 能力、主机密钥、下载队列和 `.part` | “SSH 通但 SFTP 失败”“队列恢复慢” | 普通 SSH、配置采集 |
| `netconsole-config-collection-skill` | 快照选择、两文件对比、裁剪、双栏 Diff 与导出 | “勾选两个文件不能对比” | AC 快照、普通文本 diff |
| `netconsole-online-mr-skill` | 车载 MR 实时采集、Ping/iPerf、原始日志和会话打包 | “Ping 2 自动填错”“停止采集困难” | 离线 MESH 分析 |
| `netconsole-agent-skill` | Windows Go Agent V1、HTTP API、内嵌 Web、配置/targets、工具、MR sidecar、构建和运行目录 | “修改 Agent API”“Agent 构建失败”“工具路径或运行数据不对” | CentOS 离线部署；纯流量参数；纯 MR 命令规则 |
| `netconsole-mesh-analysis-skill` | MR 原始 MESH 离线解析、主备链、切换、图表和报告 | “备份链为空”“乒乓判定错误” | 在线 MR SSH、普通 SNMP |
| `netconsole-ap-identity-skill` | AP canonical identity、Radio/BSSID/Peer、shadow 和 diagnostics | “Identity 匹配错误”“评审接管” | 普通 AP 表格/名称显示 |
| `netconsole-project-docs-skill` | README/docs/架构状态同步 | “更新 docs”“同步重构地图” | 一次性报告、无文档影响的实现 |
| `netconsole-data-safety-skill` | SQLite、Repository、目录、备份、迁移和清理 | “增加字段”“数据库 locked”“防止误删” | 纯 UI、无持久化 parser |
| `netconsole-change-review-skill` | 当前 diff 的跨领域只读评审 | “评审本次修改”“看看遗漏” | 直接实现、自动修复 |

## 4. Skill 组合关系

| 主任务 | 主 Skill | 按需组合 |
| --- | --- | --- |
| 新增普通后台采集 | `netconsole-job-center-skill` | `network-command-parser-skill` |
| 新增用户可见任务型报告 | `netconsole-user-file-interaction-skill` | `netconsole-export-report-skill`、`netconsole-data-safety-skill` |
| 修改 Export Worker 内部报告生成 | `netconsole-export-report-skill` | `netconsole-data-safety-skill` |
| AC 受控动作/NAM | `netconsole-ac-management-skill` | `netconsole-job-center-skill`、`netconsole-export-report-skill` |
| 车内通信检测 | `netconsole-train-communication-skill` | `netconsole-job-center-skill`、`network-command-parser-skill` |
| 设备文件/SFTP | `netconsole-device-files-skill` | `netconsole-job-center-skill`、`netconsole-data-safety-skill` |
| 配置快照对比 | `netconsole-config-collection-skill` | `netconsole-job-center-skill`、`netconsole-export-report-skill` |
| 在线 MR 修改 | `netconsole-online-mr-skill` | `traffic-test-skill`、`network-command-parser-skill` |
| Agent API/构建/工具路径 | `netconsole-agent-skill` | `netconsole-project-docs-skill` |
| Agent 流量任务 | `netconsole-agent-skill` | `traffic-test-skill` |
| Agent Online MR sidecar | `netconsole-agent-skill` | `netconsole-online-mr-skill` |
| Agent 文档同步 | `netconsole-agent-skill` | `netconsole-project-docs-skill` |
| 离线 MESH 分析 | `netconsole-mesh-analysis-skill` | `netconsole-ap-identity-skill`、`netconsole-export-report-skill` |
| 数据库/目录升级 | `netconsole-data-safety-skill` | `netconsole-change-review-skill` |
| 完成重要改造 | `netconsole-project-docs-skill` | `netconsole-change-review-skill` |

不要让一个 Skill 无条件加载全部其他 Skills。只有任务真实跨越另一领域时才组合。

## 5. 如何显式调用

在提示开头写 `$skill-name`，后面给出具体目标、范围和验证要求：

```text
$netconsole-online-mr-skill 修复单设备选择时 Ping 2 被错误自动填充的问题，不修改 collection_commands.py 中的命令顺序。

$netconsole-job-center-skill 把指定大日志解析迁到 Job Center，保留进度、取消和唯一终态。

$netconsole-user-file-interaction-skill 为已有 Artifact 增加用户主动“另存为”，复用 Main 授权路径和共享协调器。

$netconsole-export-report-skill 增加后台 XLSX 报告，验证中文列宽、冻结、筛选、文件占用和取消清理。

$netconsole-change-review-skill 只读评审当前 diff，重点检查 UI 阻塞、SQLite、设备命令和原始日志回归。
```

自然语言中明确出现用户可见导入/导出、模板下载、报告保存、Artifact 另存、Save As/Open/File/Folder 选择、Task Center 保存失败重试、Job Center、Online MR、MESH、AP Identity、iperf3、fping、乱码等触发词时，Codex 也应自动选择相应 Skill。任务型报告通常同时加载 `netconsole-user-file-interaction-skill` 和 `netconsole-export-report-skill`：前者负责用户选择和最终落盘，后者负责 Export Process、格式与内部 Artifact。

## 6. 如何升级 Skill

1. 先读当前生产代码、测试、diff、文档和近期提交，不从旧 Skill 推断事实。
2. 使用 `$skill-creator` 原位更新现有目录；不要创建同义新 Skill。
3. 保留仍正确的规则，删除冲突、过期路径和已失真的“已实现”描述。
4. 让 description 前半段包含真实触发词、使用场景和不适用范围。
5. 每个 Skill 保持单一职责，并包含触发/反例、输入输出、生产代码权限、工作流、验证和失败报告。
6. 只在重复、确定且可安全复用时增加标准库脚本；不创建空资源目录。
7. Skill 被退役架构或删除模块完全取代、且不再有活动触发面时删除目录；只因内容陈旧不得删除，应原位修正并同步所有索引。

## 7. 如何验证 Skill

每次升级至少检查：

- 每个目录有 `SKILL.md`，且 YAML front matter 只有 `name`、`description`。
- front matter 可解析、name 与目录一致且全仓库唯一。
- description 明确触发和不适用场景。
- 代码/文档相对路径存在，不含开发机绝对路径、真实凭据、IP 或 MAC。
- 没有重复职责、空资源目录、`__pycache__` 或 `.pyc`。
- `docs/CODEX_SKILLS.md`、`docs/README.md` 和 `AGENTS.md` 路由一致。
- `git diff --check` 通过；只报告实际执行的验证。

可使用官方 Skill 校验器逐项检查：

```powershell
.\.venv\Scripts\python.exe <skill-creator>/scripts/quick_validate.py .agents/skills/<skill-name>
```

`<skill-creator>` 表示当前 Codex 提供的 skill-creator 位置，不应把开发机绝对路径写进仓库文档。

## 8. 如何避免重复

- UI 设计、UI 缺陷、Fluent 集成和 UI 审查分别由四个边界明确的 Skill 负责。
- 在线 MR 与离线 MESH 分析分离。
- 普通 Job 与文件导出分离。
- CLI Parser 与编码边界分离。
- AP Identity 与普通 AP 展示分离。
- 新需求先扩展现有 Skill；只有职责不能自然归入且会重复出现时才新建。

## 9. 当前架构状态提示

- `src/netconsole/services/job_center/handlers/legacy_tasks.py` 仍是兼容区，只迁出、不迁入；不能写成全部任务已迁移。
- AP Identity 当前主要是 canonical 工具、shadow comparison 和只读 diagnostics；不能写成已全面接管生产匹配。
- Windows Go Agent V1 已位于 `apps/agent/`，包含 HTTP API、内嵌 Web、iPerf/fping、MR sidecar、目标管理、任务事件和采集包；Python Controller 已接入 Traffic，并提供默认关闭的单 Agent Online MR start/status/normal stop 与安全包导入。
- 普通 Job Center 仍以本地 Worker Process 为主；Windows Go Agent 是独立执行端，通过 Controller/Traffic 适配接入，不等同于 Job Center 完全远程化。CentOS 离线部署、主动注册、多 Controller 和完整 Traffic Web 页面仍未完成。
- 本地 XLSX 格式优化在范围内；WPS 云服务、WPS API、KDocs 和在线同步默认不在范围内。

## 10. 过期 Skill 审计与后续候选

2026-07-23 按当前代码路径和触发面审计既有 12 个 Skill：没有 Skill 被退役 Qt 架构、已删除 SNMP Center 或无线勘测完全取代，因此本轮无安全删除项；陈旧内容按原职责更新。新增上述四个重复且高风险的领域 Skill 后，应继续优先扩展现有目录，避免同义 Skill。

当前仅保留以下后续候选：

- CentOS 离线部署 Agent。
- 远程 Agent 批量运维。
- Agent 发布、签名和许可证检查流程。
