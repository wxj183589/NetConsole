"""Read-only SQLite page allocation report using the dbstat virtual table."""

from __future__ import annotations

import argparse
import json
import mmap
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPORT_FILE_NAME = "SQLITE_SPACE_REPORT.json"


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


def _row_count(connection: sqlite3.Connection, name: str) -> int:
    identifier = '"' + name.replace('"', '""') + '"'
    row = connection.execute(f"SELECT COUNT(*) FROM {identifier}").fetchone()
    return int(row[0] or 0)


def _read_varint(data: mmap.mmap, offset: int) -> tuple[int, int]:
    value = 0
    for index in range(9):
        byte = data[offset + index]
        if index == 8:
            return (value << 8) | byte, offset + index + 1
        value = (value << 7) | (byte & 0x7F)
        if byte < 0x80:
            return value, offset + index + 1
    raise ValueError("invalid SQLite varint")


def _u16(data: mmap.mmap, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "big")


def _u32(data: mmap.mmap, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "big")


def _local_payload(payload_size: int, usable_size: int, *, index: bool) -> int:
    max_local = ((usable_size - 12) * (64 if index else 32)) // 255 - 23
    max_payload = usable_size - (12 if index else 35)
    if payload_size <= max_payload:
        return payload_size
    min_local = max_local
    local = min_local + (payload_size - min_local) % (usable_size - 4)
    return min_local if local > max_payload else local


def _raw_allocations(
    path: Path,
    objects: list[sqlite3.Row],
    page_size: int,
) -> dict[str, tuple[int, int]]:
    """Estimate physical object allocation by traversing SQLite B-trees.

    This is a read-only fallback for Python builds without the optional dbstat
    virtual table. It counts each reachable B-tree and overflow page once.
    """

    allocations: dict[str, tuple[int, int]] = {}
    file_size = path.stat().st_size
    if page_size <= 0 or file_size < page_size:
        raise ValueError("invalid SQLite page size or file size")

    with path.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
        reserved = data[20]
        usable_size = page_size - reserved
        page_limit = min(file_size // page_size, _u32(data, 28) or file_size // page_size)

        def page_offset(page_number: int) -> int:
            if page_number < 1 or page_number > page_limit:
                raise ValueError(f"SQLite page out of range: {page_number}")
            return (page_number - 1) * page_size

        def walk_overflow(page_number: int, visited: set[int]) -> None:
            while page_number:
                if page_number in visited:
                    return
                visited.add(page_number)
                page_number = _u32(data, page_offset(page_number))

        def walk_btree(page_number: int, visited: set[int], *, index: bool) -> None:
            if page_number in visited:
                return
            visited.add(page_number)
            offset = page_offset(page_number)
            header = offset + (100 if page_number == 1 else 0)
            page_type = data[header]
            cell_count = _u16(data, header + 3)
            if page_type in (0x05, 0x02):
                for index_in_page in range(cell_count):
                    cell_pointer = _u16(data, header + 12 + index_in_page * 2)
                    cell_offset = offset + cell_pointer
                    child_page = _u32(data, cell_offset)
                    walk_btree(child_page, visited, index=page_type == 0x02)
                rightmost = _u32(data, header + 8)
                walk_btree(rightmost, visited, index=page_type == 0x02)
                return
            if page_type not in (0x0D, 0x0A):
                raise ValueError(f"unsupported SQLite B-tree page type: {page_type:#x}")
            for index_in_page in range(cell_count):
                cell_pointer = _u16(data, header + 8 + index_in_page * 2)
                cell_offset = offset + cell_pointer
                payload_size, payload_offset = _read_varint(data, cell_offset)
                if not index:
                    _, payload_offset = _read_varint(data, payload_offset)
                local_size = _local_payload(
                    payload_size,
                    usable_size,
                    index=index,
                )
                if payload_size > local_size:
                    overflow_offset = payload_offset + local_size
                    walk_overflow(_u32(data, overflow_offset), visited)

        for object_row in objects:
            root_page = int(object_row["rootpage"] or 0)
            if not root_page:
                allocations[str(object_row["name"])] = (0, 0)
                continue
            visited: set[int] = set()
            walk_btree(root_page, visited, index=str(object_row["type"]) == "index")
            allocations[str(object_row["name"])] = (len(visited), len(visited) * page_size)
    return allocations


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
    allocation_source = "dbstat"
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
                "SELECT type, name, tbl_name, rootpage FROM sqlite_schema "
                "WHERE type IN ('table', 'index') AND name NOT LIKE 'sqlite_%' "
                "ORDER BY type, name"
            ).fetchall()
            raw_allocations: dict[str, tuple[int, int]] = {}
            if not dbstat_supported:
                allocation_source = "raw_btree"
                try:
                    raw_allocations = _raw_allocations(path, objects, page_size)
                except (OSError, ValueError) as exc:
                    allocation_source = "unavailable"
                    errors.append(
                        "raw SQLite page allocation unavailable: "
                        f"{exc.__class__.__name__}: {exc}"
                    )
            for row in objects:
                object_type = str(row["type"])
                name = str(row["name"])
                object_page_count = 0
                size_bytes = 0
                if dbstat_supported:
                    object_page_count, size_bytes = _allocation(connection, name)
                elif raw_allocations:
                    object_page_count, size_bytes = raw_allocations.get(name, (0, 0))
                if object_type == "table":
                    try:
                        row_count = _row_count(connection, name)
                    except sqlite3.Error as exc:
                        row_count = 0
                        errors.append(
                            f"row count unavailable for {name}: "
                            f"{exc.__class__.__name__}: {exc}"
                        )
                    tables.append(
                        {
                            "table_name": name,
                            "row_count": row_count,
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

    database_size_bytes = path.stat().st_size
    for table in tables:
        table["percentage"] = (
            round(table["size_bytes"] * 100 / database_size_bytes, 2)
            if database_size_bytes
            else 0.0
        )

    tables.sort(key=lambda item: (-item["size_bytes"], item["table_name"]))
    indexes.sort(key=lambda item: (-item["size_bytes"], item["index_name"]))
    allocated_size_bytes = sum(item["size_bytes"] for item in tables + indexes)
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "database_path": str(path),
        "database_size_bytes": database_size_bytes,
        "page_size": page_size,
        "page_count": page_count,
        "dbstat_supported": dbstat_supported,
        "dbstat_error": dbstat_error,
        "allocation_source": allocation_source,
        "tables": tables,
        "indexes": indexes,
        "dbstat_size_bytes": allocated_size_bytes if dbstat_supported else 0,
        "allocated_size_bytes": allocated_size_bytes,
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
