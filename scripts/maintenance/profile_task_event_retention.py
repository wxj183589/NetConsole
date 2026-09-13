"""Read-only age distribution for production ``tasks.db.task_events``."""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from netconsole.models.task_state import TERMINAL_TASK_STATES


DEFAULT_ROOT = Path("D:/NetConsoleData")
BUCKETS = (
    "<=3d",
    "3-7d",
    "7-14d",
    "14-30d",
    "30-90d",
    ">90d",
)


def _connect(database: Path) -> sqlite3.Connection:
    uri = f"{database.resolve().as_uri()}?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True, timeout=2.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def _timestamp(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _bucket(age_seconds: float) -> str | None:
    if age_seconds < 0:
        return None
    age_days = age_seconds / 86_400
    if age_days <= 3:
        return "<=3d"
    if age_days <= 7:
        return "3-7d"
    if age_days <= 14:
        return "7-14d"
    if age_days <= 30:
        return "14-30d"
    if age_days <= 90:
        return "30-90d"
    return ">90d"


def _dbstat_bytes(connection: sqlite3.Connection) -> tuple[int, int, bool]:
    try:
        table_bytes = int(
            connection.execute(
                "SELECT COALESCE(SUM(pgsize), 0) FROM dbstat WHERE name='task_events'"
            ).fetchone()[0]
        )
        index_bytes = int(
            connection.execute(
                "SELECT COALESCE(SUM(pgsize), 0) FROM dbstat "
                "WHERE name IN (SELECT name FROM sqlite_schema "
                "WHERE type='index' AND tbl_name='task_events')"
            ).fetchone()[0]
        )
        return table_bytes, index_bytes, True
    except sqlite3.Error:
        return 0, 0, False


def _profile_database(database: Path, *, site_name: str, now: datetime) -> dict[str, Any]:
    result: dict[str, Any] = {
        "site_name": site_name,
        "path": str(database),
        "file_size_bytes": database.stat().st_size,
        "wal_bytes_observed": database.with_name(database.name + "-wal").stat().st_size
        if database.with_name(database.name + "-wal").is_file()
        else 0,
        "shm_bytes_observed": database.with_name(database.name + "-shm").stat().st_size
        if database.with_name(database.name + "-shm").is_file()
        else 0,
    }
    with _connect(database) as connection:
        table_bytes, index_bytes, dbstat_available = _dbstat_bytes(connection)
        result.update(
            {
                "task_event_rows": int(connection.execute("SELECT COUNT(*) FROM task_events").fetchone()[0]),
                "task_event_table_bytes": table_bytes,
                "task_event_index_bytes": index_bytes,
                "dbstat_available": dbstat_available,
            }
        )
        buckets = {
            name: {"terminal_task_count": 0, "event_rows": 0, "logical_bytes": 0, "estimated_bytes": 0}
            for name in BUCKETS
        }
        rows = connection.execute(
            "SELECT e.task_id, COUNT(*) AS event_rows, "
            "COALESCE(SUM(LENGTH(CAST(e.payload_json AS BLOB))), 0) AS logical_bytes, "
            "s.status, s.finished_time "
            "FROM task_events e LEFT JOIN task_snapshots s ON s.task_id=e.task_id "
            "GROUP BY e.task_id, s.status, s.finished_time"
        ).fetchall()
        terminal_values = {state.value for state in TERMINAL_TASK_STATES}
        unknown_rows = 0
        invalid_or_future_rows = 0
        for row in rows:
            event_rows = int(row["event_rows"] or 0)
            status = str(row["status"] or "").upper()
            finished = _timestamp(row["finished_time"])
            if status not in terminal_values or finished is None:
                unknown_rows += event_rows
                continue
            bucket = _bucket((now - finished).total_seconds())
            if bucket is None:
                invalid_or_future_rows += event_rows
                continue
            item = buckets[bucket]
            item["terminal_task_count"] += 1
            item["event_rows"] += event_rows
            item["logical_bytes"] += int(row["logical_bytes"] or 0)
        total_rows = max(1, int(result["task_event_rows"]))
        allocation_base = int(result["task_event_table_bytes"] or result["file_size_bytes"])
        for item in buckets.values():
            item["estimated_bytes"] = round(
                allocation_base * item["event_rows"] / total_rows
            )
        predicted = {
            "event_rows": sum(buckets[name]["event_rows"] for name in BUCKETS[2:]),
            "logical_bytes": sum(buckets[name]["logical_bytes"] for name in BUCKETS[2:]),
            "estimated_bytes": sum(buckets[name]["estimated_bytes"] for name in BUCKETS[2:]),
        }
        result.update(
            {
                "buckets": buckets,
                "unknown_or_non_terminal_event_rows": unknown_rows,
                "invalid_or_future_event_rows": invalid_or_future_rows,
                "predicted_at_7d": predicted,
            }
        )
    return result


def build_report(root: Path, *, now: datetime) -> dict[str, Any]:
    root = root.resolve()
    if root != DEFAULT_ROOT.resolve():
        raise ValueError(f"production profile is restricted to {DEFAULT_ROOT}")
    sites_root = root / "sites"
    sites: list[dict[str, Any]] = []
    if sites_root.is_dir():
        for site_dir in sorted(sites_root.iterdir(), key=lambda path: path.name.casefold()):
            database = site_dir / "db" / "tasks.db"
            if not site_dir.is_dir() or database.is_symlink() or not database.is_file():
                continue
            try:
                sites.append(_profile_database(database, site_name=site_dir.name, now=now))
            except sqlite3.Error as exc:
                sites.append({"site_name": site_dir.name, "path": str(database), "status": "UNREADABLE", "error": exc.__class__.__name__})
    totals = {
        "task_event_rows": sum(int(site.get("task_event_rows") or 0) for site in sites),
        "task_event_table_bytes": sum(int(site.get("task_event_table_bytes") or 0) for site in sites),
        "task_event_index_bytes": sum(int(site.get("task_event_index_bytes") or 0) for site in sites),
    }
    buckets = {
        name: {"terminal_task_count": 0, "event_rows": 0, "logical_bytes": 0, "estimated_bytes": 0}
        for name in BUCKETS
    }
    for site in sites:
        for name in BUCKETS:
            for key in buckets[name]:
                buckets[name][key] += int(site.get("buckets", {}).get(name, {}).get(key) or 0)
    return {
        "generated_at": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "data_root": str(root),
        "source_mode": "sqlite_immutable_read_only",
        "mutation": "NONE",
        "production_data_mutated": False,
        "sites": sites,
        "totals": totals,
        "buckets": buckets,
        "predicted_at_7d": {
            "event_rows": sum(buckets[name]["event_rows"] for name in BUCKETS[2:]),
            "logical_bytes": sum(buckets[name]["logical_bytes"] for name in BUCKETS[2:]),
            "estimated_bytes": sum(buckets[name]["estimated_bytes"] for name in BUCKETS[2:]),
        },
        "notes": [
            "Only existing sites/<site>/db/tasks.db files were opened with SQLite immutable read-only URI.",
            "estimated_bytes allocates task_events dbstat table pages by event-row share; when dbstat is unavailable it uses the database file size as a conservative physical allocation base. logical_bytes is payload_json bytes.",
            "No SQLite checkpoint, schema initialization, cleanup, DELETE, VACUUM or file write was performed.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = build_report(args.root, now=datetime.now(UTC))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "totals": report["totals"], "mutation": report["mutation"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
