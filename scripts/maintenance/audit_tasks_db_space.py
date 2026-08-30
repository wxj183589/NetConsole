"""Read-only table and payload audit for per-site ``tasks.db`` files.

The audit deliberately does not open a write transaction and never changes a
database.  SQLite builds shipped with Python do not always include the
optional ``dbstat`` virtual table, so the report records whether allocation is
exact (dbstat) or a reproducible logical estimate based on live pages and
column/index byte weights.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


DEFAULT_DEV_ROOT = Path(r"D:\NetConsoleData-dev")
PAYLOAD_NAME_HINTS = (
    "json",
    "text",
    "blob",
    "payload",
    "result",
    "snapshot",
    "detail",
    "raw",
)
IGNORED_TABLE_PREFIXES = ("sqlite_",)


def _quote(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def _open_read_only(path: Path) -> sqlite3.Connection:
    uri = f"{path.resolve().as_uri()}?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True, timeout=5.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA busy_timeout=5000")
    return connection


def _tables(connection: sqlite3.Connection) -> list[dict[str, str]]:
    rows = connection.execute(
        "SELECT name, type, COALESCE(tbl_name, name) AS tbl_name "
        "FROM sqlite_master WHERE type IN ('table','index') "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [dict(row) for row in rows]


def _columns(connection: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(f"PRAGMA table_info({_quote(table)})")]


def _is_payload_column(column: dict[str, Any]) -> bool:
    name = str(column.get("name") or "").casefold()
    declared = str(column.get("type") or "").casefold()
    return any(hint in name or hint in declared for hint in PAYLOAD_NAME_HINTS)


def _length_expression(column: str) -> str:
    return f"length(CAST({_quote(column)} AS BLOB))"


def _table_row_count(connection: sqlite3.Connection, table: str) -> int:
    row = connection.execute(f"SELECT COUNT(*) AS count FROM {_quote(table)}").fetchone()
    return int(row["count"] if row is not None else 0)


def _logical_weight(connection: sqlite3.Connection, table: str, columns: list[dict[str, Any]]) -> int:
    expressions = [
        f"COALESCE({_length_expression(str(column['name']))}, 0)"
        for column in columns
    ]
    if not expressions:
        return 0
    row = connection.execute(
        f"SELECT COALESCE(SUM({' + '.join(expressions)}), 0) AS bytes "
        f"FROM {_quote(table)}"
    ).fetchone()
    return int(row["bytes"] if row is not None else 0)


def _index_columns(connection: sqlite3.Connection, index: str) -> list[str]:
    return [
        str(row["name"])
        for row in connection.execute(f"PRAGMA index_info({_quote(index)})")
        if row["name"] is not None
    ]


def _has_dbstat(connection: sqlite3.Connection) -> bool:
    try:
        connection.execute("SELECT name, path, pageno, pagetype, pgsize FROM dbstat LIMIT 1")
    except sqlite3.DatabaseError:
        return False
    return True


def _dbstat_allocation(
    connection: sqlite3.Connection,
    objects: list[dict[str, str]],
) -> tuple[dict[str, int], dict[str, int]]:
    object_types = {str(item["name"]): str(item["type"]) for item in objects}
    table_bytes: Counter[str] = Counter()
    index_bytes: Counter[str] = Counter()
    for row in connection.execute(
        "SELECT name, path, pagetype, pgsize FROM dbstat"
    ):
        name = str(row["name"])
        bytes_value = int(row["pgsize"] or 0)
        if object_types.get(name) == "table":
            table_bytes[name] += bytes_value
        elif object_types.get(name) == "index":
            index_bytes[name] += bytes_value
    index_owner: dict[str, str] = {}
    for table in (item["name"] for item in objects if item["type"] == "table"):
        for index_row in connection.execute(f"PRAGMA index_list({_quote(table)})"):
            index_owner[str(index_row["name"])] = table
    by_table: Counter[str] = Counter()
    for index, size in index_bytes.items():
        by_table[index_owner.get(index, index)] += size
    return dict(table_bytes), dict(by_table)


def _estimated_allocation(
    connection: sqlite3.Connection,
    objects: list[dict[str, str]],
    db_live_bytes: int,
) -> tuple[dict[str, int], dict[str, int]]:
    """Allocate live page bytes proportionally when dbstat is unavailable."""

    table_weights: dict[str, int] = {}
    index_weights: dict[str, int] = {}
    index_owner: dict[str, str] = {}
    for item in objects:
        if item["type"] != "table":
            continue
        table = item["name"]
        columns = _columns(connection, table)
        table_weights[table] = _logical_weight(connection, table, columns) + (
            _table_row_count(connection, table) * 16
        )
        for index_row in connection.execute(f"PRAGMA index_list({_quote(table)})"):
            index = str(index_row["name"])
            index_owner[index] = table
            names = _index_columns(connection, index)
            index_weights[index] = max(1, _logical_weight(connection, table, [
                {"name": name, "type": "TEXT"} for name in names
            ]) + _table_row_count(connection, table) * max(8, 8 * len(names)))
    total_weight = sum(table_weights.values()) + sum(index_weights.values())
    if total_weight <= 0:
        return (
            {table: db_live_bytes if table == next(iter(table_weights), "") else 0 for table in table_weights},
            {},
        )
    table_bytes = {
        table: int(db_live_bytes * weight / total_weight)
        for table, weight in table_weights.items()
    }
    index_bytes_by_table: Counter[str] = Counter()
    for index, weight in index_weights.items():
        index_bytes_by_table[index_owner[index]] += int(db_live_bytes * weight / total_weight)
    used = sum(table_bytes.values()) + sum(index_bytes_by_table.values())
    if used < db_live_bytes and table_bytes:
        largest = max(table_bytes, key=table_bytes.get)
        table_bytes[largest] += db_live_bytes - used
    return table_bytes, dict(index_bytes_by_table)


def _payload_stats(
    connection: sqlite3.Connection,
    table: str,
    column: str,
) -> dict[str, Any]:
    expr = _length_expression(column)
    row = connection.execute(
        f"SELECT COUNT(*) AS row_count, "
        f"SUM(CASE WHEN {_quote(column)} IS NULL THEN 1 ELSE 0 END) AS null_count, "
        f"AVG(CASE WHEN {_quote(column)} IS NULL THEN NULL ELSE {expr} END) AS average_length, "
        f"MAX(CASE WHEN {_quote(column)} IS NULL THEN NULL ELSE {expr} END) AS max_length, "
        f"COALESCE(SUM(COALESCE({expr}, 0)), 0) AS total_bytes, "
        f"COUNT({_quote(column)}) - COUNT(DISTINCT {_quote(column)}) AS duplicate_payload_count "
        f"FROM {_quote(table)}"
    ).fetchone()
    values = dict(row) if row is not None else {}
    return {
        "table": table,
        "column": column,
        "row_count": int(values.get("row_count") or 0),
        "null_count": int(values.get("null_count") or 0),
        "average_length": round(float(values.get("average_length") or 0), 2),
        "max_length": int(values.get("max_length") or 0),
        "total_payload_bytes": int(values.get("total_bytes") or 0),
        "duplicate_payload_count": int(values.get("duplicate_payload_count") or 0),
    }


def _full_result_duplicates(
    connection: sqlite3.Connection,
    table: str,
    column: str,
) -> dict[str, Any]:
    columns = {str(item["name"]) for item in _columns(connection, table)}
    if "task_id" not in columns:
        return {"table": table, "column": column, "full_result_rows": 0, "duplicate_payload_rows": 0, "duplicate_groups": 0}
    occurrences: defaultdict[tuple[str, str], int] = defaultdict(int)
    full_rows = 0
    for row in connection.execute(
        f"SELECT task_id, {_quote(column)} AS payload FROM {_quote(table)} "
        f"WHERE {_quote(column)} IS NOT NULL AND {_quote(column)} <> ''"
    ):
        raw = row["payload"]
        try:
            parsed = json.loads(str(raw))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if table == "task_events":
            if not isinstance(parsed, dict) or not isinstance(parsed.get("result"), dict):
                continue
            full = parsed["result"]
        elif table == "task_snapshots":
            if not isinstance(parsed, dict) or not parsed:
                continue
            full = parsed
        elif table == "task_results":
            if not isinstance(parsed, dict) or not parsed:
                continue
            full = parsed
        else:
            continue
        canonical = json.dumps(full, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        occurrences[(str(row["task_id"]), digest)] += 1
        full_rows += 1
    duplicate_rows = sum(max(0, count - 1) for count in occurrences.values())
    return {
        "table": table,
        "column": column,
        "full_result_rows": full_rows,
        "duplicate_payload_rows": duplicate_rows,
        "duplicate_groups": sum(count > 1 for count in occurrences.values()),
    }


def audit_database(site: str, db_path: Path) -> dict[str, Any]:
    db_size = db_path.stat().st_size
    with _open_read_only(db_path) as connection:
        page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
        page_count = int(connection.execute("PRAGMA page_count").fetchone()[0])
        freelist_count = int(connection.execute("PRAGMA freelist_count").fetchone()[0])
        live_bytes = page_size * page_count
        objects = _tables(connection)
        table_objects = [item for item in objects if item["type"] == "table"]
        has_dbstat = _has_dbstat(connection)
        if has_dbstat:
            table_bytes, index_bytes = _dbstat_allocation(connection, objects)
            allocation_method = "dbstat_exact_page_allocation"
        else:
            table_bytes, index_bytes = _estimated_allocation(connection, objects, live_bytes)
            allocation_method = "logical_byte_weight_estimate_without_dbstat"

        tables: list[dict[str, Any]] = []
        payloads: list[dict[str, Any]] = []
        duplicate_details: list[dict[str, Any]] = []
        for item in table_objects:
            table = item["name"]
            row_count = _table_row_count(connection, table)
            table_size = int(table_bytes.get(table, 0))
            index_size = int(index_bytes.get(table, 0))
            tables.append(
                {
                    "table": table,
                    "row_count": row_count,
                    "table_bytes": table_size,
                    "index_bytes": index_size,
                    "allocated_bytes": table_size + index_size,
                    "avg_row_bytes": round(table_size / row_count, 2) if row_count else 0,
                    "percentage_of_tasks_db": round((table_size + index_size) * 100 / db_size, 4) if db_size else 0,
                }
            )
            for column in _columns(connection, table):
                if not _is_payload_column(column):
                    continue
                column_name = str(column["name"])
                stats = _payload_stats(connection, table, column_name)
                payloads.append(stats)
                if column_name in {"payload_json", "result_json", "canonical_json", "snapshot_json"}:
                    duplicate_details.append(_full_result_duplicates(connection, table, column_name))
        tables.sort(key=lambda item: (item["allocated_bytes"], item["table"]), reverse=True)
        for rank, item in enumerate(tables, start=1):
            item["rank"] = rank
        return {
            "site": site,
            "db_path": str(db_path),
            "db_size_bytes": db_size,
            "page_size": page_size,
            "page_count": page_count,
            "freelist_count": freelist_count,
            "live_page_bytes": live_bytes,
            "allocation_method": allocation_method,
            "dbstat_available": has_dbstat,
            "tables": tables,
            "payload_analysis": payloads,
            "full_result_duplicates": duplicate_details,
            "top_tables": [item["table"] for item in tables[:10]],
        }


def _resolve_databases(
    data_root: Path,
    site: str | None,
    all_sites: bool,
    database: Path | None,
) -> list[tuple[str, Path]]:
    if database is not None:
        return [(site or database.parent.parent.parent.name, database)]
    if site:
        return [(site, data_root / "sites" / site / "db" / "tasks.db")]
    if not all_sites:
        raise SystemExit("必须指定 --site、--all-sites 或 --database")
    return [
        (item.name, item / "db" / "tasks.db")
        for item in sorted((data_root / "sites").iterdir(), key=lambda path: path.name.casefold())
        if item.is_dir() and (item / "db" / "tasks.db").is_file()
    ]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="只读审计 DEV sites/*/db/tasks.db 的表级空间与 payload")
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DEV_ROOT)
    parser.add_argument("--site")
    parser.add_argument("--all-sites", action="store_true")
    parser.add_argument("--database", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("D:/study/NetConsole-Workspace/diagnostic/tasks-db-space-audit"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    databases = _resolve_databases(args.data_root, args.site, args.all_sites, args.database)
    reports: list[dict[str, Any]] = []
    for site, db_path in databases:
        if not db_path.is_file():
            reports.append({"site": site, "db_path": str(db_path), "error": "tasks.db 不存在"})
            continue
        reports.append(audit_database(site, db_path))
    report = {
        "schema": "tasks-db-space-audit/v1",
        "data_root": str(args.data_root),
        "read_only": True,
        "sites": reports,
        "top_tables_by_site": {
            str(item.get("site")): item.get("top_tables", []) for item in reports
        },
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "TASKS_DB_SPACE_AUDIT.json"
    md_path = args.output_dir / "TASKS_DB_SPACE_AUDIT.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# tasks.db 表级空间审计",
        "",
        f"- data_root: `{args.data_root}`",
        "- mode: READ_ONLY",
        "- 说明：优先使用 SQLite dbstat；当前 Python SQLite 未提供 dbstat 时，表/索引字节为可复现的逻辑权重估算，不冒充精确页归属。",
        "",
    ]
    for item in reports:
        lines.extend([f"## {item['site']}", ""])
        if item.get("error"):
            lines.extend([f"- ERROR: {item['error']}", ""])
            continue
        lines.extend([
            f"- db_path: `{item['db_path']}`",
            f"- db_size_bytes: `{item['db_size_bytes']}`",
            f"- page_size/page_count/freelist_count: `{item['page_size']}/{item['page_count']}/{item['freelist_count']}`",
            f"- allocation_method: `{item['allocation_method']}`",
            "",
            "| rank | table | row_count | table_bytes | index_bytes | avg_row_bytes | percentage_of_tasks_db |",
            "| ---: | --- | ---: | ---: | ---: | ---: | ---: |",
        ])
        for table in item["tables"]:
            lines.append(
                f"| {table['rank']} | `{table['table']}` | {table['row_count']} | {table['table_bytes']} | {table['index_bytes']} | {table['avg_row_bytes']} | {table['percentage_of_tasks_db']}% |"
            )
        lines.extend(["", "### Top 占用表", "", "```text", "TASKS_DB_TOP_TABLES ="])
        lines.extend(f"{idx}. {name}" for idx, name in enumerate(item["top_tables"], start=1))
        lines.extend(["```", "", "### Payload/重复摘要", ""])
        for duplicate in item["full_result_duplicates"]:
            lines.append(
                f"- `{duplicate['table']}.{duplicate['column']}`: full_result_rows={duplicate['full_result_rows']}, duplicate_payload_rows={duplicate['duplicate_payload_rows']}, duplicate_groups={duplicate['duplicate_groups']}"
            )
        lines.append("")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"json": str(json_path), "markdown": str(md_path), "sites": len(reports)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
