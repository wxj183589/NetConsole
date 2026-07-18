from __future__ import annotations

from table_guard import check_hardcoded_column_widths


if __name__ == "__main__":
    failures = check_hardcoded_column_widths()
    if failures:
        raise SystemExit("\n".join(failures))
    print("表格硬编码列宽检查通过")
