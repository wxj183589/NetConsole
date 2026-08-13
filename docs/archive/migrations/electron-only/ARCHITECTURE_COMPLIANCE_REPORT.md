# Electron-only 架构一致性报告

> 冻结历史基线：本文记录 2026-07 Electron-only 收敛时的检查结果和未验收边界，不代表当前文件数量、例外数量或功能状态。当前规则与结果以生产代码、机器可读配置、测试和 [架构一致性](../../../architecture/COMPLIANCE.md) 为准。

## 结论

本报告记录 2026-07-18 起当前分支的 E10/E10B 收口事实。Qt 活动源码、入口、运行依赖与发布链已删除；首轮回收了遗留 Qt/MIB/OID 字节码缓存、七处 Qt offscreen 测试环境设置、旧命令路径引用、过时迁移文档和项目 Skill 中的失效 UI 路径，并建立[冻结迁移矩阵](../qt-to-electron/MIGRATION_MATRIX.md)。九门 Guard、精确分类与整改结论已汇总在本文，逐提交过程由 Git 历史保留。

在首轮清理之后，E10B 已建立九个公开架构门及精确配置：Direct SQL 61 个文件全部分类且 `VIOLATION=0`，38 条限时例外精确到规则和文件，建立目录门时 139 个维护目录 README 缺失为 0。该结论是“Electron-only 架构 Guard 基线成立”，不是“所有业务已完成真实设备验收”。AC、轨道交通、配置、文件、网络工具和随后完成定向自动验证的设备详情仍按矩阵保留 `PARTIAL`、`IMPLEMENTED_UNVERIFIED` 或 `REAL_DEVICE_PENDING`；Electron 主题最终视觉验收也仍为 `PENDING`。

## 本轮证据

| 检查 | 结果 | 证据/处理 |
| --- | --- | --- |
| Qt 受跟踪源码与入口 | `PASS` | `src/netconsole/ui/`、`apps/desktop/`、Qt probe/Adapter 已由历史提交删除；当前生产扫描无 Qt import |
| 忽略目录旧字节码 | `PASS` | 删除仓库内仅含 `.pyc` 的 `src/netconsole/ui/**/__pycache__`（302 文件）与 `apps/desktop/__pycache__`（2 文件）；已验证绝对路径在仓库内，未触碰 `.venv`、`dist/build` 或 `.local` 用户数据 |
| 已删除 MIB/OID 字节码 | `PASS` | 删除 `src/netconsole/services`、`repositories`、`models` 下 18 个无源码消费者的 MIB/OID `.pyc`；受跟踪树中不存在 MIB/OID/SNMPv3 实现，历史用户 `.local/data/global/mibs` 明确保留 |
| Qt 测试环境 | `PASS` | 从 7 个纯 Python 业务测试移除 `QT_QPA_PLATFORM=offscreen` 及无用 `os` import |
| 删除文件过时引用 | `PASS` | `docs/JOB_CENTER.md` 改为真实路径 `src/netconsole/services/online_mr/collection_commands.py` |
| 旧 Qt 架构文档 | `PASS` | 编号文档、Web 迁移计划/矩阵及逐模块 parity 文档降为历史兼容指针；原文由 Git 保存 |
| 活动工程规范 | `PASS` | `PROJECT_OVERVIEW`、源码目录 README、Online MR README、开发历史、Job/后台任务、Renderer 响应性、表格、导出、开发工作流、AC/Online MR/AP Identity 等现行文档和 8 个项目 Skill 已切换为 Electron/Vue/Application Service 事实；文档 Guard 覆盖活动 README/Skill 的旧 Qt 当前时态和已删除路径 |
| 最终迁移映射 | `PASS` | `docs/architecture/MIGRATION_MATRIX.md` 按历史路径组记录分类、新位置、测试、删除依据和当前验收状态 |
| 九个架构门 | `PASS`（当前基线） | `scripts/architecture/run_all.py` 汇总分层、禁用依赖、直接 SQL、设备命令、UI 逻辑、移除功能、运行路径、孤儿模块和迁移映射九门；每门保留独立 rule ID |
| Direct SQL | `PASS` | 61 个精确文件分类：Repository 12、只读网关 12、分析库所有者 6、迁移工具 2、测试 29；`VIOLATION=0` |
| UI 与主题 | `PASS`（自动 Guard） | 32 个 AST 符号已人工分类；状态色已收敛到语义 Token，`check_ui_business_logic.py` 为 0 finding / 0 waived；最终 Electron 视觉验收仍待执行 |
| 架构例外 | `PASS_WITH_DEBT` | 38 条精确限时例外：Python 分层 14、孤儿候选 24、状态色 0；禁止目录通配，过期或陈旧例外会使 Guard 失败 |
| 目录职责 | `PASS`（建立时快照） | 建立门禁时 139 个维护目录、0 个 README 缺失；当前工作树新增目录必须在最终组合重新检查 |

## 已知自动化组合证据

以下计数来自 2026-07-18 已完成的组合基线，不包含随后独立收口的设备详情；设备详情已有单独的定向测试记录，但本文不猜测尚未运行的最终新全量总数，也不把自动验证替代 Electron 视觉验收：

