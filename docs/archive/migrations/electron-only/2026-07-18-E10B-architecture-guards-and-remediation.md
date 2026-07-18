# E10B 架构 Guard 与整改归档

## 归档范围

本归档记录 Electron-only `E10B` 在 2026-07-18 建立九个自动架构门、收敛直接 SQL、分类 UI 命中、登记有限期债务和建立目录职责门的事实。长期规则见[架构一致性审计](../../../ARCHITECTURE_COMPLIANCE.md)，当前汇总结论见[架构一致性报告](ARCHITECTURE_COMPLIANCE_REPORT.md)。

本阶段不等于业务功能验收。真实设备、Electron 多尺寸/多缩放人工检查、由后续独立功能提交收口的设备详情，以及 E11 命令平台/E12 API v1 均不在“Guard 已建立”的完成语义内。

## 初始发现

- 旧报告仍把 Vue、Router、Direct SQL 和孤儿扫描标为 `OPEN_E10_GUARD`，无法作为稳定发布门；
- 生产、维护脚本、分析库和测试中的直接 SQLite 访问没有统一的精确所有权清单；
- Python 分层存在少量历史反向依赖，不能用整层白名单掩盖；
- Vue 可疑函数名、状态色与图表颜色需要 AST/CSS 证据和人工职责分类，不能用字符串命中直接判业务违规；
- 无静态生产调用者的 Service 需要保留候选证据，不能猜测性批量删除；
- 新增目录缺少稳定的 README 完整性门；
- 生产命令迁移只完成首个 Operation，不能把命令扫描通过写成全平台接管。

## 已建立的九个门

统一入口：

```powershell
.\.venv\Scripts\python.exe scripts\architecture\run_all.py
```

| 门 | 入口 | 主要职责 |
| --- | --- | --- |
| 分层边界 | `check_architecture_boundaries.py` | Python、FastAPI Router、TypeScript、Electron Main/Preload 和历史导航字段 |
| 禁用依赖 | `check_forbidden_imports.py` | Qt/PySide/PyQt 活动 import 与依赖回归 |
| Direct SQL | `check_direct_sql_access.py` | SQLite connector 的逐文件所有权与陈旧分类 |
| 设备命令 | `check_device_command_hardcoding.py` | 正式命令 Profile 与严格命令审计 |
| UI 业务逻辑 | `check_ui_business_logic.py` | TypeScript AST 人工分类、主题 Token、状态色与图表色 |
| 移除功能 | `check_removed_features.py` | Qt、SNMP Center、无线勘测等活动入口回归 |
| 运行路径 | `check_runtime_paths.py` | 仓库运行数据、`Path.cwd()` 与目录 README |
| 孤儿模块 | `check_orphan_modules.py` | 无静态生产调用者的 Service 候选 |
| 迁移映射 | `check_migration_map.py` | Qt 删除基线、迁移分类和状态词汇 |

九门共享 AST、配置和确定性诊断实现，但保留各自公开入口和 rule ID。统一入口还拒绝已不再匹配 Finding 的陈旧例外。当前集成记录为 `9/9` 通过；新增目录、代码或分类后必须重新运行受影响单门，最终代码组合再运行统一入口。

## Direct SQL 整改

当前 `config/architecture/direct_sql_access.yaml` 精确登记 61 个文件：

| 分类 | 数量 | 边界 |
| --- | ---: | --- |
| `REPOSITORY_REQUIRED` | 12 | Repository、统一连接工厂或兼容存储 facade |
| `READ_ONLY_DATA_GATEWAY` | 12 | 只读查询/报告数据网关 |
| `ANALYSIS_DB_OWNER` | 6 | 独立会话或分析数据库所有者 |
| `MIGRATION_TOOL` | 2 | 显式维护与 schema 迁移脚本 |
| `TEST_ONLY` | 29 | fixture、准备数据与断言 |
| `VIOLATION` | 0 | 发布阻塞项已清零 |

整改将轨旁光衰、Online MR 诊断及任务只读查询归入永久 Repository 边界；设备数据库备份与完整性校验也收敛到 Repository。分类是精确职责登记，不表示允许 Service 任意新增 SQL；未分类新命中和已不再直接连接的陈旧分类都会失败。

## UI、主题与 Electron 背景

TypeScript AST 当前登记 32 个符号：`DISPLAY_ONLY` 15、`FALSE_POSITIVE` 17；没有 `BUSINESS_LOGIC` 目录级豁免。函数名只用于发现候选，最终结论需要读取实现与测试。

全局主题链已经统一为：

```text
系统设置 theme/theme_color
  -> applySystemAppearance
  -> NetConsole Design Token
  -> App Shell / 侧栏 / Element Plus / ECharts
  -> 严格单向 IPC { resolvedTheme: light | dark }
  -> Electron 预定义窗口背景
```

