# 架构 Guard

本目录实现 E10B Electron-only 架构合规 Guard。九个公开入口共享 Python AST、TypeScript AST、CSS 解析、例外校验和确定性诊断实现，但每项边界保留独立 rule ID；共享引擎不表示合并或缺少发布门。

Guard 只读取生产代码、测试、配置、Git 跟踪状态和迁移矩阵，不修改业务代码、数据库、运行数据或命令文本。现有债务只有匹配[精确限时例外](../../config/architecture/exceptions.yaml)时才被豁免；配置无效、例外过期、未分类命中、陈旧 SQL 分类或统一入口中的陈旧例外都会失败关闭。

## 九个公开门

| 公开入口 | 检查范围 | 主要 rule ID |
| --- | --- | --- |
| `check_architecture_boundaries.py` | Python 分层、FastAPI Router、Vue/TypeScript、Electron Main/Preload、legacy 导航字段 | `PY_LAYER_CORE_REVERSE`、`PY_LAYER_REPOSITORIES_REVERSE`、`PY_LAYER_SERVICES_REVERSE`、`PY_LAYER_APPLICATION_REVERSE`；`FASTAPI_ROUTER_BOUNDARY`；`TS_AST_UNAVAILABLE`、`TS_AST_INVALID_OUTPUT`、`TS_AST_PARSE`、`TS_WEB_ELECTRON_IMPORT`、`TS_MAIN_WEB_IMPORT`、`TS_PRELOAD_BUSINESS_IMPORT`；`LEGACY_NAV_FIELD_SCOPE` |
| `check_forbidden_imports.py` | 活动 Python 与依赖清单中的 Qt/PySide/PyQt 运行时回归 | `QT_RUNTIME_IMPORT`、`QT_RUNTIME_DEPENDENCY` |
| `check_direct_sql_access.py` | `sqlite3.connect`、`aiosqlite.connect` 和统一 SQLite connector 的逐文件所有权 | `DIRECT_SQL_CONFIG`、`DIRECT_SQL_UNCLASSIFIED`、`DIRECT_SQL_STALE_CLASSIFICATION`、`DIRECT_SQL_VIOLATION` |
| `check_device_command_hardcoding.py` | 生产设备命令硬编码与 Profile 接管状态 | `DEVICE_COMMAND_AUDIT` |
| `check_ui_business_logic.py` | Vue 可疑业务符号人工分类、主题基础变量、业务 CSS 基础色、AppLayout/侧栏、流式内容宽度、状态色和图表 token | `UI_CLASSIFICATION_CONFIG`、`UI_BUSINESS_LOGIC_UNCLASSIFIED`、`UI_BUSINESS_LOGIC`、`UI_CLASSIFICATION_STALE`；`WEB_THEME_TOKEN_MISSING`、`WEB_THEME_LITERAL_CONFIG`、`WEB_THEME_BASE_LITERAL`、`WEB_THEME_EL_BASE_OVERRIDE`、`WEB_THEME_SIDEBAR_LITERAL`、`WEB_THEME_SIDEBAR_SURFACE`、`WEB_LAYOUT_FLUID_CONTAINER`、`WEB_STATUS_COLOR_TOKEN`、`WEB_CHART_TOKEN_IMPORT`、`WEB_CHART_LITERAL_COLOR`、`WEB_CHART_SERIES_TOKEN` |
| `check_removed_features.py` | 已删除 Qt 路径、SNMP Center、无线勘测等活动入口回归 | `REMOVED_FEATURE_PATH`、`REMOVED_FEATURE_ENTRY` |
| `check_runtime_paths.py` | 仓库运行数据、`Path.cwd()`、目录职责 README | `RUNTIME_PATH_GIT`、`RUNTIME_PATH_TRACKED`、`RUNTIME_PATH_CWD`、`DIRECTORY_README_CONFIG`、`DIRECTORY_README_MISSING` |
| `check_orphan_modules.py` | 无静态生产调用者的 Service 候选；排除 Router、DTO、Job Handler、包入口和显式动态注册 | `ORPHAN_SERVICE_MODULE` |
| `check_migration_map.py` | Qt 删除基线、迁移分类与状态词汇 | `MIGRATION_MAP_MISSING`、`MIGRATION_MAP_CLASSIFICATION`、`MIGRATION_MAP_STATUS`、`MIGRATION_MAP_HISTORY` |

