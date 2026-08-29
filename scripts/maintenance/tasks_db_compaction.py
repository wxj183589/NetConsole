"""tasks.db table audit and development-only candidate compaction.

The command deliberately separates read-only inspection, a frozen SQLite
Backup API candidate, logical result projection de-duplication, VACUUM INTO,
parity verification, and the final DEV-only atomic replacement.

It never accepts D:/NetConsoleData as an apply root and never writes a source
database during --dry-run. Task rows, event history, operational session
mappings, and Ground's separate current mapping are retained.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
from collections import defaultdict
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable


DEVELOPMENT_DATA_ROOT = Path("D:/NetConsoleData-dev").resolve()
DIAGNOSTIC_ROOT = Path("D:/study/diagnostic/NetConsole").resolve()
TERMINAL_STATUSES = frozenset({"COMPLETED", "FAILED", "CANCELLED"})
ACTIVE_STATUSES = frozenset(
    {"PENDING", "STARTING", "RUNNING", "STOPPING", "PAUSED", "RECOVERY"}
)
RESULT_EVENT_TYPES = frozenset(
    {"finished", "error", "cancelled", "artifact_finalized", "artifact_rejected"}
)
PAYLOAD_NAME_MARKERS = (
    "json",
    "payload",
    "result",
    "snapshot",
    "detail",
    "raw",
    "blob",
)


def _quote(identifier: str) -> str:
    if not identifier:
        raise ValueError("empty SQLite identifier")
    return '"' + identifier.replace('"', '""') + '"'


def _connect_read_only(path: Path) -> sqlite3.Connection:
    uri = f"{path.resolve().as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=5.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA busy_timeout=5000")
    return connection


def _connect_candidate(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=30.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=30000")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_revision(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"exists": False, "bytes": 0, "sha256": ""}
    stat = path.stat()
    return {
        "exists": True,
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "sha256": _sha256(path),
    }


def source_revision(database: Path) -> dict[str, Any]:
    return {
        "main": _file_revision(database),
        "wal": _file_revision(database.with_name(database.name + "-wal")),
        "shm": _file_revision(database.with_name(database.name + "-shm")),
    }


def _source_content_revision(revision: dict[str, Any]) -> tuple[str, int, str, int]:
    """Return the SQLite content identity; -shm mtime is process metadata."""

    main = revision["main"]
    wal = revision["wal"]
    return (
        str(main.get("sha256") or ""),
        int(main.get("bytes") or 0),
        str(wal.get("sha256") or ""),
        int(wal.get("bytes") or 0),
    )


def _sidecar_bytes(database: Path) -> int:
    return sum(
        int(path.stat().st_size)
        for path in (
            database.with_name(database.name + "-wal"),
            database.with_name(database.name + "-shm"),
        )
        if path.is_file()
    )


def _tables(connection: sqlite3.Connection) -> list[str]:
    return [
        str(row["name"])
        for row in connection.execute(
            "SELECT name FROM sqlite_schema "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    ]


def _columns(connection: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in connection.execute(f"PRAGMA table_info({_quote(table)})").fetchall()
    ]


def _length_expression(column: str) -> str:
    name = _quote(column)
    return (
        f"CASE typeof({name}) WHEN 'null' THEN 0 "
        f"WHEN 'blob' THEN length({name}) "
        f"WHEN 'text' THEN length(CAST({name} AS BLOB)) "
        f"ELSE length(CAST({name} AS TEXT)) END"
    )


def _physical(connection: sqlite3.Connection, database: Path) -> dict[str, Any]:
    page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
    page_count = int(connection.execute("PRAGMA page_count").fetchone()[0])
    freelist = int(connection.execute("PRAGMA freelist_count").fetchone()[0])
    journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0])
    return {
        "db_size_bytes": int(database.stat().st_size),
        "tasks_db_total_bytes": int(database.stat().st_size) + _sidecar_bytes(database),
        "wal_bytes": int(database.with_name(database.name + "-wal").stat().st_size)
        if database.with_name(database.name + "-wal").is_file()
        else 0,
        "shm_bytes": int(database.with_name(database.name + "-shm").stat().st_size)
        if database.with_name(database.name + "-shm").is_file()
        else 0,
        "page_size": page_size,
        "page_count": page_count,
        "freelist_count": freelist,
        "free_page_bytes": freelist * page_size,
        "journal_mode": journal_mode,
    }


def _dbstat(connection: sqlite3.Connection) -> dict[str, dict[str, int]] | None:
    try:
        rows = connection.execute(
            "SELECT name, COUNT(*) AS page_count, "
            "COALESCE(SUM(pgsize), 0) AS bytes, "
            "COALESCE(SUM(payload), 0) AS payload_bytes "
            "FROM dbstat GROUP BY name"
        ).fetchall()
    except sqlite3.Error:
        return None
    return {
        str(row["name"]): {
            "page_count": int(row["page_count"] or 0),
            "bytes": int(row["bytes"] or 0),
            "payload_bytes": int(row["payload_bytes"] or 0),
        }
        for row in rows
    }


def _logical_bytes(
    connection: sqlite3.Connection, table: str, columns: list[dict[str, Any]]
) -> tuple[int, int]:
    if not columns:
        return 0, 0
    expression = " + ".join(
        _length_expression(str(column["name"])) for column in columns
    )
    row = connection.execute(
        f"SELECT COUNT(*) AS row_count, COALESCE(SUM({expression}), 0) AS bytes "
        f"FROM {_quote(table)}"
    ).fetchone()
    return int(row["row_count"] or 0), int(row["bytes"] or 0)


def _index_map(
    connection: sqlite3.Connection, tables: Iterable[str]
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    index_to_table: dict[str, str] = {}
    indexes: list[dict[str, Any]] = []
    for table in tables:
        for row in connection.execute(f"PRAGMA index_list({_quote(table)})").fetchall():
            index = str(row["name"])
            index_to_table[index] = table
            key_rows = connection.execute(f"PRAGMA index_xinfo({_quote(index)})").fetchall()
            columns = [
                str(item["name"])
                for item in key_rows
                if int(item["key"] or 0) and int(item["cid"]) >= 0
            ]
            indexes.append(
                {
                    "index": index,
                    "table": table,
                    "columns": columns,
                    "unique": bool(int(row["unique"] or 0)),
                    "origin": str(row["origin"] or ""),
                    "partial": bool(int(row["partial"] or 0)),
                }
            )
    return index_to_table, indexes


def _allocation(
    connection: sqlite3.Connection, database: Path, table_names: list[str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    physical = _physical(connection, database)
    page_size = int(physical["page_size"])
    _index_to_table, indexes = _index_map(connection, table_names)
    dbstat = _dbstat(connection)
    table_stats: list[dict[str, Any]] = []
    table_weight: dict[str, int] = {}
    index_weight: dict[str, int] = {}
    for table in table_names:
        columns = _columns(connection, table)
        row_count, logical_bytes = _logical_bytes(connection, table, columns)
        table_weight[table] = logical_bytes + row_count * max(8, len(columns) // 2)
        table_stats.append(
            {
                "table": table,
                "row_count": row_count,
                "logical_payload_bytes": logical_bytes,
                "avg_row_bytes": round(logical_bytes / row_count, 2) if row_count else 0,
                "table_bytes": 0,
                "index_bytes": 0,
                "page_count": 0,
                "table_page_count": 0,
                "index_page_count": 0,
                "payload_bytes": 0,
                "percentage_of_tasks_db": 0.0,
            }
        )
    for item in indexes:
        table = str(item["table"])
        columns = item["columns"]
        if columns:
            expression = " + ".join(_length_expression(column) for column in columns)
            row = connection.execute(
                f"SELECT COUNT(*) AS row_count, COALESCE(SUM({expression}), 0) AS bytes "
                f"FROM {_quote(table)}"
            ).fetchone()
            rows = int(row["row_count"] or 0)
            bytes_value = int(row["bytes"] or 0)
        else:
            rows = 0
            bytes_value = 0
        index_weight[str(item["index"])] = bytes_value + rows * 12

    allocations: dict[str, dict[str, int]]
    method = "sqlite_dbstat"
    if dbstat is not None:
        allocations = dbstat
    else:
        method = "logical_weight_normalized_fallback"
        live_bytes = max(
            0, int(physical["db_size_bytes"]) - int(physical["free_page_bytes"])
        )
        total_weight = max(1, sum(table_weight.values()) + sum(index_weight.values()))
        allocations = {
            name: {
                "bytes": round(live_bytes * weight / total_weight),
                "page_count": round(live_bytes * weight / total_weight / page_size),
                "payload_bytes": 0,
            }
            for name, weight in {**table_weight, **index_weight}.items()
        }
    by_table = {str(item["table"]): item for item in table_stats}
    for table in table_names:
        table_item = by_table[table]
        allocation = allocations.get(table, {})
        table_item["table_bytes"] = int(allocation.get("bytes", 0))
        table_item["table_page_count"] = int(allocation.get("page_count", 0))
        table_item["payload_bytes"] = int(
            allocation.get("payload_bytes", table_item["logical_payload_bytes"])
        )
        for index in indexes:
            if str(index["table"]) != table:
                continue
            index_item = allocations.get(str(index["index"]), {})
            table_item["index_bytes"] += int(index_item.get("bytes", 0))
            table_item["index_page_count"] += int(index_item.get("page_count", 0))
        table_item["page_count"] = (
            table_item["table_page_count"] + table_item["index_page_count"]
        )
        table_item["percentage_of_tasks_db"] = round(
            (table_item["table_bytes"] + table_item["index_bytes"])
            * 100
            / max(1, int(physical["db_size_bytes"])),
            2,
        )
    for item in indexes:
        allocation = allocations.get(str(item["index"]), {})
        item["index_bytes"] = int(allocation.get("bytes", 0))
        item["page_count"] = int(allocation.get("page_count", 0))
        item["payload_bytes"] = int(allocation.get("payload_bytes", 0))
    table_stats.sort(
        key=lambda item: int(item["table_bytes"]) + int(item["index_bytes"]),
        reverse=True,
    )
    indexes.sort(key=lambda item: int(item["index_bytes"]), reverse=True)
    duplicate_groups: dict[str, list[str]] = defaultdict(list)
    for item in indexes:
        signature = json.dumps(
            {
                "table": item["table"],
                "columns": item["columns"],
                "unique": item["unique"],
                "partial": item["partial"],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        duplicate_groups[signature].append(str(item["index"]))
    return (
        table_stats,
        indexes,
        {
            "allocation_method": method,
            "dbstat_available": dbstat is not None,
            "estimated": dbstat is None,
            "index_duplicate_groups": [
                names for names in duplicate_groups.values() if len(names) > 1
            ],
            "note": (
                "SQLite dbstat page allocation."
                if dbstat is not None
                else "dbstat is unavailable; logical field/key weights normalized "
                "to live database bytes. Payload totals remain exact."
            ),
        },
    )


def _payload_columns(columns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for column in columns:
        name = str(column["name"])
        declared = str(column.get("type") or "").upper()
        if declared in {"TEXT", "BLOB", "JSON"} or any(
            marker in name.casefold() for marker in PAYLOAD_NAME_MARKERS
        ):
            result.append(column)
    return result


def _payload_stats(
    connection: sqlite3.Connection, table: str, columns: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for column in _payload_columns(columns):
        name = str(column["name"])
        quoted = _quote(name)
        length_sql = _length_expression(name)
        row = connection.execute(
            f"SELECT COUNT(*) AS row_count, "
            f"COUNT(*) - COUNT({quoted}) AS null_count, "
            f"COALESCE(SUM({length_sql}), 0) AS total_payload_bytes, "
            f"COALESCE(AVG({length_sql}), 0) AS average_length, "
            f"COALESCE(MAX({length_sql}), 0) AS max_length "
            f"FROM {_quote(table)}"
        ).fetchone()
        duplicate_count: int | None
        try:
            duplicate = connection.execute(
                f"SELECT COALESCE(SUM(duplicate_count - 1), 0) AS duplicates "
                f"FROM (SELECT {quoted}, COUNT(*) AS duplicate_count "
                f"FROM {_quote(table)} WHERE {quoted} IS NOT NULL "
                f"GROUP BY {quoted} HAVING COUNT(*) > 1)"
            ).fetchone()
            duplicate_count = int(duplicate["duplicates"] or 0)
        except sqlite3.Error:
            duplicate_count = None
        result.append(
            {
                "table": table,
                "column": name,
                "declared_type": str(column.get("type") or ""),
                "row_count": int(row["row_count"] or 0),
                "null_count": int(row["null_count"] or 0),
                "non_null_count": int(row["row_count"] or 0)
                - int(row["null_count"] or 0),
                "average_length": round(float(row["average_length"] or 0), 2),
                "max_length": int(row["max_length"] or 0),
                "total_payload_bytes": int(row["total_payload_bytes"] or 0),
                "duplicate_payload_count": duplicate_count,
            }
        )
    return result


def _json_object(raw: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(str(raw or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _canonical(value: dict[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _status_event(status: str) -> str:
    return {
        "COMPLETED": "finished",
        "FAILED": "error",
        "CANCELLED": "cancelled",
    }.get(status.upper(), "finished")


def _result_summary(result: dict[str, Any], byte_size: int) -> dict[str, Any]:
    keys = sorted(str(key) for key in result)
    return {
        "byte_size": int(byte_size),
        "field_count": len(keys),
        "keys": keys[:32],
        "keys_truncated": len(keys) > 32,
    }


def _result_rows(connection: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    if "task_results" not in _tables(connection):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for row in connection.execute("SELECT * FROM task_results"):
        item = dict(row)
        canonical = str(item.get("canonical_json") or "")
        item["result"] = _json_object(canonical)
        result[str(item["result_id"])] = item
    return result


def _resolve_result(
    result_id: str, result_rows: dict[str, dict[str, Any]]
) -> tuple[str, dict[str, Any]] | None:
    if not result_id or result_id not in result_rows:
        return None
    item = result_rows[result_id]
    canonical = str(item.get("canonical_json") or "")
    result = item.get("result")
    if not canonical or not isinstance(result, dict):
        return None
    return _digest(canonical), result


def _artifact_references(result: dict[str, Any]) -> list[str]:
    values: set[str] = set()

    def visit(value: Any, key: str = "") -> None:
        if isinstance(value, dict):
            for child_key, child in value.items():
                lowered = str(child_key).casefold()
                if "artifact" in lowered or lowered in {
                    "result_path",
                    "path_id",
                    "sha256",
                }:
                    if isinstance(child, (str, int, float, bool)):
                        values.add(f"{child_key}={child}")
                visit(child, str(child_key))
        elif isinstance(value, list):
            for child in value:
                visit(child, key)

    visit(result)
    return sorted(values)


def _task_semantics(connection: sqlite3.Connection) -> dict[str, Any]:
    table_names = set(_tables(connection))
    if "task_snapshots" not in table_names:
        return {
            "task_rows": 0,
            "event_rows": 0,
            "snapshot_rows": 0,
            "status_counts": {},
            "task_list": [],
            "task_list_digest": _digest("[]"),
            "task_detail_digest": _digest("[]"),
            "sample_task_ids": [],
            "sessions": {"rows": 0, "digest": _digest("[]")},
        }
    result_rows = _result_rows(connection)
    snapshots = [
        dict(row)
        for row in connection.execute(
            "SELECT * FROM task_snapshots ORDER BY task_id"
        ).fetchall()
    ]
    events = [
        dict(row)
        for row in connection.execute(
            "SELECT * FROM task_events ORDER BY sequence"
        ).fetchall()
    ] if "task_events" in table_names else []
    status_counts: dict[str, int] = defaultdict(int)
    task_list: list[dict[str, Any]] = []
    for row in snapshots:
        status = str(row.get("status") or "")
        status_counts[status] += 1
        raw_result = _json_object(row.get("result_json"))
        resolved = _resolve_result(str(row.get("result_id") or ""), result_rows)
        if resolved:
            result_digest, result = resolved
        elif raw_result:
            result_digest, result = _digest(_canonical(raw_result)), raw_result
        else:
            result_digest, result = "", {}
        normalized_summary = (
            _result_summary(result, len(_canonical(result).encode("utf-8")))
            if result
            else {}
        )
        task_list.append(
            {
                "task_id": str(row.get("task_id") or ""),
                "task_type": str(row.get("task_type") or ""),
                "status": status,
                "created_time": str(row.get("created_time") or ""),
                "started_time": str(row.get("started_time") or ""),
                "finished_time": str(row.get("finished_time") or ""),
                "updated_time": str(row.get("updated_time") or ""),
                "progress": int(row.get("progress") or 0),
                "summary_digest": _digest(
                    json.dumps(
                        normalized_summary,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                ),
                "result_digest": result_digest,
                "artifact_references": _artifact_references(result),
                "error_summary": str(row.get("error_message") or "")[:500],
            }
        )
    task_list_digest = _digest(
        json.dumps(task_list, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        payload = _json_object(event.get("payload_json"))
        raw_result = payload.pop("result", None)
        result_digest = ""
        if isinstance(raw_result, dict) and raw_result:
            result_digest = _digest(_canonical(raw_result))
        resolved = _resolve_result(str(payload.get("result_id") or ""), result_rows)
        if resolved:
            result_digest = resolved[0]
        for key in ("result_id", "result_hash", "result_summary"):
            payload.pop(key, None)
        if result_digest:
            payload["result_digest"] = result_digest
        by_task[str(event.get("task_id") or "")].append(
            {
                "sequence": int(event.get("sequence") or 0),
                "event_id": str(event.get("event_id") or ""),
                "event_type": str(event.get("event_type") or ""),
                "event_time": str(event.get("event_time") or ""),
                "source": str(event.get("source") or ""),
                "payload": payload,
            }
        )
    sample_ids: list[str] = []
    ordered = sorted(
        task_list,
        key=lambda row: (str(row["updated_time"]), str(row["task_id"])),
        reverse=True,
    )
    sample_ids.extend(row["task_id"] for row in ordered[:2])
    for row in reversed(ordered):
        if row["task_id"] not in sample_ids:
            sample_ids.append(row["task_id"])
            break
    for predicate in (
        lambda row: row["status"] == "COMPLETED",
        lambda row: row["status"] == "FAILED",
        lambda row: "online_mr" in row["task_type"].casefold(),
        lambda row: "export" in row["task_type"].casefold(),
    ):
        for row in task_list:
            if predicate(row) and row["task_id"] not in sample_ids:
                sample_ids.append(row["task_id"])
                break
    details = []
    task_rows_by_id = {row["task_id"]: row for row in task_list}
    for task_id in sample_ids:
        details.append(
            {
                "task": task_rows_by_id.get(task_id, {}),
                "events": by_task.get(task_id, []),
            }
        )
    detail_digest = _digest(
        json.dumps(details, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    sessions = {"rows": 0, "digest": _digest("[]")}
    if "online_mr_task_sessions" in table_names:
        session_rows = [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM online_mr_task_sessions ORDER BY rowid"
            ).fetchall()
        ]
        sessions = {
            "rows": len(session_rows),
            "digest": _digest(
                json.dumps(
                    session_rows,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            ),
        }
    return {
        "task_rows": len(snapshots),
        "event_rows": len(events),
        "snapshot_rows": len(snapshots),
        "status_counts": dict(sorted(status_counts.items())),
        "active_task_count": sum(status_counts.get(status, 0) for status in ACTIVE_STATUSES),
        "pending_task_count": status_counts.get("PENDING", 0),
        "running_task_count": status_counts.get("RUNNING", 0),
        "completed_task_count": status_counts.get("COMPLETED", 0),
        "task_list": task_list,
        "task_list_digest": task_list_digest,
        "task_detail_digest": detail_digest,
        "sample_task_ids": sample_ids,
        "sessions": sessions,
    }


def _payload_duplication(connection: sqlite3.Connection) -> dict[str, Any]:
    table_names = set(_tables(connection))
    if "task_snapshots" not in table_names:
        return {}
    result_rows = _result_rows(connection)
    result_by_task_digest: dict[tuple[str, str], list[str]] = defaultdict(list)
    for result_id, row in result_rows.items():
        canonical = str(row.get("canonical_json") or "")
        result_by_task_digest[(str(row.get("task_id") or ""), _digest(canonical))].append(
            result_id
        )
    full_occurrences: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    snapshot_full_rows = 0
    snapshot_full_bytes = 0
    safe_snapshot_rows = 0
    for row in connection.execute(
        "SELECT task_id, status, result_json, result_id FROM task_snapshots"
    ):
        if str(row["status"] or "") not in TERMINAL_STATUSES:
            continue
        value = _json_object(row["result_json"])
        if not value:
            continue
        canonical = _canonical(value)
        size = len(canonical.encode("utf-8"))
        snapshot_full_rows += 1
        snapshot_full_bytes += size
        digest = _digest(canonical)
        task_id = str(row["task_id"])
        full_occurrences[(task_id, digest)].append(
            {"owner": "task_snapshots.result_json", "bytes": size}
        )
        if _resolve_result(str(row["result_id"] or ""), result_rows) is not None or (
            task_id,
            digest,
        ) in result_by_task_digest:
            safe_snapshot_rows += 1
    event_full_rows = 0
    event_full_bytes = 0
    safe_event_rows = 0
    repeated_progress_rows = 0
    repeated_progress_bytes = 0
    previous_progress: dict[str, str] = {}
    if "task_events" in table_names:
        for row in connection.execute(
            "SELECT task_id, event_type, payload_json FROM task_events ORDER BY sequence"
        ):
            task_id = str(row["task_id"])
            event_type = str(row["event_type"])
            payload_raw = str(row["payload_json"] or "{}")
            payload = _json_object(payload_raw)
            if event_type == "progress":
                progress_digest = _digest(payload_raw)
                if previous_progress.get(task_id) == progress_digest:
                    repeated_progress_rows += 1
                    repeated_progress_bytes += len(payload_raw.encode("utf-8"))
                previous_progress[task_id] = progress_digest
            if event_type not in RESULT_EVENT_TYPES:
                continue
            value = payload.get("result")
            if not isinstance(value, dict) or not value:
                continue
            canonical = _canonical(value)
            size = len(canonical.encode("utf-8"))
            digest = _digest(canonical)
            event_full_rows += 1
            event_full_bytes += size
            full_occurrences[(task_id, digest)].append(
                {"owner": f"task_events.{event_type}.payload_json", "bytes": size}
            )
            if _resolve_result(str(payload.get("result_id") or ""), result_rows) is not None or (
                task_id,
                digest,
            ) in result_by_task_digest:
                safe_event_rows += 1
    duplicate_groups = []
    duplicate_rows = 0
    duplicate_bytes = 0
    for (task_id, digest), occurrences in full_occurrences.items():
        if len(occurrences) < 2:
            continue
        extras = occurrences[1:]
        duplicate_rows += len(extras)
        duplicate_bytes += sum(int(item["bytes"]) for item in extras)
        duplicate_groups.append(
            {
                "task_id": task_id,
                "payload_sha256": digest,
                "occurrence_count": len(occurrences),
                "duplicate_rows": len(extras),
                "duplicate_bytes": sum(int(item["bytes"]) for item in extras),
                "owners": [str(item["owner"]) for item in occurrences],
            }
        )
    return {
        "snapshot_full_result_rows": snapshot_full_rows,
        "snapshot_full_result_bytes": snapshot_full_bytes,
        "event_full_result_rows": event_full_rows,
        "event_full_result_bytes": event_full_bytes,
        "safe_snapshot_projection_rows": safe_snapshot_rows,
        "safe_event_projection_rows": safe_event_rows,
        "full_result_projection_rows": safe_snapshot_rows + safe_event_rows,
        "full_result_projection_bytes": snapshot_full_bytes + event_full_bytes,
        "duplicate_payload_rows": duplicate_rows,
        "duplicate_payload_bytes": duplicate_bytes,
        "duplicate_payload_groups": sorted(
            duplicate_groups, key=lambda item: item["duplicate_bytes"], reverse=True
        )[:100],
        "repeated_progress_rows": repeated_progress_rows,
        "repeated_progress_bytes": repeated_progress_bytes,
        "repeated_progress_action": (
            "OBSERVE_ONLY; Task Center event replay and Site Return Package consumers "
            "require the event trajectory. No Recent10 deletion was applied."
        ),
        "obsolete_snapshot_rows": 0,
        "obsolete_snapshot_reason": (
            "task_snapshots.task_id is the current/recovery projection primary key; "
            "there is no second snapshot row per task to retire."
        ),
    }


def _ground_state(site_dir: Path) -> dict[str, Any]:
    database = site_dir / "files" / "rail_transit" / "ground_unattended" / "index.sqlite"
    if not database.is_file():
        return {"path": str(database), "exists": False, "tables": {}, "sha256": ""}
    tables: dict[str, int] = {}
    try:
        with closing(_connect_read_only(database)) as connection:
            for table in _tables(connection):
                if any(
                    marker in table.casefold()
                    for marker in ("current", "mapping", "task", "run")
                ):
                    tables[table] = int(
                        connection.execute(f"SELECT COUNT(*) FROM {_quote(table)}").fetchone()[0]
                    )
    except sqlite3.Error as exc:
        return {
            "path": str(database),
            "exists": True,
            "bytes": int(database.stat().st_size),
            "error": f"{exc.__class__.__name__}: {exc}",
            "tables": {},
            "sha256": "",
        }
    return {
        "path": str(database),
        "exists": True,
        "bytes": int(database.stat().st_size),
        "tables": tables,
        "sha256": _sha256(database),
        "note": "Ground current mapping is outside tasks.db and is not touched.",
    }


def _task_db_audit(
    database: Path,
    *,
    site: str,
    source_database: Path | None = None,
    site_dir: Path | None = None,
) -> dict[str, Any]:
    source = source_database or database
    with closing(_connect_read_only(database)) as connection:
        table_names = _tables(connection)
        tables, indexes, allocation = _allocation(connection, database, table_names)
        payload_fields = [
            field
            for table in table_names
            for field in _payload_stats(connection, table, _columns(connection, table))
        ]
        semantics = _task_semantics(connection)
        duplication = _payload_duplication(connection)
        quick_check = str(connection.execute("PRAGMA quick_check").fetchone()[0])
        physical = _physical(connection, source)
    return {
        "site": site,
        "db_path": str(source),
        "db_size_bytes": int(physical["db_size_bytes"]),
        "tasks_db_total_bytes": int(physical["tasks_db_total_bytes"]),
        "physical": physical,
        "quick_check": quick_check,
        "tables": tables,
        "indexes": indexes,
        "allocation": allocation,
        "payload_fields": payload_fields,
        "ground_current_mapping": _ground_state(site_dir) if site_dir else {},
        "task_storage": {
            "semantics": semantics,
            "duplication": duplication,
            "canonical_result_authority": {
                "table": "task_results",
                "status": (
                    "PASS"
                    if "task_results" in table_names
                    else "NOT_AVAILABLE"
                ),
                "policy": (
                    "task_results.canonical_json is the task result authority; "
                    "task_snapshots and terminal events retain refs/summary only after "
                    "verified candidate migration."
                ),
            },
            "online_mr_task_sessions": {
                "rows": int(semantics["sessions"]["rows"]),
                "preserved": True,
                "policy": (
                    "operational Controller/session mapping; generic task retention "
                    "must not delete mapped rows."
                ),
            },
        },
        "consumer_contract": {
            "task_list": "JobCenterQueryService.list_tasks reads task_snapshots and result refs.",
            "task_detail": (
                "JobCenterQueryService.get_task reads current snapshot plus latest "
                "progress events; TaskApplicationService list_events replays task_events."
            ),
            "restart_recovery": (
                "TaskRuntime/ApplicationService recover from current task snapshot; "
                "active states and resource keys remain untouched."
            ),
            "online_mr": (
                "online_mr_task_sessions is an operational authority joined by Task Center "
                "and read during restart; it is not reconstructed from generic events."
            ),
            "ground": (
                "Ground current mapping is held in the separate ground_unattended index "
                "and is outside this candidate."
            ),
            "event_retention": (
                "No automatic event cap is applied: repeated progress is reported only. "
                "Recent10 is limited to engineering change history, not tasks.db."
            ),
        },
    }


def _backup_database(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise FileExistsError(f"candidate already exists: {target}")
    with closing(_connect_read_only(source)) as source_connection:
        with closing(sqlite3.connect(target, timeout=30.0)) as target_connection:
            source_connection.backup(target_connection, pages=0, sleep=0.05)
            target_connection.commit()
    check = _quick_check(target)
    if not check["pass"]:
        raise sqlite3.DatabaseError(f"backup quick_check failed: {check}")


def _valid_result_item(
    connection: sqlite3.Connection, result_id: str, task_id: str, event_type: str
) -> dict[str, Any] | None:
    if not result_id:
        return None
    row = connection.execute(
        "SELECT * FROM task_results WHERE result_id=?", (result_id,)
    ).fetchone()
    if row is None or str(row["task_id"]) != task_id:
        return None
    if event_type and str(row["terminal_event_type"]) != event_type:
        return None
    canonical = str(row["canonical_json"] or "")
    result = _json_object(canonical)
    # An empty JSON object is a valid canonical result (for example a
    # cancelled task with no result body). Only an absent/invalid canonical
    # document is an invalid reference.
    if not canonical or not isinstance(result, dict):
        return None
    if str(row["sha256"] or "") != _digest(canonical):
        return None
    return dict(row) | {"result": result}


def _apply_result_projection_cleanup(database: Path) -> dict[str, Any]:
    """Create immutable result authorities and strip only verified projections."""

    counters: dict[str, Any] = {
        "tasks_examined": 0,
        "result_rows_created": 0,
        "snapshot_full_results_removed": 0,
        "event_full_results_removed": 0,
        "logical_result_bytes_removed": 0,
        "conflict_tasks": [],
        "invalid_tasks": [],
        "invalid_snapshot_refs_removed": 0,
        "invalid_event_refs_removed": 0,
        "obsolete_snapshot_rows_removed": 0,
    }
    with closing(_connect_candidate(database)) as connection:
        if not {"task_snapshots", "task_events", "task_results"} <= set(_tables(connection)):
            return {**counters, "skipped": "required task result tables are absent"}
        connection.execute("BEGIN IMMEDIATE")
        snapshots = [
            dict(row)
            for row in connection.execute(
                "SELECT task_id, status, finished_time, updated_time, result_json, "
                "result_id, result_hash FROM task_snapshots ORDER BY task_id"
            ).fetchall()
        ]
        for snapshot in snapshots:
            status = str(snapshot["status"] or "")
            if status not in TERMINAL_STATUSES:
                continue
            counters["tasks_examined"] += 1
            task_id = str(snapshot["task_id"])
            options: list[tuple[str, str, dict[str, Any]]] = []
            snapshot_result = _json_object(snapshot["result_json"])
            snapshot_ref = _valid_result_item(
                connection,
                str(snapshot["result_id"] or ""),
                task_id,
                "",
            )
            if snapshot_ref:
                options.append(
                    (
                        str(snapshot_ref["canonical_json"]),
                        str(snapshot_ref["terminal_event_type"]),
                        dict(snapshot_ref["result"]),
                    )
                )
            elif snapshot["result_id"] and not snapshot_result:
                connection.execute(
                    "UPDATE task_snapshots SET result_id='', result_hash='', "
                    "result_summary_json='{}' WHERE task_id=?",
                    (task_id,),
                )
                counters["invalid_snapshot_refs_removed"] += 1
            elif snapshot["result_id"]:
                # A full snapshot is a usable source when an old reference is
                # stale; the candidate below will replace that reference only
                # after hashing the full value.
                pass
            if snapshot_result:
                options.append(
                    (_canonical(snapshot_result), _status_event(status), snapshot_result)
                )
            event_rows = [
                dict(row)
                for row in connection.execute(
                    "SELECT sequence, event_type, payload_json FROM task_events "
                    "WHERE task_id=? AND event_type IN "
                    "('finished','error','cancelled','artifact_finalized','artifact_rejected') "
                    "ORDER BY sequence",
                    (task_id,),
                ).fetchall()
            ]
            for event in event_rows:
                payload = _json_object(event["payload_json"])
                event_type = str(event["event_type"])
                ref = _valid_result_item(
                    connection,
                    str(payload.get("result_id") or ""),
                    task_id,
                    event_type,
                )
                if payload.get("result_id") and ref is None:
                    if not isinstance(payload.get("result"), dict) or not payload.get("result"):
                        for key in ("result_id", "result_hash", "result_summary"):
                            payload.pop(key, None)
                        connection.execute(
                            "UPDATE task_events SET payload_json=? WHERE sequence=?",
                            (
                                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                                int(event["sequence"]),
                            ),
                        )
                        counters["invalid_event_refs_removed"] += 1
                        continue
                    # A full result can repair a stale reference without
                    # losing the event's result semantics.
                if ref:
                    options.append(
                        (
                            str(ref["canonical_json"]),
                            event_type,
                            dict(ref["result"]),
                        )
                    )
                value = payload.get("result")
                if isinstance(value, dict) and value:
                    options.append((_canonical(value), event_type, value))
            if not options:
                continue
            post_options = [
                option
                for option in options
                if option[1] in {"artifact_finalized", "artifact_rejected"}
            ]
            selected_options = post_options or options
            distinct = {option[0] for option in selected_options}
            if len(distinct) > 1:
                counters["conflict_tasks"].append(task_id)
                continue
            canonical = next(iter(distinct))
            result = next(option[2] for option in selected_options if option[0] == canonical)
            event_type = post_options[0][1] if post_options else _status_event(status)
            if not post_options:
                event_types = [option[1] for option in options if option[1]]
                if event_types:
                    event_type = event_types[0]
            encoded = canonical.encode("utf-8")
            result_hash = _digest(canonical)
            result_id = "tr-" + _digest(f"{task_id}\0{event_type}\0{result_hash}")
            created_time = str(
                snapshot["finished_time"] or snapshot["updated_time"] or ""
            )
            cursor = connection.execute(
                "INSERT OR IGNORE INTO task_results "
                "(result_id, task_id, terminal_event_type, canonical_json, sha256, "
                "byte_size, schema_version, created_time) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    result_id,
                    task_id,
                    event_type,
                    canonical,
                    result_hash,
                    len(encoded),
                    1,
                    created_time,
                ),
            )
            counters["result_rows_created"] += int(cursor.rowcount or 0)
            summary = json.dumps(
                _result_summary(result, len(encoded)),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            if snapshot_result and _canonical(snapshot_result) != canonical:
                counters["conflict_tasks"].append(task_id)
                continue
            if snapshot_result or snapshot["result_id"]:
                cursor = connection.execute(
                    "UPDATE task_snapshots SET result_json='{}', result_id=?, "
                    "result_hash=?, result_summary_json=? WHERE task_id=?",
                    (result_id, result_hash, summary, task_id),
                )
                if snapshot_result:
                    counters["snapshot_full_results_removed"] += int(cursor.rowcount or 0)
                    counters["logical_result_bytes_removed"] += max(
                        0, len(_canonical(snapshot_result).encode("utf-8")) - 2
                    )
            for event in event_rows:
                payload = _json_object(event["payload_json"])
                value = payload.get("result")
                if not isinstance(value, dict) or not value:
                    continue
                if _canonical(value) != canonical:
                    # A pending finished result can legitimately be superseded
                    # by one unambiguous artifact_finalized result. Keep the
                    # event row and its historical meaning; only the selected
                    # final projection is stripped in this pass.
                    continue
                payload.pop("result", None)
                payload.update(
                    {
                        "result_id": result_id,
                        "result_hash": result_hash,
                        "result_summary": json.loads(summary),
                    }
                )
                connection.execute(
                    "UPDATE task_events SET payload_json=? WHERE sequence=?",
                    (
                        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                        int(event["sequence"]),
                    ),
                )
                counters["event_full_results_removed"] += 1
                counters["logical_result_bytes_removed"] += len(
                    _canonical(value).encode("utf-8")
                )
        counters["duplicate_payload_rows_removed"] = (
            counters["snapshot_full_results_removed"]
            + counters["event_full_results_removed"]
        )
        connection.commit()
    return counters


def _set_result_authority_state(database: Path, *, updated_by: str) -> dict[str, Any]:
    with closing(_connect_candidate(database)) as connection:
        tables = set(_tables(connection))
        if "task_result_storage_rollout" not in tables:
            return {"state": "NOT_AVAILABLE", "revision": 0}
        row = connection.execute(
            "SELECT state, revision FROM task_result_storage_rollout WHERE singleton_id=1"
        ).fetchone()
        if row is None:
            return {"state": "NOT_AVAILABLE", "revision": 0}
        current_state = str(row["state"])
        current_revision = int(row["revision"])
        if current_state == "RESULT_REF_AUTHORITY":
            return {"state": current_state, "revision": current_revision}
        next_revision = current_revision + 1
        now = datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        if "task_result_storage_rollout_audit" in tables:
            connection.execute(
                "INSERT OR IGNORE INTO task_result_storage_rollout_audit "
                "(revision, from_state, to_state, changed_at, changed_by, reason, schema_version) "
                "VALUES (?, ?, 'RESULT_REF_AUTHORITY', ?, ?, ?, 4)",
                (
                    next_revision,
                    current_state,
                    now,
                    updated_by,
                    "DEV candidate verified task result reference authority",
                ),
            )
        connection.execute(
            "UPDATE task_result_storage_rollout SET state='RESULT_REF_AUTHORITY', "
            "revision=?, updated_at=?, updated_by=?, reason=? WHERE singleton_id=1",
            (
                next_revision,
                now,
                updated_by,
                "DEV candidate verified task result reference authority",
            ),
        )
        connection.commit()
        return {"state": "RESULT_REF_AUTHORITY", "revision": next_revision}


def _quick_check(path: Path) -> dict[str, Any]:
    with closing(_connect_read_only(path)) as connection:
        quick = str(connection.execute("PRAGMA quick_check").fetchone()[0])
        foreign = [
            dict(row)
            for row in connection.execute("PRAGMA foreign_key_check").fetchall()
        ]
    return {
        "quick_check": quick,
        "foreign_key_errors": foreign,
        "pass": quick.casefold() == "ok" and not foreign,
    }


def _site_total(site_dir: Path) -> int:
    return sum(
        int(path.stat().st_size)
        for path in site_dir.rglob("*")
        if path.is_file() and not path.is_symlink()
    )


def _safe_name(site: str) -> str:
    return hashlib.sha256(site.encode("utf-8")).hexdigest()[:12]


def _write_reports(output_dir: Path, report: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "TASKS_DB_SPACE_AUDIT.json"
    md_path = output_dir / "TASKS_DB_SPACE_AUDIT.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    lines = [
        "# tasks.db 表级空间审计与候选瘦身报告",
        "",
        f"- 生成时间：{report['generated_at']}",
        f"- 数据根：{report['data_root']}",
        f"- 模式：{report['mode']}",
        "- 生产数据：NOT TOUCHED",
        "",
        "## 结论",
        "",
        f"TASKS_DB_TOP_TABLES = {report.get('top_tables', [])}",
        "",
        "task_snapshots 是当前/恢复投影，task_results.canonical_json 是任务结果 "
        "authority；事件只在已验证结果引用后去除重复 full result。Repeated progress "
        "仅统计，不按 Recent10 删除。",
        "",
        "## Site 指标",
        "",
        "| site | db before bytes | db after bytes | reclaimed | reclaim % | site total before | site total after | external retained |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in report.get("sites", []):
        lines.append(
            "| {site} | {before} | {after} | {reclaimed} | {percent:.2f}% | "
            "{site_before} | {site_after} | {external} |".format(
                site=item.get("site", ""),
                before=item.get("tasks_db_before_bytes", item.get("db_size_bytes", 0)),
                after=item.get("tasks_db_after_bytes", ""),
                reclaimed=item.get("tasks_db_reclaimed_bytes", ""),
                percent=float(item.get("tasks_db_reclaim_percent", 0)),
                site_before=item.get("site_total_before", ""),
                site_after=item.get("site_total_after", ""),
                external=item.get("external_bytes_created", 0),
            )
        )
    lines.extend(["", "## 表级 Top 占用", ""])
    for item in report.get("sites", []):
        lines.extend(
            [
                f"### {item.get('site', '')}",
                "",
                "| rank | table | rows | table bytes | index bytes | avg row bytes | percent |",
                "| ---: | --- | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        tables = item.get("audit_after", item.get("audit", {})).get("tables", [])
        for rank, table in enumerate(tables[:10], 1):
            lines.append(
                "| {rank} | {table} | {rows} | {table_bytes} | {index_bytes} | "
                "{avg} | {percent:.2f}% |".format(
                    rank=rank,
                    table=table.get("table", ""),
                    rows=table.get("row_count", 0),
                    table_bytes=table.get("table_bytes", 0),
                    index_bytes=table.get("index_bytes", 0),
                    avg=table.get("avg_row_bytes", 0),
                    percent=float(table.get("percentage_of_tasks_db", 0)),
                )
            )
        task = item.get("audit_after", item.get("audit", {})).get("task_storage", {})
        duplicate = task.get("duplication", {})
        lines.extend(
            [
                "",
                f"- task_events rows: {item.get('task_events_rows_after', task.get('semantics', {}).get('event_rows', 0))}",
                f"- task_snapshots rows: {item.get('task_snapshots_rows_after', task.get('semantics', {}).get('snapshot_rows', 0))}",
                f"- duplicate payload rows removable: {duplicate.get('duplicate_payload_rows', 0)}",
                f"- obsolete snapshot rows: {duplicate.get('obsolete_snapshot_rows', 0)}",
                f"- quick_check: {item.get('quick_check_after', item.get('audit', {}).get('quick_check', ''))}",
                "",
            ]
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _discover_sites(data_root: Path, site_filter: str | None) -> list[tuple[str, Path]]:
    sites_dir = data_root / "sites"
    result = []
    for site_dir in sorted(sites_dir.iterdir() if sites_dir.is_dir() else []):
        if not site_dir.is_dir() or site_dir.is_symlink():
            continue
        if site_filter and site_dir.name != site_filter:
            continue
        database = site_dir / "db" / "tasks.db"
        if database.is_file() and not database.is_symlink():
            result.append((site_dir.name, database))
    return result


def _ensure_output_dir(output_dir: Path) -> Path:
    resolved = output_dir.resolve()
    if DIAGNOSTIC_ROOT not in resolved.parents and resolved != DIAGNOSTIC_ROOT:
        raise ValueError(f"report output must be under {DIAGNOSTIC_ROOT}")
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _checkpoint_dev_source(database: Path) -> dict[str, Any]:
    result = {
        "performed": False,
        "busy": False,
        "wal_before": (
            database.with_name(database.name + "-wal").stat().st_size
            if database.with_name(database.name + "-wal").is_file()
            else 0
        ),
    }
    wal = database.with_name(database.name + "-wal")
    if not wal.is_file() or wal.stat().st_size == 0:
        return result
    try:
        with sqlite3.connect(database, timeout=5.0) as connection:
            connection.execute("PRAGMA busy_timeout=5000")
            row = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            busy = int(row[0] or 0) if row else 1
            result.update(
                {
                    "performed": busy == 0 and (not wal.is_file() or wal.stat().st_size == 0),
                    "busy": busy != 0,
                    "checkpoint_result": [int(value or 0) for value in row] if row else [],
                    "wal_after": wal.stat().st_size if wal.is_file() else 0,
                }
            )
    except sqlite3.Error as exc:
        result.update({"busy": True, "error": f"{exc.__class__.__name__}: {exc}"})
    return result


def _apply_one_site(
    *,
    site: str,
    site_dir: Path,
    source: Path,
    run_dir: Path,
) -> dict[str, Any]:
    site_report: dict[str, Any] = {
        "site": site,
        "db_path": str(source),
        "site_total_before": _site_total(site_dir),
        "external_bytes_created": 0,
    }
    checkpoint = _checkpoint_dev_source(source)
    site_report["source_checkpoint"] = checkpoint
    revision_before = source_revision(source)
    site_report["source_revision_before"] = revision_before
    staging = run_dir / "staging" / _safe_name(site)
    frozen = staging / "source.tasks.db"
    candidate = staging / "candidate.tasks.db"
    compact = staging / "tasks.compact.candidate.db"
    _backup_database(source, frozen)
    site_report["audit"] = _task_db_audit(
        frozen, site=site, source_database=source, site_dir=site_dir
    )
    site_report["tasks_db_before_bytes"] = int(site_report["audit"]["db_size_bytes"])
    before_semantics = site_report["audit"]["task_storage"]["semantics"]
    plan = site_report["audit"]["task_storage"]["duplication"]
    site_report["migration_plan"] = {
        "TASK_ROWS": before_semantics["task_rows"],
        "EVENT_ROWS": before_semantics["event_rows"],
        "SNAPSHOT_ROWS": before_semantics["snapshot_rows"],
        "DUPLICATE_PAYLOAD_ROWS": plan.get("duplicate_payload_rows", 0),
        "OBSOLETE_SNAPSHOT_ROWS": plan.get("obsolete_snapshot_rows", 0),
        "ESTIMATED_RECLAIMABLE_BYTES": plan.get("duplicate_payload_bytes", 0),
        "note": (
            "Full result projections are stripped only after result authority binding. "
            "Progress duplicates are observe-only."
        ),
    }
    shutil.copy2(frozen, candidate)
    mutation = _apply_result_projection_cleanup(candidate)
    site_report["migration"] = mutation
    if not mutation.get("conflict_tasks") and not mutation.get("invalid_tasks"):
        site_report["rollout"] = _set_result_authority_state(
            candidate, updated_by="tasks-db-compaction"
        )
    else:
        site_report["rollout"] = {"state": "NOT_PROMOTED", "reason": "conflict/invalid task"}
    with closing(_connect_candidate(candidate)) as connection:
        connection.execute("VACUUM INTO ?", (str(compact),))
    compact_check = _quick_check(compact)
    site_report["compact_quick_check"] = compact_check
    if not compact_check["pass"]:
        raise sqlite3.DatabaseError(f"compact quick_check failed for {site}: {compact_check}")
    compact_audit = _task_db_audit(compact, site=site, source_database=compact)
    site_report["audit_candidate"] = compact_audit
    candidate_semantics = compact_audit["task_storage"]["semantics"]
    parity = {
        "TASK_LIST_PARITY": before_semantics["task_list_digest"]
        == candidate_semantics["task_list_digest"],
        "TASK_DETAIL_PARITY": before_semantics["task_detail_digest"]
        == candidate_semantics["task_detail_digest"],
        "ONLINE_MR_CURRENT_SESSIONS_PARITY": before_semantics["sessions"]["digest"]
        == candidate_semantics["sessions"]["digest"],
    }
    site_report["parity_candidate"] = parity
    if not all(parity.values()):
        raise RuntimeError(f"candidate parity failed for {site}: {parity}")
    source_after_prepare = source_revision(source)
    site_report["source_revision_before_replace"] = source_after_prepare
    if _source_content_revision(source_after_prepare) != _source_content_revision(revision_before):
        site_report["replace"] = {
            "status": "NOT_RUN",
            "reason": "STALE_SOURCE: source changed while candidate was prepared",
        }
        site_report["status"] = "NOT_RUN"
        return site_report
    rollback_dir = run_dir / "rollback" / _safe_name(site)
    rollback_dir.mkdir(parents=True, exist_ok=True)
    rollback = rollback_dir / "tasks.db"
    shutil.copy2(source, rollback)
    site_report["external_bytes_created"] += int(rollback.stat().st_size)
    sidecar_backups = []
    for suffix in ("-wal", "-shm"):
        sidecar = source.with_name(source.name + suffix)
        if sidecar.is_file():
            backup = rollback_dir / ("tasks.db" + suffix)
            shutil.copy2(sidecar, backup)
            sidecar_backups.append(str(backup))
            site_report["external_bytes_created"] += int(backup.stat().st_size)
            sidecar.unlink()
    os.replace(compact, source)
    site_report["replace"] = {"status": "ATOMIC_REPLACE", "rollback": str(rollback)}
    site_report["rollback_sidecars"] = sidecar_backups
    after_check = _quick_check(source)
    site_report["quick_check_after"] = after_check["quick_check"]
    if not after_check["pass"]:
        raise sqlite3.DatabaseError(f"source quick_check failed after replace: {site}")
    audit_after = _task_db_audit(
        source, site=site, source_database=source, site_dir=site_dir
    )
    site_report["audit_after"] = audit_after
    after_semantics = audit_after["task_storage"]["semantics"]
    site_report["parity"] = {
        "TASK_LIST_PARITY": before_semantics["task_list_digest"]
        == after_semantics["task_list_digest"],
        "TASK_DETAIL_PARITY": before_semantics["task_detail_digest"]
        == after_semantics["task_detail_digest"],
        "TASK_RESTART_RECOVERY": before_semantics["active_task_count"]
        == after_semantics["active_task_count"]
        and before_semantics["pending_task_count"]
        == after_semantics["pending_task_count"]
        and before_semantics["running_task_count"]
        == after_semantics["running_task_count"],
        "ONLINE_MR_CURRENT_SESSIONS_PARITY": before_semantics["sessions"]["digest"]
        == after_semantics["sessions"]["digest"],
    }
    site_report["tasks_db_after_bytes"] = int(audit_after["db_size_bytes"])
    site_report["tasks_db_reclaimed_bytes"] = (
        site_report["tasks_db_before_bytes"] - site_report["tasks_db_after_bytes"]
    )
    site_report["tasks_db_reclaim_percent"] = (
        site_report["tasks_db_reclaimed_bytes"]
        * 100
        / max(1, site_report["tasks_db_before_bytes"])
    )
    site_report["site_total_after"] = _site_total(site_dir)
    site_report["site_total_after_plus_external"] = (
        site_report["site_total_after"] + site_report["external_bytes_created"]
    )
    site_report["task_events_rows_before"] = before_semantics["event_rows"]
    site_report["task_events_rows_after"] = after_semantics["event_rows"]
    site_report["task_snapshots_rows_before"] = before_semantics["snapshot_rows"]
    site_report["task_snapshots_rows_after"] = after_semantics["snapshot_rows"]
    site_report["duplicate_payload_rows_removed"] = mutation.get(
        "duplicate_payload_rows_removed", 0
    )
    site_report["obsolete_snapshot_rows_removed"] = mutation.get(
        "obsolete_snapshot_rows_removed", 0
    )
    if not all(site_report["parity"].values()):
        raise RuntimeError(f"post-replace parity failed for {site}: {site_report['parity']}")
    site_report["status"] = "PASS"
    return site_report


def run(
    *,
    mode: str,
    data_root: Path,
    output_dir: Path,
    site_filter: str | None = None,
) -> dict[str, Any]:
    data_root = data_root.resolve()
    output_dir = _ensure_output_dir(output_dir)
    if mode == "apply" and data_root != DEVELOPMENT_DATA_ROOT:
        raise ValueError(
            f"--apply is DEV-only and requires exactly {DEVELOPMENT_DATA_ROOT}"
        )
    run_dir = output_dir / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    sites = _discover_sites(data_root, site_filter)
    report: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "mode": mode,
        "data_root": str(data_root),
        "production_data_touched": "NO",
        "sites": [],
    }
    for site, source in sites:
        site_dir = source.parent.parent
        if mode == "apply":
            try:
                item = _apply_one_site(
                    site=site, site_dir=site_dir, source=source, run_dir=run_dir
                )
            except Exception as exc:
                item = {
                    "site": site,
                    "db_path": str(source),
                    "status": "FAILED",
                    "error": f"{exc.__class__.__name__}: {exc}",
                    "site_total_after": _site_total(site_dir),
                    "source_revision_after_failure": source_revision(source),
                }
        else:
            revision_before = source_revision(source)
            staging = run_dir / "staging" / _safe_name(site)
            frozen = staging / "source.tasks.db"
            _backup_database(source, frozen)
            audit = _task_db_audit(
                frozen, site=site, source_database=source, site_dir=site_dir
            )
            revision_after = source_revision(source)
            semantics = audit["task_storage"]["semantics"]
            duplication = audit["task_storage"]["duplication"]
            item = {
                "site": site,
                "db_path": str(source),
                "source_revision_before": revision_before,
                "source_revision_after": revision_after,
                "source_changed_during_snapshot": _source_content_revision(revision_before)
                != _source_content_revision(revision_after),
                "site_total_before": _site_total(site_dir),
                "audit": audit,
                "db_size_bytes": audit["db_size_bytes"],
                "TASK_ROWS": semantics["task_rows"],
                "EVENT_ROWS": semantics["event_rows"],
                "SNAPSHOT_ROWS": semantics["snapshot_rows"],
                "DUPLICATE_PAYLOAD_ROWS": duplication.get("duplicate_payload_rows", 0),
                "OBSOLETE_SNAPSHOT_ROWS": duplication.get("obsolete_snapshot_rows", 0),
                "ESTIMATED_RECLAIMABLE_BYTES": duplication.get(
                    "duplicate_payload_bytes", 0
                ),
                "dry_run": {
                    "logical_cleanup": "candidate-only",
                    "atomic_replace": "NOT_RUN",
                    "external_bytes_created": 0,
                    "TASKS_DB_SIZE_AFTER": "NOT_RUN",
                },
            }
        report["sites"].append(item)
    all_tables: list[tuple[str, int]] = []
    for item in report["sites"]:
        audit = item.get("audit_after", item.get("audit", {}))
        for table in audit.get("tables", []):
            all_tables.append(
                (
                    f"{item.get('site')}:{table.get('table')}",
                    int(table.get("table_bytes", 0)) + int(table.get("index_bytes", 0)),
                )
            )
    report["top_tables"] = [
        name
        for name, _bytes in sorted(all_tables, key=lambda value: value[1], reverse=True)[:10]
    ]
    if mode == "apply" and report["sites"] and all(
        item.get("status") == "PASS" for item in report["sites"]
    ):
        shutil.rmtree(run_dir / "staging", ignore_errors=True)
        report["temporary_staging_cleaned"] = True
    elif mode == "apply":
        report["temporary_staging_cleaned"] = False
    _write_reports(output_dir, report)
    return report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--audit", action="store_true", help="read-only audit (default)")
    mode.add_argument("--dry-run", action="store_true", help="frozen candidate plan only")
    mode.add_argument("--apply", action="store_true", help="DEV candidate migration and replace")
    parser.add_argument("--data-root", type=Path, default=DEVELOPMENT_DATA_ROOT)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--site", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    mode = "apply" if args.apply else "dry-run" if args.dry_run else "audit"
    output_dir = args.output_dir or (
        DIAGNOSTIC_ROOT
        / f"tasks-db-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{mode}"
    )
    try:
        report = run(
            mode=mode,
            data_root=args.data_root,
            output_dir=output_dir,
            site_filter=args.site,
        )
    except Exception as exc:
        print(f"{exc.__class__.__name__}: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "mode": report["mode"],
                "output_dir": str(output_dir.resolve()),
                "sites": len(report["sites"]),
                "top_tables": report["top_tables"],
                "production_data_touched": report["production_data_touched"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if mode == "apply" and any(item.get("status") != "PASS" for item in report["sites"]):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
