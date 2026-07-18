# 架构 Guard 配置

本目录保存 E10B Electron-only 架构 Guard 的版本化配置。配置只供 [`scripts/architecture`](../../scripts/architecture/README.md) 扫描与测试读取，不是产品运行时配置，不改变数据库 schema、设备命令或业务行为。

## 文件职责

| 文件 | 职责 |
| --- | --- |
| `direct_sql_access.yaml` | 对扫描到的直接 SQLite 连接按精确文件登记所有权和职责分类。 |
| `exceptions.yaml` | 保存当前代码确实命中规则时允许的精确限时例外。 |
| `ui_business_logic.yaml` | 对 Vue/TypeScript AST 发现的可疑业务符号进行人工职责分类。 |
| `theme_color_literals.yaml` | 对确实不能迁入 Token 的品牌、状态或图表系列基础色按文件、selector、属性和值精确登记。 |
| `required_readmes.yaml` | 列出必须存在的目录职责 README，包括本文件。 |
| `table-layout-baseline.json` | 记录全局表格整改阶段 1 已存在的直接 `el-table`；逐域迁移后删除对应项，不得扩充以接纳新债务。 |
| `table-layout-exceptions.yaml` | 只登记固定复选框、序号、展开或图标列的精确限时例外。 |

所有 `.yaml` 使用 JSON-compatible YAML 子集和 UTF-8 编码，由 Guard 自身读取，不引入额外 YAML 运行依赖。列表项必须使用仓库相对精确路径；禁止目录级通配或整层豁免。

表格 Guard 由 `scripts/ui/` 独立执行。表格例外必须精确包含 `table_id`、`column_key`、`reason`、`fixed_width`、`test` 和 `expires_at`，禁止通配。旧表基线是显式迁移债务，不是长期豁免。

## Direct SQL 分类

`direct_sql_access.yaml` 每项包含 `path`、`classification`、`owner` 和 `reason`。`classification` 只允许：

- `REPOSITORY_REQUIRED`：Repository、统一连接工厂或兼容存储 facade 的正确持久化边界；
- `READ_ONLY_DATA_GATEWAY`：职责明确的只读查询网关；
- `ANALYSIS_DB_OWNER`：独立会话或分析数据库的所有者；
- `MIGRATION_TOOL`：显式维护或迁移工具；
- `TEST_ONLY`：测试或 fixture 的直接数据库准备与断言；
- `VIOLATION`：尚未归位的生产直接 SQL，必须同时产生发布阻塞 Finding 或匹配限时例外。

Guard 会拒绝未分类的新命中和已不再直接连接 SQLite 的陈旧分类。Repository 内的 SQL 仍需逐文件登记，不能用 `repositories/**` 或 `services/**` 目录规则代替。

## UI 候选分类

`ui_business_logic.yaml` 的函数或符号名称来自 TypeScript AST，只是待分类证据。人工分类只允许：

- `DISPLAY_ONLY`：展示映射、格式化或 API/状态适配；
- `BUSINESS_LOGIC`：Renderer 中不应存在的业务规则；
- `FALSE_POSITIVE`：名称相似但不表达业务语义。

函数名本身不能自动判违规。新增、删除或改名后必须同步实际 AST 证据；陈旧分类会失败关闭。

## 主题字面量

`theme_color_literals.yaml` 每项必须精确包含 `path`、`selector`、`property`、`value`、`category`、`reason`、`owner` 和 `test`。只允许 `BRAND`、`STATUS`、`CHART_SERIES` 三类，路径、selector 和属性不得使用通配；未命中实际 CSS declaration 的陈旧项失败关闭。集中 `theme/*.css` 的 `--nc-*` 定义是事实源，不需要登记；业务 Vue/CSS 的 `background`、`color`、`border`、`box-shadow` 等基础属性必须使用 Token。当前受控清单为空。

## 限时例外

`exceptions.yaml` 每项必须且只能包含：

- `rule_id`
- `path`
- `reason`
- `owner`
- `created_at`
- `expires_at`
- `test`

例外按 `rule_id + path` 精确匹配，日期使用 ISO `YYYY-MM-DD`，`test` 必须指向现存测试。过期、通配、缺字段或不再匹配任何 Finding 的例外都会使 Guard 失败。债务消除后应在同一改动中删除对应分类和例外。

## 验证

在仓库根运行：

```powershell
.\.venv\Scripts\python.exe scripts\architecture\check_direct_sql_access.py
.\.venv\Scripts\python.exe scripts\architecture\run_all.py
.\.venv\Scripts\python.exe -m pytest tests\architecture -q
```

九个公开门、共享 AST 引擎和 rule ID 对照见[架构 Guard README](../../scripts/architecture/README.md)，配置契约测试见[架构 Guard 测试 README](../../tests/architecture/README.md)。
