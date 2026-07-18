from __future__ import annotations

from table_guard import check_table_contracts


if __name__ == "__main__":
    failures = check_table_contracts()
    if failures:
        raise SystemExit("\n".join(failures))
    print("表格组件契约检查通过")
