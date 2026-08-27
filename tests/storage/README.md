# Storage tests

本目录覆盖 SQLite 空间分析、局点存储报告、站点根目录分析和相关生命周期报告。

- 测试只在 pytest 临时目录中创建隔离的 SQLite、文件和 ZIP fixture，不读取或修改 `D:\NetConsoleData`、`D:\NetConsoleData-dev` 或其他机器级数据根。
- 分析器的 direct-SQL 使用必须保持只读、显式输入和失败关闭；测试 fixture 的 direct-SQL 仅用于构造隔离数据。
- 数据库生命周期、路径边界和备份约束遵循 [`docs/testing/BASELINE.md`](../../docs/testing/BASELINE.md) 与 [`docs/development/DEVELOPMENT_RULES.md`](../../docs/development/DEVELOPMENT_RULES.md)。

运行本目录定向测试：

```powershell
.venv\Scripts\python.exe -m pytest tests/storage -q
```
