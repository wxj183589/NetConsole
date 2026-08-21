"""Read-only SQLite page allocation report using the dbstat virtual table."""

from __future__ import annotations

import argparse
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPORT_FILE_NAME = "SQLite_SPACE_REPORT.json"


class SQLiteSpaceReportError(ValueError):
    """Raised when a SQLite space report cannot be generated."""


def _connect_read_only(database: Path) -> sqlite3.Connection:
    uri = f"{database.as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=5.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def _allocation(connection: sqlite3.Connection, name: str) -> tuple[int, int]:
    row = connection.execute(
        "SELECT COUNT(*) AS page_count, COALESCE(SUM(pgsize), 0) AS size_bytes "
        "FROM dbstat WHERE name = ?",
        (name,),
    ).fetchone()
    return int(row["page_count"] or 0), int(row["size_bytes"] or 0)


def analyze_sqlite_size(database: Path | str) -> dict[str, Any]:
    """Return physical table/index page allocation without modifying ``database``."""

    path = Path(database).expanduser().resolve()
    if not path.exists():
        raise SQLiteSpaceReportError(f"SQLite file does not exist: {path}")
    if path.is_symlink() or not path.is_file():
        raise SQLiteSpaceReportError(f"SQLite path is not a regular file: {path}")

    errors: list[str] = []
    tables: list[dict[str, Any]] = []
    indexes: list[dict[str, Any]] = []
    dbstat_supported = False
    dbstat_error = ""
    page_size = 0
    page_count = 0
    try:
        with closing(_connect_read_only(path)) as connection:
            page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
            page_count = int(connection.execute("PRAGMA page_count").fetchone()[0])
            try:
                connection.execute("SELECT name FROM dbstat LIMIT 1").fetchone()
            except sqlite3.Error as exc:
                dbstat_error = f"{exc.__class__.__name__}: {exc}"
                errors.append(f"dbstat unavailable: {dbstat_error}")
            else:
                dbstat_supported = True
                objects = connection.execute(
                    "SELECT type, name, tbl_name FROM sqlite_schema "
                    "WHERE type IN ('table', 'index') AND name NOT LIKE 'sqlite_%' "
                    "ORDER BY type, name"
                ).fetchall()
                for row in objects:
                    object_type = str(row["type"])
                    name = str(row["name"])
                    object_page_count, size_bytes = _allocation(connection, name)
                    if object_type == "table":
                        tables.append(
                            {
                                "table_name": name,
                                "page_count": object_page_count,
                                "size_bytes": size_bytes,
                            }
                        )
                    else:
                        indexes.append(
                            {
                                "index_name": name,
                                "table_name": str(row["tbl_name"]),
                                "page_count": object_page_count,
                                "size_bytes": size_bytes,
                            }
                        )
    except (OSError, sqlite3.Error) as exc:
        raise SQLiteSpaceReportError(f"cannot read SQLite file: {path}") from exc

    tables.sort(key=lambda item: (-item["size_bytes"], item["table_name"]))
    indexes.sort(key=lambda item: (-item["size_bytes"], item["index_name"]))
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "database_path": str(path),
        "database_size_bytes": path.stat().st_size,
        "page_size": page_size,
        "page_count": page_count,
        "dbstat_supported": dbstat_supported,
        "dbstat_error": dbstat_error,
        "tables": tables,
        "indexes": indexes,
        "dbstat_size_bytes": sum(item["size_bytes"] for item in tables + indexes),
        "errors": sorted(errors),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        "--path",
        dest="input_path",
        type=Path,
        required=True,
        help="SQLite file to inspect",
    )
    parser.add_argument("--output", type=Path, help=f"output path (default name: {REPORT_FILE_NAME})")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        report = analyze_sqlite_size(args.input_path)
    except SQLiteSpaceReportError as exc:
        parser.error(str(exc))

    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        output = args.output.expanduser().resolve()
        input_path = args.input_path.expanduser().resolve()
        if output == input_path:
            parser.error("SQLite report output cannot overwrite the database")
        try:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(payload, encoding="utf-8")
        except OSError:
            parser.error(f"cannot write SQLite report: {output}")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
