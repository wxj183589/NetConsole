from __future__ import annotations

import argparse

from table_guard import write_baseline, write_inventory


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="生成 NetConsole 表格清单")
    parser.add_argument("--write-baseline", action="store_true", help="按当前旧表建立阶段基线")
    args = parser.parse_args()
    if args.write_baseline:
        write_baseline()
    write_inventory()
    print("表格清单已更新")
