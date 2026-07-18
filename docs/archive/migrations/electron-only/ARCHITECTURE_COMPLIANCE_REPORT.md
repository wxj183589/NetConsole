# Electron-only 架构一致性报告

## 结论

本报告记录 2026-07-18 当前分支的 E10 收口事实。Qt 活动源码、入口、运行依赖与发布链已删除；本轮进一步回收了遗留 Qt/MIB/OID 字节码缓存、七处 Qt offscreen 测试环境设置、旧命令路径引用、过时迁移文档和项目 Skill 中的失效 UI 路径，并建立[最终迁移矩阵](../../../architecture/MIGRATION_MATRIX.md)。

该结论是“Electron-only 架构成立”，不是“所有业务已完成真实设备验收”。AC、轨道交通、配置、文件、网络工具等仍按矩阵保留 `PARTIAL`、`IMPLEMENTED_UNVERIFIED` 或 `REAL_DEVICE_PENDING`。E2 最终制品合规与自动化组合门已通过；现场验收完成前仍不得把相应模块标记为 `COMPLETE`。

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

## 最终自动化组合证据

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
| Vue/Electron UI 业务逻辑 | `OPEN_E10_GUARD` | 本轮未新增或搬移业务逻辑；完整 AST/启发式 Guard 仍按 `ARCHITECTURE_COMPLIANCE.md` 执行 |
| Router 业务逻辑与直接 SQL | `OPEN_E10_GUARD` | 既有 API 边界审计不因文档清理自动升级；最终发布前仍需全量复跑 |
| 设备命令硬编码 | `PARTIAL` | `device.inventory.collect` 已进入版本化 Profile；AC/MR/配置/文件等逐域迁移仍是活动技术债务 |
| Core 反向依赖 | `PASS`（Qt） | 永久层无 Qt 反向依赖；Electron/FastAPI 全边界由后续 Guard 复验 |
| 孤儿代码/资源 | `PASS`（本轮范围） | Qt cache 和兼容 Shell 已回收；未对非 Qt Service 做扩大删除 |
| 数据库所有权 | `NOT_CHANGED` | 本轮不改 schema、Repository、数据路径或用户数据 |
| API/OpenAPI | `NOT_CHANGED` | 本轮不改 API 契约；生产 OpenAPI 仍关闭，开发态受 loopback/会话保护 |
| 删除功能 | `PASS` | SNMP Center、MIB/OID、SNMPv3 和无线勘测无活动入口；设备 SNMP v1/v2c 与无线扫描独立保留 |
| 目录 README/运行路径 | `NOT_CHANGED` | 由 E1～E6A 与仓库目录 Guard 继续约束 |
| 版本化 Command Profile | `PARTIAL` | 首个 inventory 操作完成，其余生产域不得误报全量接管 |

## Qt 文字分类

后续扫描必须区分三类，不能机械删除：

1. **活动残留（必须失败）**：生产 import、依赖、入口、运行分支、Qt 插件/许可证或发布文件。
2. **历史归档（允许）**：`docs/archive/**`、Changelog 和迁移兼容指针中的明确过去时描述。
3. **负向 Guard（允许）**：构建脚本和测试中用于拒绝 `PySide6/PyQt/QFluentWidgets/qt.conf` 的字符串。

Navigation Registry 的 `qt_page_id/qt_feature_id` 是历史映射字段，当前不加载任何 Qt 模块；若后续重命名，应独立做 schema 迁移，不能在本轮破坏前端契约。

## 未解决项与发布门

| 级别 | 未解决项 | 处理边界 |
| --- | --- | --- |
| P1 | 多个业务模块缺少 Electron 人工或真实设备验收 | 保持矩阵状态，不标记 `COMPLETE` |
| P2 | Vue/Router/SQL/命令/孤儿模块的完整 E10 Guard 套件仍需按规则文档落地并复跑 | 不允许目录级忽略；命中逐项分类 |
| P2 | Navigation Registry 仍使用历史字段名 `qt_page_id/qt_feature_id` | 只作追踪元数据；以后以独立 schema 迁移处理 |

因此，本轮遗留清理、活动文档/Skill 事实源、最终迁移矩阵和自动化组合证据已经收口；Electron-only 架构事实已经形成，但真实设备/桌面人工验收与完整 E10 静态 Guard 仍受以上 P1/P2 约束。
