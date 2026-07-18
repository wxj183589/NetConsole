# UI 契约检查脚本

本目录维护 Electron/Vue 表格和字段展示的增量 Guard，不承载运行时 UI 或业务逻辑。

## 入口

- `export_table_inventory.py`：扫描 Vue 表格并生成 `docs/ui/TABLE_INVENTORY.md`。`--write-baseline` 只用于建立或显式更新旧表基线，不能在普通检查中自动执行。
- `check_table_contracts.py`：阻止新增未登记的直接 `el-table`，要求 `NcDataTable` 使用稳定 `table-id` 和 `route-key`，并检查精确例外。
- `check_column_definitions.py`：阻止迁移文件继续散写 Element Plus 列、`header-align` 或 `measureText()`。
- `check_table_alignment.py`：阻止迁移文件通过 CSS 覆盖表格对齐。
- `check_hardcoded_column_widths.py`：阻止迁移文件散写固定 Element Plus 列宽。
- `table_guard.py`：共享扫描、基线、例外和清单实现。

旧表基线位于 `config/architecture/table-layout-baseline.json`，仅表示阶段 1 时已经存在的债务。逐域迁移时必须删除对应基线项并重新生成清单，不能把新表追加到基线逃避整改。

## 验证

```powershell
\.venv\Scripts\python.exe scripts\ui\check_table_contracts.py
\.venv\Scripts\python.exe scripts\ui\check_column_definitions.py
\.venv\Scripts\python.exe scripts\ui\check_table_alignment.py
\.venv\Scripts\python.exe scripts\ui\check_hardcoded_column_widths.py
\.venv\Scripts\python.exe -m pytest tests\test_ui_table_guards.py -q
```
