"""Explicitly upgrade an isolated Task Center cleanup schema."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from netconsole.core.runtime_environment import (
    ProductionWriteBlockedError,
    data_root_for_path,
    require_non_production_data_root,
)
from netconsole.repositories.task_cleanup_schema import upgrade_task_cleanup_schema


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    return parser


def _development_database(path: Path) -> Path:
    database = Path(path).expanduser().resolve()
    root = data_root_for_path(database)
    if database == root or not database.is_relative_to(root):
        raise SystemExit("数据库不在受控数据根内")
    try:
        require_non_production_data_root(root, "upgrade_task_cleanup_schema")
    except ProductionWriteBlockedError as exc:
        raise SystemExit(str(exc)) from exc
    return database


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    database = _development_database(args.database)
    print(
        json.dumps(
            upgrade_task_cleanup_schema(database),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
