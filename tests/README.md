# Python 测试

## 用途

本目录保存 NetConsole Python 单元、集成、架构和脱敏数据测试。

## 边界

测试不得依赖开发机绝对路径、真实设备凭据或正式用户数据。Qt-only 与 standalone Browser Product 测试已经退出活动基线，不得恢复；名称含 `web` 的 FastAPI/Renderer 契约测试仍属于当前产品。

## 主要入口

- `conftest.py`：共享 pytest fixture 与测试环境。
- `fixtures/`：脱敏、版本化测试样本。
- `smoke/`、`support/`：冒烟和测试辅助代码。
- `test_*.py`：按业务模块和架构边界组织的测试。

## 依赖关系

测试导入 `src/netconsole` 的公开或明确内部契约；不得让生产代码反向依赖测试 helper。

## 数据与状态

数据库、日志、报告和缓存使用 `tmp_path` 或明确测试数据根；测试结束后不得在仓库根生成 `data/`、`.local/` 或正式报告。

## 测试

定向示例：`.venv/Scripts/python.exe -m pytest tests/test_site_database_recovery.py -q`。最终组合按 `docs/testing/BASELINE.md` 执行。

## 修改规则

不得用删除测试掩盖 Qt 迁移回归；Fake、自动化和真实设备验收必须分开陈述。

## 生成与清理

`__pycache__/`、`.pytest_cache/` 和 pytest 临时目录可安全重新生成；未知数据库、日志或截图先分类再清理。

## 相关文档

- [测试基线](../docs/testing/BASELINE.md)
- [仓库目录规范](../docs/development/repository-layout.md)