`check_architecture_boundaries.py` 是一个公开门，但其中 Python、TypeScript、Router、Electron 和 legacy names 均输出上表中的独立规则名，不能用其中一类通过推断其他边界也已通过。

## 共享实现

- `checks.py`：Python AST、Router AST、直接 SQL、CSS、运行路径、孤儿 import graph、迁移矩阵和各规则集合。
- `typescript_ast.mjs`：使用工作区 TypeScript compiler API 解析 `.ts` 和 Vue `<script>`；提取 import/export、动态 import、函数符号、legacy 字段及颜色字面量。TypeScript compiler 不可用时失败关闭，不退化为裸字符串 grep。
- `guard_core.py`：`Finding`、确定性排序、UTF-8 配置读取、例外 schema/日期/精确路径校验和退出码。
- `cli.py`：九个公开门的唯一注册表。
- `run_all.py`：从仓库根汇总九个门，并额外拒绝不再命中任何 Finding 的陈旧例外。

FastAPI Router 规则由 `checks.py` 的 `router_boundary_messages()` 提供，现有 Router 测试直接复用该实现。设备命令门直接运行既有 `scripts/maintenance/audit_commands.py --strict --json`，不复制命令事实源。

## 配置与例外

配置统一位于 [`config/architecture`](../../config/architecture/)：

- `direct_sql_access.yaml`：每个直接连接文件必须精确登记，分类只允许 `REPOSITORY_REQUIRED`、`READ_ONLY_DATA_GATEWAY`、`ANALYSIS_DB_OWNER`、`MIGRATION_TOOL`、`TEST_ONLY`、`VIOLATION`；只有 `VIOLATION` 产生发布债务 Finding。
- `ui_business_logic.yaml`：AST 名称命中只产生待分类证据，人工分类只允许 `DISPLAY_ONLY`、`BUSINESS_LOGIC`、`FALSE_POSITIVE`。函数名本身不能自动判定违规。
- `theme_color_literals.yaml`：业务 Vue/CSS 基础属性字面量的精确受控清单，只允许 `BRAND`、`STATUS`、`CHART_SERIES`，禁止目录或 selector 通配；当前清单为空。
- `required_readmes.yaml`：必须存在的目录职责 README 精确列表。
- `exceptions.yaml`：每项必须且只能包含 `rule_id`、`path`、`reason`、`owner`、`created_at`、`expires_at`、`test`。`path` 必须是仓库相对精确路径，禁止目录通配。

这些 `.yaml` 使用 JSON-compatible YAML 子集，以避免给运行层新增 YAML 解析依赖。新增例外前必须先确认对应 Finding、责任域、到期日和可执行测试；债务消除后同步删除分类或例外。

## 运行

在仓库根使用项目虚拟环境：

```powershell
.\.venv\Scripts\python.exe scripts\architecture\run_all.py
```

单独定位某个门，例如：

```powershell
.\.venv\Scripts\python.exe scripts\architecture\check_architecture_boundaries.py
.\.venv\Scripts\python.exe scripts\architecture\check_direct_sql_access.py
.\.venv\Scripts\python.exe scripts\architecture\check_ui_business_logic.py
```

其余公开入口使用表格中的文件名。单门无未豁免命中时返回 `0`，发现问题时返回非零；例外配置本身无效时单门返回 `2`。统一入口只有九门全部通过且没有陈旧例外时返回 `0`。

相关测试见 [`tests/architecture/README.md`](../../tests/architecture/README.md)，长期分层与发布规则见[架构一致性审计](../../docs/ARCHITECTURE_COMPLIANCE.md)。
