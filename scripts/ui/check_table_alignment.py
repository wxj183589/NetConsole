from __future__ import annotations

from table_guard import check_table_alignment


if __name__ == "__main__":
    failures = check_table_alignment()
    if failures:
        raise SystemExit("\n".join(failures))
    print("表格对齐检查通过")