- Python 全量：`2052 passed, 1 skipped`；跳过项是既有环境条件，不是失败。
- Vue：62 个测试文件、191 项测试通过，TypeScript 检查与生产构建通过；现有 ECharts 已接入主题重绘事件。
- Electron：13 个测试文件、89 项测试通过，typecheck、main/preload 构建和最终 Package Smoke 通过。
- PyInstaller/Electron 制品：本地 Electron distribution、Qt-free、NOTICE、SBOM、PyInstaller inventory、Backend 启停和退出清理通过。
- Agent：MR sidecar、console/tray、Go 全量测试和交付目录本地 fping/iPerf3 复验通过。
- 依赖与文档：`pip check` 通过；文档/迁移 Guard 29 项通过；本次修改的 Python 文件 Ruff check/format 通过。全仓 Ruff 仍有 37 项既有问题，未由本轮扩大。

## 架构审计清单

| 域 | 状态 | 说明 |
| --- | --- | --- |
| Qt 删除完整性 | `PASS` | 活动生产代码无 Qt import；构建/测试中的 Qt 文字只用于负向阻断 |
| 已删除 Qt 业务逻辑去向 | `PASS_WITH_PENDING_VALIDATION` | 路径组已映射；业务现场状态按矩阵保留，不把自动测试当真实验收 |
| Vue/Electron UI 业务逻辑 | `PASS`（当前 Guard） | TypeScript AST 分类为 `DISPLAY_ONLY` 15、`FALSE_POSITIVE` 17；状态色例外已归零，普通文本 Token 的误报规则已收窄并有单元测试，未把启发式命中自动当成业务违规 |
| Router 业务逻辑与直接 SQL | `PASS`（当前 Guard） | Router 边界与 Direct SQL 门已建立；61 个文件精确分类且 `VIOLATION=0`。API v1 正式产品契约仍属于 E12，不能由本项推断完成 |
| 设备命令硬编码 | `PARTIAL` | `device.inventory.collect` 已进入版本化 Profile；AC/MR/配置/文件等逐域迁移仍是活动技术债务 |
| Core 反向依赖 | `PASS_WITH_EXCEPTIONS` | 永久层无 Qt 反向依赖；14 个历史 Python 分层债务均精确登记责任域、到期日和测试，不允许扩大例外 |
| 孤儿代码/资源 | `PASS_WITH_EXCEPTIONS` | Qt cache 和兼容 Shell 已回收；24 个无静态生产调用者候选保留精确限时例外，需逐项确认入口或删除，未进行猜测性批量回收 |
| 数据库所有权 | `NOT_CHANGED` | 本轮不改 schema、Repository、数据路径或用户数据 |
| API/OpenAPI | `PASS`（设备详情定向） | 设备详情公开 DTO/OpenAPI 已移除不再展示的冗余关联字段，定向 API 契约测试通过；生产 OpenAPI 仍关闭，开发态受 loopback/会话保护 |
| 删除功能 | `PASS` | SNMP Center、MIB/OID、SNMPv3 和无线勘测无活动入口；设备 SNMP v1/v2c 与无线扫描独立保留 |
| 目录 README/运行路径 | `PASS`（建立时快照） | 建立 Guard 时 139 个维护目录 README 0 缺失；运行路径和仓库数据门由 `check_runtime_paths.py` 约束，新增目录需最终组合复跑 |
| 版本化 Command Profile | `PARTIAL` | 首个 inventory 操作完成，其余生产域不得误报全量接管 |

## Qt 文字分类

后续扫描必须区分三类，不能机械删除：

1. **活动残留（必须失败）**：生产 import、依赖、入口、运行分支、Qt 插件/许可证或发布文件。
2. **历史归档（允许）**：`docs/archive/**`、Changelog 和迁移兼容指针中的明确过去时描述。
3. **负向 Guard（允许）**：构建脚本和测试中用于拒绝 `PySide6/PyQt/QFluentWidgets/qt.conf` 的字符串。

Navigation Registry 的活动注册项已迁移为 `legacy_page_id/legacy_feature_id`；历史 `qt_page_id/qt_feature_id` 只用于 schema v1 读取兼容与负向测试，规范化后不会进入活动导航项，也不加载任何 Qt 模块。历史文字只允许出现在归档、迁移矩阵和负向 Guard 中。

## 未解决项与发布门

| 级别 | 未解决项 | 处理边界 |
| --- | --- | --- |
| P1 | 多个业务模块仍缺少 Electron 人工或真实设备验收；设备详情仅完成定向自动验证 | 保持矩阵状态，不标记 `COMPLETE`，继续执行 Electron/真实设备验收 |
| P1 | 全局主题尚未完成 Electron 多尺寸、多缩放与 Windows 跟随系统视觉验收 | 自动测试只证明 Token、事件和严格 IPC 契约，人工结果单独记录 |
| P2 | 14 个 Python 分层债务与 24 个孤儿候选 | 逐项迁移、接线或删除；例外到期或陈旧时 Guard 失败 |
| P2 | Command Profile 当前仅接管 `device.inventory.collect` | E11 逐域迁移；E12 另行完成正式 API v1 契约，不能在 E10B 报告中提前完成 |

因此，遗留清理、活动文档/Skill 事实源、冻结迁移矩阵和 E10B 九门 Guard 基线已经形成；Electron-only 架构事实成立，状态色自动 Guard 和设备详情定向自动验证已收口，但 Electron 主题人工视觉验收、真实设备/桌面人工验收、E11 命令平台扩展和 E12 API 契约仍受以上 P1/P2 约束。
