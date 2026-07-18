from __future__ import annotations

from table_guard import check_column_definitions


if __name__ == "__main__":
    failures = check_column_definitions()
    if failures:
        raise SystemExit("\n".join(failures))
    print("表格列定义检查通过")