浅色、深色和跟随系统统一作用于侧栏与内容区，不保留隐式固定深色侧栏；Renderer 不能向 Main 发送任意颜色或窗口参数。四个历史页面的状态色字面量已收敛到语义 Token，`WEB_STATUS_COLOR_TOKEN` 精确例外已全部删除；`check_ui_business_logic.py` 当前为 0 finding / 0 waived。Guard 同时收窄了把 `--nc-text-primary` 等普通文本 Token 误判为状态色的规则，并以单元测试固定。

Electron 浅/深/跟随系统、多尺寸、多缩放视觉验收仍为 `PENDING`；Token、事件、IPC 和 Guard 自动测试不能替代实际视觉通过。

## 精确限时例外

`config/architecture/exceptions.yaml` 当前共 38 条：

| 类型 | 数量 | 处置 |
| --- | ---: | --- |
| Python 分层 | 14 | Core 7、Repository 3、Service 4；逐项迁移并在债务消失时删除例外 |
| 状态色 | 0 | 已收敛到语义 Token并删除例外 |
| 孤儿候选 | 24 | 确认永久入口、接线或删除；不能仅凭静态无调用猜测业务无用 |

每项只能包含 `rule_id/path/reason/owner/created_at/expires_at/test`，并精确匹配当前 Finding。目录通配、缺字段、过期、测试不存在或陈旧例外都会失败关闭。

## 命令平台边界

当前只有 `device.inventory.collect` 进入 `resources/device_command_profiles.json` 的版本化 Profile，并由正式 loader、selector、parser/DTO contract 和严格审计约束。AC、MR、配置、诊断、文件管理及 Agent sidecar 的生产命令仍需 E11 逐域迁移；Huawei/ZTE 或未验证版本必须失败关闭。

九门通过只说明未发现未分类的活动硬编码回归，不能宣称命令平台全量完成。正式 API v1 的版本、弃用、分页、错误和 OpenAPI 合同属于后续 E12。

## 孤儿与目录职责

- 24 个 Service 候选目前只有精确限时例外，没有做猜测性删除；
- 已删除 Qt/MIB/OID 缓存和旧 Shell 由首轮 E10 归档与 Git 历史保存，不建立 `legacy/old/backup` 源码目录；
- 目录门建立时扫描 139 个维护目录，README 缺失为 0；
- README 计数是建立时快照。当前工作树若新增 `components/device-detail`、架构配置或其他目录，必须补齐职责 README 并重新运行目录门，不能沿用旧计数推断通过。

## 测试与证据边界

本阶段已知证据：

- 九个架构公开门统一入口：`9/9`；
- Direct SQL：61 个精确分类、`VIOLATION=0`；
- 例外配置：38 条精确限时记录；
- UI AST：32 个精确符号分类；
- 目录 README：建立时 139 个维护目录、0 缺失。

2026-07-18 的既有全量组合计数保留在[架构一致性报告](ARCHITECTURE_COMPLIANCE_REPORT.md)，不把它们冒充当前工作树的新测试结果。开发期间只运行受影响的定向测试和单门；完整 pytest、完整前端测试/构建、Electron Package Smoke 和最终九门统一入口只在用户解除资源限制后的最终代码组合运行。

真实 AC/MR/交换机、外部终端、SFTP、导入导出和 Electron 视觉验收均需单独记录，Fake 和自动测试不能代替。

## 回滚与资源安全

- Guard、分类和例外都是版本化文本，回滚使用普通 Git revert；不得删除测试、扩大目录例外或改写历史来获得通过；
- Direct SQL 归位没有删除用户数据库、表、字段、会话或 Artifact；如功能回退，先还原对应 Repository/Service 提交，再恢复与实际扫描一致的精确分类；
- 主题回滚必须同时回滚 Renderer Token/Element/ECharts、严格 IPC 和 Electron 预定义背景映射，避免重新形成混合主题；
- 孤儿候选删除必须有调用图、Feature/Registry、测试和业务事实证据；误判时从 Git 恢复具体文件，不建立长期备份目录；
- 设备详情已由后续独立功能提交与定向测试收口，不能以本文作为其完成真实设备或可发布验收证据。

## 后续门

1. 完成设备详情定向测试、架构门、Electron 人工与真实设备验收；
2. 完成 Electron 浅/深/跟随系统、多尺寸、多缩放视觉验收；
3. 逐项处理 14 个 Python 分层债务和 24 个孤儿候选；
4. E11 继续版本化网络设备命令平台；
5. E12 建立正式 `/api/v1` 产品契约；
6. 用户解除 CPU 限制后，在最终代码组合运行全量测试、构建、Package Smoke 和九门统一入口。
