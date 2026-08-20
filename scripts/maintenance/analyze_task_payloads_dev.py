"""Read-only payload composition analysis for the NetConsole DEV COPY."""

from __future__ import annotations

import argparse
import heapq
import json
import math
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable


DEFAULT_ROOT = Path(r"D:\NetConsoleData-dev")
DEFAULT_OUTPUT = Path(r"D:\study\diagnostic\NetConsole\lifecycle-audit-dev-20260821")
REPORT_NAME = "TASK_PAYLOAD_ANALYSIS_REPORT.json"
PAYLOAD_COLUMNS = (
    ("task_events", "payload_json"),
    ("task_snapshots", "result_json"),
    ("task_results", "canonical_json"),
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _marker(root: Path) -> dict[str, Any]:
    marker_path = root / "runtime_mode.json"
    if not marker_path.is_file():
        raise RuntimeError(f"runtime marker missing: {marker_path}")
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    if marker.get("mode") != "development":
        raise RuntimeError(f"runtime mode is not development: {marker.get('mode')!r}")
    return marker


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def _tables(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }


def _percentile(values: list[int], fraction: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(len(ordered) * fraction) - 1))]


def _json_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _category_matches(raw: str, task_type: str) -> set[str]:
    text = f"{task_type}\n{raw}".lower()
    rules = {
        "command_output": (
            "command_output", "command output", "stdout", "stderr", "cli_output", "shell_output", "raw_output", "command_result", "command_results"
        ),
        "device_response": (
            "device_response", "raw_response", "response_text", "reply", "ssh_response", "telnet_response", "snmp_response", "device_reply"
        ),
        "ap_fit_data": (
            "fit_ap", "fit-ap", "capwap", "bssid", "radio", "ap_uuid", "ap_name", "ac_fit_ap", "trackside_ap"
        ),
        "lldp_data": (
            "lldp", "neighbor_mac", "neighbor_interface", "neighbor_device", "local_interface"
        ),
        "configuration_text": (
            "running-config", "startup-config", "current-configuration", "configuration", "config_text", "config_snapshot", "display config"
        ),
        "mesh_data": (
            "mesh_link", "mesh_detail", "mesh", "peer_mac", "channel_busy", "main_link", "radio_statistics"
        ),
        "mr_data": (
            "online_mr", "vehicle_mr", "mr_collect", "mr_id", "mr_name", "mesh.sqlite", "fping_1s", "iperf"
        ),
    }
    return {category for category, needles in rules.items() if any(needle in text for needle in needles)}


def _record_metadata(
    connection: sqlite3.Connection,
    table: str,
    column: str,
    site_id: str,
) -> Iterable[dict[str, Any]]:
    tables = _tables(connection)
    if table == "task_events":
        if "task_snapshots" in tables:
            query = (
                "SELECT e.task_id, e.event_time AS created_time, e.payload_json, "
                "s.created_time AS snapshot_created_time, s.task_type "
                "FROM task_events e LEFT JOIN task_snapshots s ON s.task_id=e.task_id"
            )
        else:
            query = "SELECT task_id, event_time AS created_time, payload_json, '' AS snapshot_created_time, '' AS task_type FROM task_events"
    elif table == "task_snapshots":
        query = "SELECT task_id, created_time, result_json, created_time AS snapshot_created_time, task_type FROM task_snapshots"
    else:
        if "task_snapshots" in tables:
            query = (
                "SELECT r.task_id, r.created_time, r.canonical_json, "
                "s.created_time AS snapshot_created_time, s.task_type "
                "FROM task_results r LEFT JOIN task_snapshots s ON s.task_id=r.task_id"
            )
        else:
            query = "SELECT task_id, created_time, canonical_json, created_time AS snapshot_created_time, '' AS task_type FROM task_results"
    for row in connection.execute(query):
        raw = _json_text(row["payload_json"] if table == "task_events" else row["result_json"] if table == "task_snapshots" else row["canonical_json"])
        yield {
            "site_id": site_id,
            "task_id": str(row["task_id"] or ""),
            "created_time": str(row["created_time"] or row["snapshot_created_time"] or ""),
            "task_type": str(row["task_type"] or ""),
            "raw": raw,
            "size_bytes": len(raw.encode("utf-8")),
            "table": table,
            "column": column,
        }


def _site_id(root: Path, database: Path) -> str:
    try:
        relative = database.relative_to(root / "sites")
        return relative.parts[0]
    except ValueError:
        return "archive_or_staging"


def _analyze_database(path: Path, root: Path) -> dict[str, Any]:
    site_id = _site_id(root, path)
    stats: dict[tuple[str, str], list[int]] = defaultdict(list)
    category_counts: Counter[str] = Counter()
    category_bytes: Counter[str] = Counter()
    category_task_types: dict[str, Counter[str]] = defaultdict(Counter)
    top: list[tuple[int, int, dict[str, Any]]] = []
    sequence = 0
    with closing(_connect(path)) as connection:
        tables = _tables(connection)
        for table, column in PAYLOAD_COLUMNS:
            if table not in tables:
                continue
            for record in _record_metadata(connection, table, column, site_id):
                sequence += 1
                size = int(record["size_bytes"])
                key = (table, column)
                stats[key].append(size)
                matches = _category_matches(record["raw"], record["task_type"])
                for category in matches:
                    category_counts[category] += 1
                    category_bytes[category] += size
                    if record["task_type"]:
                        category_task_types[category][record["task_type"]] += 1
                item = {
                    "database": str(path),
                    "site_id": site_id,
                    "task_id": record["task_id"],
                    "table": table,
                    "column": column,
                    "size_bytes": size,
                    "created_time": record["created_time"],
                    "task_type": record["task_type"],
                    "matched_categories": sorted(matches),
                    "classification_method": "case-insensitive keyword scan of task_type and JSON/text payload; no payload content copied",
                }
                token = (size, -sequence, item)
                if len(top) < 100:
                    heapq.heappush(top, token)
                elif token > top[0]:
                    heapq.heapreplace(top, token)
    return {
        "database": str(path),
        "site_id": site_id,
        "database_size_bytes": path.stat().st_size,
        "scope": "current_site" if site_id != "archive_or_staging" else "archive_or_staging",
        "stats": stats,
        "category_counts": category_counts,
        "category_bytes": category_bytes,
        "category_task_types": category_task_types,
        "top": top,
    }


