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
| `qt6-polished-ui-skill` | 新建/系统性优化 Qt6 页面、布局与视觉层级 | “优化页面布局”“新建 Fluent 页面” | 单点遮挡、纯后端 |
| `qt6-ui-fix-skill` | 修复现有页面/弹窗遮挡、滚动、主题、表格和卡顿 | “1080p 被遮挡”“弹窗不能滚动” | 全新页面、纯 Excel |
| `qfluentwidgets-netconsole-ui-skill` | QFluentWidgets Shell、主题、CommandBar、图标和 fallback | “主题切换异常”“修复 AppFluentWindow” | 普通 Qt 布局、业务逻辑 |
| `netconsole-qt6-ui-taste-skill` | 工业桌面 UI 的按钮归属、状态完整性和 anti-slop 审查 | “按 Taste 审查 UI”“检查无效按钮” | 默认不实施修改、纯后端评审 |
| `h3c-snmp-mib-skill` | H3C/HH3C MIB、OID、模块依赖、字典和参考表 | “导入 H3C V9 MIB”“OID 不显示” | SNMP 请求调度、CLI parser |
| `snmp-collector-design-skill` | SNMP 请求/采集、并发、取消、缓存和持久化 | “增加 GETBULK”“WALK 无法取消” | MIB 文件、纯 UI |
| `network-command-parser-skill` | H3C/Comware 命令回显、提示符和字段 parser | “解析 display wlan ap all” | MIB、Excel、UI |
| `traffic-test-skill` | fping/iPerf、TCP/UDP、模板、阈值和生命周期 | “修复 fping 丢包”“增加 PIS UDP 模板” | 普通 SSH/路由 |
| `windows-encoding-skill` | Windows 控制台、H3C 输出、文件和 JSONL 编码 | “中文乱码”“GBK 日志导入失败” | i18n 设计、纯解析规则 |
| `netconsole-job-center-skill` | 普通后台 Job、handler、JSONL、进度和取消 | “迁移到 Job Center”“取消后仍运行” | 导出文件、轻量 UI |
| `netconsole-export-report-skill` | Export Process、本地 XLSX/CSV/PDF/ZIP 与文件恢复 | “导出卡 UI”“Excel 列宽不合适” | 实时采集、普通表格样式 |
| `netconsole-online-mr-skill` | 车载 MR 实时采集、Ping/iPerf、原始日志和会话打包 | “Ping 2 自动填错”“停止采集困难” | 离线 MESH 分析 |
| `netconsole-mesh-analysis-skill` | MR 原始 MESH 离线解析、主备链、切换、图表和报告 | “备份链为空”“乒乓判定错误” | 在线 MR SSH、普通 SNMP |
| `netconsole-ap-identity-skill` | AP canonical identity、Radio/BSSID/Peer、shadow 和 diagnostics | “Identity 匹配错误”“评审接管” | 普通 AP 表格/名称显示 |
| `netconsole-project-docs-skill` | README/docs/架构状态同步 | “更新 docs”“同步重构地图” | 一次性报告、无文档影响的实现 |
| `netconsole-data-safety-skill` | SQLite、Repository、目录、备份、迁移和清理 | “增加字段”“数据库 locked”“防止误删” | 纯 UI、无持久化 parser |
| `netconsole-change-review-skill` | 当前 diff 的跨领域只读评审 | “评审本次修改”“看看遗漏” | 直接实现、自动修复 |

## 4. Skill 组合关系

