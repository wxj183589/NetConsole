"""Explicitly upgrade an isolated Task Center cleanup schema."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from netconsole.repositories.task_cleanup_schema import upgrade_task_cleanup_schema


PRODUCTION_DATA_ROOT = Path("D:/NetConsoleData").resolve()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    database = args.database.resolve()
    if database.is_relative_to(PRODUCTION_DATA_ROOT):
        raise SystemExit("Production tasks.db migration is not allowed by this development command")
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