def _write_report(root: Path, generated: str, output: Path) -> Path:
    databases = sorted(root.rglob("tasks.db"))
    per_database: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    aggregate_stats: dict[tuple[str, str], list[int]] = defaultdict(list)
    aggregate_categories: Counter[str] = Counter()
    aggregate_category_bytes: Counter[str] = Counter()
    aggregate_category_types: dict[str, Counter[str]] = defaultdict(Counter)
    current_size = 0
    current_count = 0
    top_records: list[tuple[int, int, dict[str, Any]]] = []
    sequence = 0
    for path in databases:
        try:
            result = _analyze_database(path, root)
        except (OSError, sqlite3.Error) as exc:
            errors.append({"database": str(path), "error": str(exc)})
            continue
        per_database.append({
            "database": result["database"],
            "site_id": result["site_id"],
            "database_size_bytes": result["database_size_bytes"],
            "scope": result["scope"],
        })
        if result["scope"] == "current_site":
            current_size += int(result["database_size_bytes"])
            current_count += 1
        if result["scope"] == "current_site":
            for key, values in result["stats"].items():
                aggregate_stats[key].extend(values)
            aggregate_categories.update(result["category_counts"])
            aggregate_category_bytes.update(result["category_bytes"])
            for category, values in result["category_task_types"].items():
                aggregate_category_types[category].update(values)
            for item in result["top"]:
                sequence += 1
                token = (item[0], -sequence, item[2])
                if len(top_records) < 100:
                    heapq.heappush(top_records, token)
                elif token > top_records[0]:
                    heapq.heapreplace(top_records, token)
    payload_statistics = []
    for (table, column), values in sorted(aggregate_stats.items()):
        payload_statistics.append({
            "table": table,
            "column": column,
            "record_count": len(values),
            "nonempty_count": sum(1 for value in values if value > 0),
            "total_bytes": sum(values),
            "average_size_bytes": round(sum(values) / len(values), 2) if values else 0,
            "max_size_bytes": max(values, default=0),
            "p50_size_bytes": _percentile(values, 0.50),
            "p95_size_bytes": _percentile(values, 0.95),
            "over_100kb_count": sum(1 for value in values if value > 100 * 1024),
            "over_1mb_count": sum(1 for value in values if value > 1024 * 1024),
        })
    categories = []
    category_names = (
        "command_output",
        "device_response",
        "ap_fit_data",
        "lldp_data",
        "configuration_text",
        "mesh_data",
        "mr_data",
    )
    for category in category_names:
        observed = aggregate_categories[category] > 0
        categories.append({
            "category": category,
            "status": "observed" if observed else "not_detected",
            "matched_record_count": aggregate_categories[category],
            "matched_payload_bytes": aggregate_category_bytes[category],
            "top_task_types": [
                {"task_type": task_type, "record_count": count}
                for task_type, count in aggregate_category_types[category].most_common(10)
            ],
            "evidence": "case-insensitive keyword scan of task_type and JSON/text payload; manual semantic confirmation still required",
        })
    top_records = sorted(top_records, key=lambda token: token[0], reverse=True)
    top_payloads = [token[2] for token in top_records]
    report = {
        "data_root": str(root),
        "runtime_mode": "development",
        "generated_time": generated,
        "sqlite_connection_mode": "mode=ro; PRAGMA query_only=ON",
        "write_operation_count": 0,
        "database_count": len(per_database),
        "database_errors": errors,
        "scope_definition": {
            "current_site": "D:\\NetConsoleData-dev\\sites\\*\\db\\tasks.db; this is the 420.86 MiB baseline",
            "archive_or_staging": "D:\\NetConsoleData-dev\\migrations\\**\\tasks.db; reported per database but excluded from current baseline",
        },
        "current_site_summary": {
            "database_count": current_count,
            "database_size_bytes": current_size,
            "database_size_mib": round(current_size / 1024 / 1024, 2),
        },
        "payload_statistics": payload_statistics,
        "content_classification": categories,
        "top_100_records": top_payloads,
        "classification_limitations": [
            "Category detection is a read-only heuristic over task_type and serialized JSON/text; it does not copy payload content into the report.",
            "A single record may match multiple categories because command output, device response, and parsed AP/LLDP data can coexist in one result.",
            "Empty or encoded payloads are counted by byte length but may not yield a category match.",
        ],
        "no_mutation": {
            "delete": False,
            "update": False,
            "insert": False,
            "drop": False,
            "alter": False,
            "vacuum": False,
            "reindex": False,
        },
        "databases": per_database,
    }
    output.mkdir(parents=True, exist_ok=True)
    report_path = output / REPORT_NAME
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    root = args.data_root.resolve()
    if root != DEFAULT_ROOT.resolve():
        raise RuntimeError(f"this analysis is restricted to {DEFAULT_ROOT}")
    marker = _marker(root)
    generated = _now()
    print(json.dumps({"data_root": str(root), "runtime_mode": marker["mode"], "generated_time": generated}, ensure_ascii=False))
    report_path = _write_report(root, generated, args.output_dir.resolve())
    print(json.dumps({"report": str(report_path), "WRITE_OPERATION_COUNT": 0}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