| 主任务 | 主 Skill | 按需组合 |
| --- | --- | --- |
| 新建 Qt 页面 | `qt6-polished-ui-skill` | `qfluentwidgets-netconsole-ui-skill`、`netconsole-job-center-skill` |
| 修复页面/弹窗遮挡 | `qt6-ui-fix-skill` | `netconsole-change-review-skill` |
| Fluent Shell/主题 | `qfluentwidgets-netconsole-ui-skill` | `qt6-polished-ui-skill` |
| UI 质量审查 | `netconsole-qt6-ui-taste-skill` | `netconsole-change-review-skill` |
| 新增普通后台采集 | `netconsole-job-center-skill` | `network-command-parser-skill` |
| 新增本地报告 | `netconsole-export-report-skill` | `netconsole-data-safety-skill` |
| 在线 MR 修改 | `netconsole-online-mr-skill` | `traffic-test-skill`、`network-command-parser-skill` |
| 离线 MESH 分析 | `netconsole-mesh-analysis-skill` | `netconsole-ap-identity-skill`、`netconsole-export-report-skill` |
| H3C MIB/OID | `h3c-snmp-mib-skill` | `snmp-collector-design-skill`、`windows-encoding-skill` |
| SNMP 后台查询 | `snmp-collector-design-skill` | `netconsole-job-center-skill` |
| 数据库/目录升级 | `netconsole-data-safety-skill` | `netconsole-change-review-skill` |
| 完成重要改造 | `netconsole-project-docs-skill` | `netconsole-change-review-skill` |

不要让一个 Skill 无条件加载全部其他 Skills。只有任务真实跨越另一领域时才组合。

## 5. 如何显式调用

在提示开头写 `$skill-name`，后面给出具体目标、范围和验证要求：

```text
$qt6-ui-fix-skill 修复在线 MR 页面在 1280 宽度下参数区和按钮被遮挡的问题，弹窗也必须可横纵滚动。

$netconsole-online-mr-skill 修复单设备选择时 Ping 2 被错误自动填充的问题，不修改 collection_commands.py 中的命令顺序。

$netconsole-job-center-skill 把指定大日志解析迁到 Job Center，保留进度、取消和唯一终态。

$netconsole-export-report-skill 增加后台 XLSX 报告，验证中文列宽、冻结、筛选、文件占用和取消清理。

$h3c-snmp-mib-skill 修复 HH3C 模块导入后 OID 树不显示，并说明旧 MIB 索引兼容性。

$netconsole-change-review-skill 只读评审当前 diff，重点检查 UI 阻塞、SQLite、设备命令和原始日志回归。
```

自然语言中明确出现 Qt6、MIB、GETBULK、Job Center、Online MR、MESH、AP Identity、iperf3、fping、乱码等触发词时，Codex 也应自动选择相应 Skill。

## 6. 如何升级 Skill

1. 先读当前生产代码、测试、diff、文档和近期提交，不从旧 Skill 推断事实。
2. 使用 `$skill-creator` 原位更新现有目录；不要创建同义新 Skill。
3. 保留仍正确的规则，删除冲突、过期路径和已失真的“已实现”描述。
4. 让 description 前半段包含真实触发词、使用场景和不适用范围。
5. 每个 Skill 保持单一职责，并包含触发/反例、输入输出、生产代码权限、工作流、验证和失败报告。
6. 只在重复、确定且可安全复用时增加标准库脚本；不创建空资源目录。

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
- MIB/OID 资源与 SNMP 请求/采集分离。
- 在线 MR 与离线 MESH 分析分离。
- 普通 Job 与文件导出分离。
- CLI Parser 与编码边界分离。
- AP Identity 与普通 AP 展示分离。
- 新需求先扩展现有 Skill；只有职责不能自然归入且会重复出现时才新建。

## 9. 当前架构状态提示

- `netconsole/services/job_center/handlers/legacy_tasks.py` 仍是兼容区，只迁出、不迁入；不能写成全部任务已迁移。
- AP Identity 当前主要是 canonical 工具、shadow comparison 和只读 diagnostics；不能写成已全面接管生产匹配。
- 当前执行端仍为本地 Worker Process，没有完整 Windows/CentOS/Go/远程 Agent 生产实现。
- 本地 XLSX 格式优化在范围内；WPS 云服务、WPS API、KDocs 和在线同步默认不在范围内。

## 10. 后续候选 Skills

可在生产代码真正落地后再评估：

- Agent 管理。
- Go Agent。
- CentOS 离线部署 Agent。
- 远程 iPerf Agent。

当前仓库尚无完整生产实现，不在本轮创建 Skill。
