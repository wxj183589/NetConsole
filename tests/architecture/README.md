# 架构 Guard 测试

本目录验证 `scripts/architecture/` 的共享引擎、配置契约和九门统一入口。测试只创建 pytest 临时文件或读取当前仓库，不修改生产代码、数据库 schema、设备命令、正式报告或运行数据。

## 测试职责

`test_architecture_guards.py` 覆盖：

- 九个公开检查没有未豁免 Finding；
- TypeScript compiler AST 能解析 `.ts` 与 Vue `<script>`；
- CSS 解析器能处理压缩样式和嵌套 at-rule；
- 主题字面量清单按文件、selector、属性和值精确匹配，当前不保留业务例外；
- direct SQL 引擎支持全部六种规定分类，当前零违规清单完整使用五种非债务分类；
- 孤儿检测不把 Router、Job Handler 和 DTO 当成普通 Service 候选；
- 例外缺字段、过期或使用通配路径时失败关闭；
- 例外只按 `rule_id + path` 精确匹配；
- `run_all.py` 可从仓库根执行并汇总九个公开门。

以下既有测试复用同一 Guard 实现，避免产生第二套事实源：

| 测试 | 复用边界 |
| --- | --- |
| `tests/test_api_router_boundary.py` | `router_boundary_messages()` 与 `FASTAPI_ROUTER_BOUNDARY` 语义 |
| `tests/test_dependency_layers.py` | Python/TypeScript 分层检查与精确例外 |
| `tests/test_e10_device_command_guard.py` | 严格命令审计及现有 Command Guard/Profile 测试 |
| `tests/test_web_architecture.py` | Vue、Electron、legacy 字段、UI 候选与主题规则 |

生产 Router、动态注册 Handler、DTO 和 Parser fixture 不因“只有一个调用者”自动判为孤儿；新的误判应先修正共享 import graph 或补充精确证据，不得给 `services/**`、`apps/web/**` 等目录增加通配豁免。

主题 Guard 还检查业务 Vue/CSS 的基础色必须来自 Token、Element Plus 基础变量只有一个映射文件，以及主工作区/路由根页面保持流式宽度。品牌、状态和图表系列例外也只能逐 declaration 精确登记，不能豁免整个页面或目录。

## 运行

在仓库根运行 Guard 专项测试：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\architecture -q
```

运行与旧架构测试的组合验证：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\architecture tests\test_api_router_boundary.py tests\test_dependency_layers.py tests\test_e10_device_command_guard.py tests\test_web_architecture.py -q
```

实现改动还应执行：

```powershell
.\.venv\Scripts\python.exe -m ruff check scripts\architecture tests\architecture tests\test_api_router_boundary.py tests\test_dependency_layers.py tests\test_e10_device_command_guard.py tests\test_web_architecture.py
.\.venv\Scripts\python.exe scripts\architecture\run_all.py
```

测试事实源、公开入口和 rule ID 对照见 [`scripts/architecture/README.md`](../../scripts/architecture/README.md)。
