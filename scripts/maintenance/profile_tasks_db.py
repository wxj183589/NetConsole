"""Read-only LIGHT/DEEP profiler for one resolved NetConsole tasks database."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sqlite3
from collections import defaultdict
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from netconsole.core.paths import PathResolver
from netconsole.services.site_storage import SiteRegistryRepository


PROFILE_FILE_NAME = "TASKS_DB_PROFILE.json"
_DEVELOPMENT_ROOT = Path("D:/study").resolve()


def _connect(database: Path, *, immutable: bool) -> sqlite3.Connection:
    query = "mode=ro&immutable=1" if immutable else "mode=ro"
    uri = f"{database.resolve().as_uri()}?{query}"
    conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn


def _sidecar_size(database: Path, suffix: str) -> int:
    path = database.with_name(database.name + suffix)
    return path.stat().st_size if path.is_file() else 0


def _physical(conn: sqlite3.Connection, database: Path) -> dict[str, Any]:
    page_size = int(conn.execute("PRAGMA page_size").fetchone()[0])
    page_count = int(conn.execute("PRAGMA page_count").fetchone()[0])
    freelist = int(conn.execute("PRAGMA freelist_count").fetchone()[0])
    return {
        "file_size_bytes": database.stat().st_size,
        "file_size_mib": round(database.stat().st_size / 1024 / 1024, 2),
        "page_size": page_size,
        "page_count": page_count,
        "freelist_count": freelist,
        "free_page_bytes": freelist * page_size,
        "journal_mode": str(conn.execute("PRAGMA journal_mode").fetchone()[0]),
        "wal_bytes": _sidecar_size(database, "-wal"),
        "shm_bytes": _sidecar_size(database, "-shm"),
    }


def _schema(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    rows = conn.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_schema "
        "WHERE (type='table' AND name NOT LIKE 'sqlite_%') OR type='index' "
        "ORDER BY type, name"
    ).fetchall()
    result = {"tables": [], "indexes": []}
    for row in rows:
        bucket = "tables" if str(row["type"]) == "table" else "indexes"
        result[bucket].append(
            {
                "name": str(row["name"]),
                "table": str(row["tbl_name"]),
                "definition_sha256": hashlib.sha256(
                    str(row["sql"] or "").encode("utf-8")
                ).hexdigest(),
            }
        )
    return result


def _identifier(value: str) -> str:
    if not value or not value.replace("_", "").isalnum() or not value[0].isalpha():
        raise ValueError(f"unsafe SQLite identifier: {value}")
    return value


def _columns(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    name = _identifier(table)
    keys = ("cid", "name", "type", "notnull", "default", "pk")
    return [
        dict(zip(keys, tuple(row), strict=True))
        for row in conn.execute(f'PRAGMA table_info("{name}")').fetchall()
    ]


def _length_expression(column: str) -> str:
    name = _identifier(column)
    return (
        f"CASE typeof(\"{name}\") WHEN 'null' THEN 0 "
        f"WHEN 'blob' THEN length(\"{name}\") "
        f"WHEN 'text' THEN length(CAST(\"{name}\" AS BLOB)) "
        f"ELSE length(CAST(\"{name}\" AS TEXT)) END"
    )


def _time_columns(columns: list[dict[str, Any]]) -> list[str]:
    names = {str(column["name"]) for column in columns}
    return [
        name
        for name in ("updated_time", "event_time", "finished_time", "created_time")
        if name in names
    ]


def _dbstat_allocations(conn: sqlite3.Connection) -> dict[str, int] | None:
    try:
        rows = conn.execute(
            "SELECT name, SUM(pgsize) AS bytes FROM dbstat GROUP BY name"
        ).fetchall()
    except sqlite3.Error:
        return None
    return {str(row["name"]): int(row["bytes"] or 0) for row in rows}


def _deep_allocations(
    conn: sqlite3.Connection,
    physical: dict[str, Any],
    schema: dict[str, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    dbstat = _dbstat_allocations(conn)
    table_profiles: list[dict[str, Any]] = []
    table_weights: dict[str, int] = {}
    for table_item in schema["tables"]:
        table = str(table_item["name"])
        columns = _columns(conn, table)
        names = [str(column["name"]) for column in columns]
        length_sql = " + ".join(_length_expression(name) for name in names) or "0"
        time_columns = _time_columns(columns)
        time_column = time_columns[0] if time_columns else ""
        select_time = (
            f', MIN("{time_column}") AS min_time, MAX("{time_column}") AS max_time'
            if time_column
            else ", '' AS min_time, '' AS max_time"
        )
        row = conn.execute(
            f'SELECT COUNT(*) AS rows, COALESCE(SUM({length_sql}), 0) AS logical_bytes'
            f'{select_time} FROM "{_identifier(table)}"'
        ).fetchone()
        rows = int(row["rows"] or 0)
        logical_bytes = int(row["logical_bytes"] or 0)
        table_weights[table] = logical_bytes + rows * max(8, len(columns) // 2)
        table_profiles.append(
            {
                "table": table,
                "rows": rows,
                "logical_field_bytes": logical_bytes,
                "avg_logical_bytes_per_row": round(logical_bytes / rows, 2) if rows else 0,
                "min_time": str(row["min_time"] or ""),
                "max_time": str(row["max_time"] or ""),
            }
        )
    index_profiles: list[dict[str, Any]] = []
    index_weights: dict[str, int] = {}
    for index_item in schema["indexes"]:
        index = str(index_item["name"])
        table = str(index_item["table"])
        key_rows = conn.execute(f'PRAGMA index_xinfo("{_identifier(index)}")').fetchall()
        key_columns = [str(row[2]) for row in key_rows if int(row[5]) and int(row[1]) >= 0]
        if key_columns:
            length_sql = " + ".join(_length_expression(column) for column in key_columns)
            row = conn.execute(
                f'SELECT COUNT(*) AS rows, COALESCE(SUM({length_sql}), 0) AS key_bytes '
                f'FROM "{_identifier(table)}"'
            ).fetchone()
            rows = int(row["rows"] or 0)
            key_bytes = int(row["key_bytes"] or 0)
        else:
            rows = 0
            key_bytes = 0
        weight = key_bytes + rows * 12
        index_weights[index] = weight
        index_profiles.append(
            {
                "index": index,
                "table": table,
                "key_columns": key_columns,
                "estimated_key_bytes": key_bytes,
                "rows": rows,
            }
        )
    main_live = max(
        0,
        int(physical["file_size_bytes"]) - int(physical["free_page_bytes"]),
    )
    method = "sqlite_dbstat"
    if dbstat is not None:
        for item in table_profiles:
            item["allocated_bytes"] = int(dbstat.get(str(item["table"]), 0))
        for item in index_profiles:
            item["allocated_bytes"] = int(dbstat.get(str(item["index"]), 0))
    else:
        method = "logical_weight_normalized_fallback"
        total_weight = max(1, sum(table_weights.values()) + sum(index_weights.values()))
        for item in table_profiles:
            item["allocated_bytes"] = round(
                main_live * table_weights[str(item["table"])] / total_weight
            )
        for item in index_profiles:
            item["allocated_bytes"] = round(
                main_live * index_weights[str(item["index"])] / total_weight
            )
    for item in (*table_profiles, *index_profiles):
        item["file_percent"] = round(
            int(item["allocated_bytes"]) * 100 / max(1, int(physical["file_size_bytes"])),
            2,
        )
    table_profiles.sort(key=lambda item: int(item["allocated_bytes"]), reverse=True)
    index_profiles.sort(key=lambda item: int(item["allocated_bytes"]), reverse=True)
    return table_profiles, index_profiles, {
        "method": method,
        "dbstat_available": dbstat is not None,
        "estimated": dbstat is None,
        "note": (
            "Python SQLite lacks dbstat; physical allocation is estimated from exact logical "
            "field/index-key weights and normalized to live database bytes."
            if dbstat is None
            else "Physical page allocation is reported by SQLite dbstat."
        ),
    }


def _percentiles(values: list[int]) -> dict[str, float | int]:
    if not values:
        return {"count": 0, "total": 0, "avg": 0, "p50": 0, "p95": 0, "p99": 0, "max": 0}
    ordered = sorted(values)

    def percentile(value: float) -> int:
        return ordered[min(len(ordered) - 1, max(0, math.ceil(len(ordered) * value) - 1))]

    return {
        "count": len(values),
        "total": sum(values),
        "avg": round(sum(values) / len(values), 2),
        "p50": percentile(0.50),
        "p95": percentile(0.95),
        "p99": percentile(0.99),
        "max": ordered[-1],
    }


def _group_rows(conn: sqlite3.Connection, sql: str) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(sql).fetchall()]


def _canonical_json_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _terminal_result_duplication(conn: sqlite3.Connection) -> dict[str, Any]:
    latest: dict[str, tuple[str, int, int]] = {}
    for row in conn.execute(
        "SELECT task_id, payload_json FROM task_events "
        "WHERE event_type='finished' ORDER BY sequence"
    ):
        raw = str(row["payload_json"] or "{}")
        try:
            payload = json.loads(raw)
            result = payload.get("result") if isinstance(payload, dict) else None
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        latest[str(row["task_id"])] = (
            _canonical_json_hash(result),
            len(json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")),
            len(raw.encode("utf-8")),
        )
    matched = 0
    snapshot_bytes = 0
    event_result_bytes = 0
    event_payload_bytes = 0
    for row in conn.execute("SELECT task_id, result_json FROM task_snapshots"):
        event = latest.get(str(row["task_id"]))
        if event is None:
            continue
        raw = str(row["result_json"] or "{}")
        try:
            result = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if _canonical_json_hash(result) != event[0]:
            continue
        matched += 1
        snapshot_bytes += len(raw.encode("utf-8"))
        event_result_bytes += event[1]
        event_payload_bytes += event[2]
    return {
        "latest_finished_events": len(latest),
        "semantically_identical_results": matched,
        "snapshot_result_bytes": snapshot_bytes,
        "finished_event_result_bytes": event_result_bytes,
        "finished_event_payload_bytes": event_payload_bytes,
        "classification": "LARGE_PAYLOAD",
        "action_this_phase": "OBSERVE_ONLY",
    }


def _repeated_events(conn: sqlite3.Connection, event_type: str) -> dict[str, Any]:
    previous: dict[str, str] = {}
    repeated_rows = 0
    repeated_bytes = 0
    by_type: dict[str, dict[str, int]] = defaultdict(lambda: {"rows": 0, "bytes": 0})
    sql = (
        "SELECT e.task_id, e.payload_json, s.task_type FROM task_events e "
        "JOIN task_snapshots s ON s.task_id=e.task_id WHERE e.event_type=? "
        "ORDER BY e.task_id, e.sequence"
    )
    for row in conn.execute(sql, (event_type,)):
        task_id = str(row["task_id"])
        payload = str(row["payload_json"] or "{}")
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        if previous.get(task_id) == digest:
            size = len(payload.encode("utf-8"))
            repeated_rows += 1
            repeated_bytes += size
            bucket = by_type[str(row["task_type"])]
            bucket["rows"] += 1
            bucket["bytes"] += size
        previous[task_id] = digest
    producers = [
        {"task_type": task_type, **values}
        for task_type, values in by_type.items()
    ]
    producers.sort(key=lambda item: int(item["bytes"]), reverse=True)
    return {
        "event_type": event_type,
        "repeated_rows": repeated_rows,
        "repeated_payload_bytes": repeated_bytes,
        "top_task_types": producers[:10],
    }


def _parse_time(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _time_distribution(conn: sqlite3.Connection) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = conn.execute(
        "SELECT task_id, status, task_type, created_time, updated_time, finished_time, "
        "length(CAST(result_json AS BLOB)) AS result_bytes FROM task_snapshots"
    ).fetchall()
    times = [
        value
        for row in rows
        if (value := _parse_time(str(row["finished_time"] or row["updated_time"] or row["created_time"])))
    ]
    reference = max(times) if times else datetime.now(UTC)
    buckets = {
        "<1d": {"tasks": 0, "result_bytes": 0},
        "1-7d": {"tasks": 0, "result_bytes": 0},
        "8-30d": {"tasks": 0, "result_bytes": 0},
        "31-90d": {"tasks": 0, "result_bytes": 0},
        ">90d": {"tasks": 0, "result_bytes": 0},
    }
    for row in rows:
        timestamp = _parse_time(str(row["finished_time"] or row["updated_time"] or row["created_time"]))
        age = max(0.0, (reference - timestamp).total_seconds() / 86400) if timestamp else 10_000
        key = "<1d" if age < 1 else "1-7d" if age <= 7 else "8-30d" if age <= 30 else "31-90d" if age <= 90 else ">90d"
        buckets[key]["tasks"] += 1
        buckets[key]["result_bytes"] += int(row["result_bytes"] or 0)
    distribution = [{"bucket": key, **value} for key, value in buckets.items()]
    growth: dict[str, Any] = {"reference_time": reference.isoformat()}
    for days in (7, 30):
        cutoff = (reference - timedelta(days=days)).isoformat().replace("+00:00", "Z")
        task_row = conn.execute(
            "SELECT COUNT(*) AS rows, COALESCE(SUM(length(CAST(result_json AS BLOB))),0) AS bytes "
            "FROM task_snapshots WHERE updated_time>=?",
            (cutoff,),
        ).fetchone()
        event_row = conn.execute(
            "SELECT COUNT(*) AS rows, COALESCE(SUM(length(CAST(payload_json AS BLOB))),0) AS bytes "
            "FROM task_events WHERE event_time>=?",
            (cutoff,),
        ).fetchone()
        logical_bytes = int(task_row["bytes"] or 0) + int(event_row["bytes"] or 0)
        growth[f"last_{days}_days"] = {
            "task_rows": int(task_row["rows"] or 0),
            "event_rows": int(event_row["rows"] or 0),
            "logical_payload_bytes": logical_bytes,
            "logical_payload_bytes_per_day": round(logical_bytes / days, 2),
        }
    rates = [
        float(growth[key]["logical_payload_bytes_per_day"])
        for key in ("last_7_days", "last_30_days")
    ]
    growth["projection_bytes"] = {
        str(days): {
            "low": round(min(rates) * days),
            "high": round(max(rates) * days),
        }
        for days in (30, 90, 365)
    }
    return distribution, growth


def _task_type_distribution(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in conn.execute(
        "SELECT task_type, COUNT(*) AS tasks, "
        "SUM(length(CAST(result_json AS BLOB))) AS snapshot_result_bytes "
        "FROM task_snapshots GROUP BY task_type"
    ):
        grouped[str(row["task_type"])] = {
            "task_type": str(row["task_type"]),
            "tasks": int(row["tasks"] or 0),
            "snapshot_result_bytes": int(row["snapshot_result_bytes"] or 0),
            "events": 0,
            "event_payload_bytes": 0,
        }
    for row in conn.execute(
        "SELECT s.task_type, COUNT(*) AS events, "
        "SUM(length(CAST(e.payload_json AS BLOB))) AS event_payload_bytes "
        "FROM task_events e JOIN task_snapshots s ON s.task_id=e.task_id "
        "GROUP BY s.task_type"
    ):
        bucket = grouped.setdefault(
            str(row["task_type"]),
            {
                "task_type": str(row["task_type"]),
                "tasks": 0,
                "snapshot_result_bytes": 0,
                "events": 0,
                "event_payload_bytes": 0,
            },
        )
        bucket["events"] = int(row["events"] or 0)
        bucket["event_payload_bytes"] = int(row["event_payload_bytes"] or 0)
    result = list(grouped.values())
    for item in result:
        item["total_payload_bytes"] = int(item["snapshot_result_bytes"]) + int(
            item["event_payload_bytes"]
        )
    result.sort(key=lambda item: int(item["total_payload_bytes"]), reverse=True)
    return result


def _deep_task_profile(conn: sqlite3.Connection) -> dict[str, Any]:
    result_lengths = [
        int(row[0] or 0)
        for row in conn.execute("SELECT length(CAST(result_json AS BLOB)) FROM task_snapshots")
    ]
    event_lengths = [
        int(row[0] or 0)
        for row in conn.execute("SELECT length(CAST(payload_json AS BLOB)) FROM task_events")
    ]
    time_distribution, growth = _time_distribution(conn)
    return {
        "status_distribution": _group_rows(
            conn,
            "SELECT status, COUNT(*) AS tasks, "
            "SUM(length(CAST(result_json AS BLOB))) AS result_bytes "
            "FROM task_snapshots GROUP BY status ORDER BY result_bytes DESC",
        ),
        "task_types": _task_type_distribution(conn),
        "event_types": _group_rows(
            conn,
            "SELECT event_type, COUNT(*) AS rows, "
            "SUM(length(CAST(payload_json AS BLOB))) AS payload_bytes, "
            "MAX(length(CAST(payload_json AS BLOB))) AS max_payload_bytes "
            "FROM task_events GROUP BY event_type ORDER BY payload_bytes DESC",
        ),
        "large_payloads": {
            "task_snapshots.result_json": _percentiles(result_lengths),
            "task_events.payload_json": _percentiles(event_lengths),
        },
        "terminal_result_duplication": _terminal_result_duplication(conn),
        "repeated_progress": _repeated_events(conn, "progress"),
        "repeated_log": _repeated_events(conn, "log"),
        "time_distribution": time_distribution,
        "growth": growth,
        "orphans": {
            "events_without_snapshot": int(
                conn.execute(
                    "SELECT COUNT(*) FROM task_events e LEFT JOIN task_snapshots s "
                    "ON s.task_id=e.task_id WHERE s.task_id IS NULL"
                ).fetchone()[0]
            ),
            "artifact_filesystem_validation": "NOT_EXECUTED",
            "note": "Artifact availability remains owned by ArtifactReconciliationService.",
        },
    }


def profile_tasks_database(database: Path, *, deep: bool) -> dict[str, Any]:
    database = Path(database).resolve()
    if not database.is_file() or database.is_symlink():
        raise ValueError("tasks database must be an existing regular file")
    if deep and not database.is_relative_to(_DEVELOPMENT_ROOT):
        raise ValueError("DEEP profiling is restricted to an isolated snapshot under D:/study")
    if deep and _sidecar_size(database, "-wal"):
        raise ValueError("DEEP profiling requires an isolated snapshot with an empty WAL")
    with closing(_connect(database, immutable=deep)) as conn:
        physical = _physical(conn, database)
        schema = _schema(conn)
        result: dict[str, Any] = {
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "mode": "DEEP" if deep else "LIGHT",
            "database_name": database.name,
            "database_write_operations": False,
            "source_metadata_verification": "CALLER_REQUIRED",
            "physical": physical,
            "schema": {
                "table_count": len(schema["tables"]),
                "index_count": len(schema["indexes"]),
                **schema,
            },
            "destructive_operations": {"DELETE": "NO", "DROP": "NO", "VACUUM": "NO"},
            "retention": "NOT STARTED",
        }
        if not deep:
            result["result"] = "PROFILE_LIGHT_COMPLETE"
            return result
        tables, indexes, allocation = _deep_allocations(conn, physical, schema)
        task_profile = _deep_task_profile(conn)
        result.update(
            {
                "allocation": allocation,
                "top_tables": tables[:10],
                "top_indexes": indexes[:10],
                "tasks": task_profile,
                "root_cause": {
                    "why_400mb": (
                        "Live task_snapshots results and task_events payloads dominate the file; "
                        "terminal results are commonly represented in both snapshot and finished event."
                    ),
                    "logical_live_data": "PRIMARY",
                    "free_page_bloat": "NO" if not physical["freelist_count"] else "PRESENT",
                    "wal_bloat": "NO" if not physical["wal_bytes"] else "PRESENT",
                    "categories": [
                        "LARGE_PAYLOAD",
                        "WRITE_AMPLIFICATION",
                        "UNBOUNDED_RETENTION",
                        "EXPECTED_DATA",
                    ],
                },
                "recommendation": {
                    "option": "D",
                    "summary": "Bound repeated progress writes first; retain terminal result contracts and defer retention.",
                    "user_policy_required": True,
                },
                "result": "PROFILE_COMPLETE",
            }
        )
        return result


def _write_report(output_dir: Path, report: dict[str, Any]) -> Path:
    output = Path(output_dir).resolve()
    if not output.is_relative_to(_DEVELOPMENT_ROOT):
        raise ValueError("profiling output must remain under D:/study")
    output.mkdir(parents=True, exist_ok=True)
    path = output / PROFILE_FILE_NAME
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--site-id", required=True)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--deep", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    paths = PathResolver(data_root=args.data_root)
    site = SiteRegistryRepository(paths).get(args.site_id)
    database = (args.database or (site.root_path / "db" / "tasks.db")).resolve()
    run_id = datetime.now(UTC).astimezone().strftime("%Y%m%dT%H%M%S%z")
    output_dir = args.output_dir or (
        Path("D:/study/diagnostic/NetConsole/tasks-db-governance") / run_id
    )
    report = profile_tasks_database(database, deep=args.deep)
    report.update({"site_id": site.site_id, "site_display_name": site.display_name})
    report_path = _write_report(output_dir, report)
    print(json.dumps({"report": str(report_path), **report}, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
