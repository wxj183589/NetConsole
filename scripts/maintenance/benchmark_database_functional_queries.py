"""Benchmark real before/after storage queries without mutating either evidence tree."""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
import os
import sqlite3
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import closing
from enum import Enum
from pathlib import Path
from typing import Any

from netconsole.repositories.history_store import HistoryStore
from netconsole.repositories.task_repository import TaskRepository
from scripts.maintenance.validate_database_functional_compatibility import (
    DEFAULT_EXCLUDED_TASK_IDS,
    _ReadonlyTaskRepository,
)


DEFAULT_DEVELOPMENT_ROOT = Path("D:/study")
REQUIRED_CASES = (
    "current_device_query",
    "fit_ap_query",
    "lldp_query",
    "history_range_query",
    "cross_shard_history_query",
    "task_center_list",
    "task_detail",
    "mr_mesh_history",
    "ground_history",
)
LEGACY_HISTORY_SPECS = {
    "device_facts_history": ("device_fact", ("device_uuid",)),
    "device_interfaces_history": ("device_interface", ("device_uuid", "interface_name")),
    "device_optical_modules_history": ("device_optical", ("device_uuid", "interface_name")),
    "device_lldp_neighbors_history": ("device_lldp", ("device_uuid", "local_interface")),
    "ac_fit_ap_resource_history": ("fit_ap_resource", ("ac_device_uuid", "ap_uuid")),
    "ac_fit_ap_radio_history": ("fit_ap_radio", ("ap_uuid", "rid")),
    "ac_fit_ap_lldp_history": ("fit_ap_lldp", ("ap_uuid",)),
    "ac_fit_ap_optical_history": ("fit_ap_optical", ("ap_uuid",)),
}


class PerformanceEvidenceError(ValueError):
    """Raised when a benchmark input or semantic comparison is invalid."""


def benchmark_database_functional_queries(
    *,
    before_devices: Path,
    after_devices: Path,
    before_tasks: Path,
    after_tasks: Path,
    after_history_root: Path,
    site_package_report: Path,
    output_path: Path,
    iterations: int = 20,
    repo_root: Path | None = None,
    development_root: Path = DEFAULT_DEVELOPMENT_ROOT,
) -> dict[str, Any]:
    if iterations < 10:
        raise PerformanceEvidenceError("performance comparison requires at least 10 iterations")
    development = development_root.resolve(strict=True)
    root = (repo_root or Path(__file__).resolve().parents[2]).resolve(strict=True)
    before_devices_path = _input_file(before_devices, development)
    after_devices_path = _input_file(after_devices, development)
    before_tasks_path = _input_file(before_tasks, development)
    after_tasks_path = _input_file(after_tasks, development)
    history_root = _input_directory(after_history_root, development)
    package_path = _input_file(site_package_report, development)
    output = _output_file(output_path, development)
    if output.exists():
        raise PerformanceEvidenceError(f"refusing to overwrite performance evidence: {output}")

    package = _load_object(package_path)
    if package.get("format") != "netconsole-integrated-site-package-validation-v1" or package.get("status") != "PASS":
        raise PerformanceEvidenceError("Site Package report must be PASS before performance comparison")
    source_site, imported_site = _package_sites(package, development)

    cases: list[dict[str, Any]] = []
    for case_id, table, order_columns in (
        ("current_device_query", "devices", ("name", "id")),
        ("fit_ap_query", "ac_fit_ap_resources", ("collected_at", "id")),
        ("lldp_query", "device_lldp_neighbors", ("collected_at", "id")),
    ):
        cases.append(
            _benchmark_pair(
                case_id,
                lambda database=before_devices_path, table=table, order=order_columns: _table_rows(database, table, order),
                lambda database=after_devices_path, table=table, order=order_columns: _table_rows(database, table, order),
                iterations=iterations,
            )
        )

    history_case = _history_case(before_devices_path)
    cases.append(
        _benchmark_pair(
            "history_range_query",
            lambda: _legacy_history_rows(before_devices_path, history_case, entity_only=True),
            lambda: _history_store_rows(history_root, history_case, entity_only=True),
            iterations=iterations,
        )
    )
    cases.append(
        _benchmark_pair(
            "cross_shard_history_query",
            lambda: _legacy_history_rows(before_devices_path, history_case, entity_only=False),
            lambda: _history_store_rows(history_root, history_case, entity_only=False),
            iterations=iterations,
        )
    )

    before_repository = _ReadonlyTaskRepository(
        before_tasks_path, history_root=_history_root_for_tasks(before_tasks_path)
    )
    after_repository = _ReadonlyTaskRepository(
        after_tasks_path, history_root=_history_root_for_tasks(after_tasks_path)
    )
    cases.append(
        _benchmark_pair(
            "task_center_list",
            lambda: _task_list_semantic(before_repository),
            lambda: _task_list_semantic(after_repository),
            iterations=iterations,
        )
    )
    task_id = _representative_task_id(before_repository)
    cases.append(
        _benchmark_pair(
            "task_detail",
            lambda: _task_detail_semantic(before_repository, task_id),
            lambda: _task_detail_semantic(after_repository, task_id),
            iterations=iterations,
        )
    )

    source_mesh = _largest_relative_database(
        source_site, "files/rail_transit/mr_raw_mesh/*/mesh.sqlite"
    )
    imported_mesh = imported_site / source_mesh.relative_to(source_site)
    cases.append(
        _benchmark_pair(
            "mr_mesh_history",
            lambda: _table_rows(source_mesh, "mesh_links", ("sample_time", "id")),
            lambda: _table_rows(imported_mesh, "mesh_links", ("sample_time", "id")),
            iterations=iterations,
        )
    )
    source_ground = source_site / "files/rail_transit/ground_unattended/index.sqlite"
    imported_ground = imported_site / source_ground.relative_to(source_site)
    cases.append(
        _benchmark_pair(
            "ground_history",
            lambda: _table_rows(source_ground, "ground_unattended_events", ("event_time", "id")),
            lambda: _table_rows(imported_ground, "ground_unattended_events", ("event_time", "id")),
            iterations=iterations,
        )
    )

    failed = [item["id"] for item in cases if item["status"] != "PASS"]
    report = {
        "format": "netconsole-database-performance-comparison-v1",
        "status": "PASS" if not failed else "FAIL",
        "git_head": _git_head(root),
        "iterations": iterations,
        "threshold_policy": {
            "p95": "after <= max(before * 3, before + 25 ms)",
            "max": "after <= max(before * 4, before + 50 ms)",
            "semantic_result": "count and canonical SHA-256 must match",
        },
        "cases": cases,
        "failed_cases": failed,
        "source_evidence": {
            "before_devices": _file_evidence(before_devices_path),
            "after_devices": _file_evidence(after_devices_path),
            "before_tasks": _file_evidence(before_tasks_path),
            "after_tasks": _file_evidence(after_tasks_path),
            "after_history_root": str(history_root),
            "site_package": _file_evidence(package_path),
        },
        "safety": {
            "sqlite_mode": "mode=ro&immutable=1",
            "query_only": True,
            "production_mutations": 0,
            "output_below_development_root": True,
        },
    }
    _atomic_json(output, report)
    return report


def _benchmark_pair(
    case_id: str,
    before_query: Callable[[], Any],
    after_query: Callable[[], Any],
    *,
    iterations: int,
) -> dict[str, Any]:
    before = _measure(before_query, iterations=iterations)
    after = _measure(after_query, iterations=iterations)
    semantic_match = (
        before["result_count"] == after["result_count"]
        and before["result_sha256"] == after["result_sha256"]
    )
    p95_limit = max(before["latency_ms"]["p95"] * 3.0, before["latency_ms"]["p95"] + 25.0)
    max_limit = max(before["latency_ms"]["max"] * 4.0, before["latency_ms"]["max"] + 50.0)
    performance_ok = (
        after["latency_ms"]["p95"] <= p95_limit
        and after["latency_ms"]["max"] <= max_limit
    )
    return {
        "id": case_id,
        "status": "PASS" if semantic_match and performance_ok else "FAIL",
        "before": before,
        "after": after,
        "semantic_match": semantic_match,
        "performance_within_threshold": performance_ok,
        "limits_ms": {"p95": round(p95_limit, 3), "max": round(max_limit, 3)},
    }


def _measure(query: Callable[[], Any], *, iterations: int) -> dict[str, Any]:
    query()
    timings: list[float] = []
    result: Any = None
    for _ in range(iterations):
        started = time.perf_counter()
        result = query()
        timings.append((time.perf_counter() - started) * 1000.0)
    normalized = _json_value(result)
    count = len(normalized) if isinstance(normalized, list) else (0 if normalized is None else 1)
    return {
        "result_count": count,
        "result_sha256": _hash_json(normalized),
        "latency_ms": _percentiles(timings),
    }


def _table_rows(database: Path, table: str, preferred_order: Sequence[str]) -> list[dict[str, Any]]:
    with closing(_connect(database)) as connection:
        tables = {
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")
        }
        if table not in tables:
            raise PerformanceEvidenceError(f"required table is missing: {database}:{table}")
        columns = [str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")')]
        order = [column for column in preferred_order if column in columns]
        order_sql = ", ".join(f'"{column}" DESC' for column in order)
        sql = f'SELECT * FROM "{table}"'
        if order_sql:
            sql += f" ORDER BY {order_sql}"
        sql += " LIMIT 100 OFFSET 0"
        return [dict(row) for row in connection.execute(sql)]


def _history_case(database: Path) -> dict[str, Any]:
    candidates: list[tuple[int, str, str, tuple[str, ...]]] = []
    with closing(_connect(database)) as connection:
        tables = {str(row[0]) for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table, (kind, entity_fields) in LEGACY_HISTORY_SPECS.items():
            if table not in tables:
                continue
            count = int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            if count:
                candidates.append((count, table, kind, entity_fields))
        if not candidates:
            raise PerformanceEvidenceError("before devices database has no supported legacy history")
        _count, table, kind, entity_fields = max(candidates)
        valid = " AND ".join(
            ["collected_at IS NOT NULL", "TRIM(collected_at)<>''"]
            + [f'"{field}" IS NOT NULL AND TRIM(CAST("{field}" AS TEXT))<>\'\'' for field in entity_fields]
        )
        fields = ", ".join(f'"{field}"' for field in entity_fields)
        row = connection.execute(
            f'SELECT {fields}, MIN(collected_at), MAX(collected_at) FROM "{table}" WHERE {valid} GROUP BY {fields} ORDER BY COUNT(*) DESC LIMIT 1'
        ).fetchone()
        if row is None:
            raise PerformanceEvidenceError(f"legacy history has no valid entity: {table}")
        entity_values = [str(row[index]) for index in range(len(entity_fields))]
        return {
            "table": table,
            "kind": kind,
            "entity_fields": list(entity_fields),
            "entity_values": entity_values,
            "entity_key": ":".join(entity_values),
            "collected_from": str(row[len(entity_fields)]),
            "collected_to": str(row[len(entity_fields) + 1]),
        }


def _legacy_history_rows(
    database: Path, case: Mapping[str, Any], *, entity_only: bool
) -> list[dict[str, Any]]:
    clauses = ["collected_at IS NOT NULL", "TRIM(collected_at)<>''"]
    params: list[Any] = []
    for field in case["entity_fields"]:
        clauses.append(f'"{field}" IS NOT NULL AND TRIM(CAST("{field}" AS TEXT))<>\'\'')
    if entity_only:
        for field, value in zip(case["entity_fields"], case["entity_values"], strict=True):
            clauses.append(f'CAST("{field}" AS TEXT)=?')
            params.append(value)
        clauses.extend(["collected_at>=?", "collected_at<=?"])
        params.extend([case["collected_from"], case["collected_to"]])
    limit, offset = (100, 0) if entity_only else (500, 100)
    params.extend([limit, offset])
    with closing(_connect(database)) as connection:
        rows = connection.execute(
            f'SELECT id,collected_at FROM "{case["table"]}" WHERE '
            + " AND ".join(clauses)
            + " ORDER BY collected_at DESC,id DESC LIMIT ? OFFSET ?",
            params,
        ).fetchall()
    return [
        {
            # Compare the durable source identity across legacy and V2
            # layouts; the physical event-id encoding is an implementation
            # detail and legitimately changes during migration.
            "event_id": f'{case["table"]}|{int(row["id"])}',
            "source_table": str(case["table"]),
            "source_id": int(row["id"]),
            "collected_at": str(row["collected_at"]),
        }
        for row in rows
    ]


def _history_store_rows(
    root: Path, case: Mapping[str, Any], *, entity_only: bool
) -> list[dict[str, Any]]:
    combined: dict[str, dict[str, Any]] = {}
    requested = 100 if entity_only else 600
    for shard in sorted(root.glob("devices-*.db"), reverse=True):
        with closing(_connect(shard)) as connection:
            tables = {
                str(row[0])
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if "history_events_v2" in tables:
                rows = _v2_history_rows(connection, case, entity_only=entity_only, limit=requested)
            elif "history_events" in tables:
                rows = _v1_history_rows(connection, case, entity_only=entity_only, limit=requested)
            else:
                continue
            combined.update({str(row["event_id"]): row for row in rows})
    ordered = sorted(
        combined.values(),
        key=lambda row: (
            row["collected_at"],
            int(row["source_id"])
            if row.get("source_id") is not None
            else -1,
            row["event_id"],
        ),
        reverse=True,
    )
    return ordered[:100] if entity_only else ordered[100:600]


def _v1_history_rows(
    connection: sqlite3.Connection,
    case: Mapping[str, Any],
    *,
    entity_only: bool,
    limit: int,
) -> list[dict[str, Any]]:
    clauses = ["kind=?", "event_type='legacy'"]
    params: list[Any] = [case["kind"]]
    if entity_only:
        clauses.extend(["entity_key=?", "collected_at>=?", "collected_at<=?"])
        params.extend([case["entity_key"], case["collected_from"], case["collected_to"]])
    params.append(limit)
    rows = connection.execute(
        "SELECT event_id,collected_at FROM history_events WHERE "
        + " AND ".join(clauses)
        + " ORDER BY collected_at DESC,event_id DESC LIMIT ?",
        params,
    ).fetchall()
    return [
        {
            "event_id": HistoryStore._event_id_text(row["event_id"]),
            "collected_at": str(row["collected_at"]),
        }
        for row in rows
    ]


def _v2_history_rows(
    connection: sqlite3.Connection,
    case: Mapping[str, Any],
    *,
    entity_only: bool,
    limit: int,
) -> list[dict[str, Any]]:
    kind = connection.execute(
        "SELECT kind_id FROM history_kinds_v2 WHERE name=?", (case["kind"],)
    ).fetchone()
    event_type = connection.execute(
        "SELECT event_type_id FROM history_event_types_v2 WHERE name='legacy'"
    ).fetchone()
    if kind is None or event_type is None:
        return []
    clauses = ["e.kind_id=?", "e.event_type_id=?"]
    params: list[Any] = [int(kind[0]), int(event_type[0])]
    if entity_only:
        entity = connection.execute(
            "SELECT entity_id FROM history_entities_v2 WHERE kind_id=? AND entity_key=?",
            (int(kind[0]), case["entity_key"]),
        ).fetchone()
        if entity is None:
            return []
        clauses.extend(["e.entity_id=?", "e.collected_at>=?", "e.collected_at<=?"])
        params.extend([int(entity[0]), case["collected_from"], case["collected_to"]])
    params.append(limit)
    has_provenance = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='history_event_provenance_v2'"
    ).fetchone() is not None
    index_name = (
        "idx_history_events_v2_entity_time"
        if entity_only
        else "idx_history_events_v2_kind_time"
    )
    if has_provenance:
        select = (
            "SELECT e.event_id,e.collected_at,p.source_table,p.source_id "
            "FROM history_events_v2 AS e INDEXED BY "
            + index_name
            + " LEFT JOIN history_event_provenance_v2 AS p "
            "ON p.event_id=e.event_id WHERE "
        )
    else:
        select = (
            "SELECT e.event_id,e.collected_at,NULL AS source_table,"
            "NULL AS source_id FROM history_events_v2 AS e INDEXED BY "
            + index_name
            + " WHERE "
        )
    rows = connection.execute(
        select
        + " AND ".join(clauses)
        + (
            " ORDER BY e.collected_at DESC,p.source_id DESC,e.event_id DESC LIMIT ?"
            if has_provenance
            else " ORDER BY e.collected_at DESC,e.event_id DESC LIMIT ?"
        ),
        params,
    ).fetchall()
    return [
        {
            "event_id": (
                f'{row["source_table"]}|{int(row["source_id"])}'
                if row["source_table"] is not None and row["source_id"] is not None
                else HistoryStore._event_id_text(row["event_id"])
            ),
            "source_table": (
                str(row["source_table"])
                if row["source_table"] is not None
                else ""
            ),
            "source_id": (
                int(row["source_id"])
                if row["source_id"] is not None
                else None
            ),
            "collected_at": str(row["collected_at"]),
        }
        for row in rows
    ]


def _task_list(repository: TaskRepository) -> list[Any]:
    return [
        task
        for task in repository.list_filtered(
            include_dismissed=True,
            limit=100 + len(DEFAULT_EXCLUDED_TASK_IDS),
            offset=0,
        )
        if str(task.task_id) not in DEFAULT_EXCLUDED_TASK_IDS
    ][:100]


def _task_list_semantic(repository: TaskRepository) -> list[dict[str, Any]]:
    """Compare task business fields, excluding result-storage metadata."""

    return [_semantic_snapshot(task) for task in _task_list(repository)]


def _representative_task_id(repository: TaskRepository) -> str:
    tasks = _task_list(repository)
    if not tasks:
        raise PerformanceEvidenceError("tasks database has no task for detail benchmark")
    return str(tasks[0].task_id)


def _task_detail(repository: TaskRepository, task_id: str) -> dict[str, Any]:
    snapshot = repository.get(task_id)
    if snapshot is None:
        raise PerformanceEvidenceError(f"task detail is missing: {task_id}")
    return {
        "snapshot": snapshot,
        "events": repository.list_events(task_id, limit=1000),
    }


def _task_detail_semantic(repository: TaskRepository, task_id: str) -> dict[str, Any]:
    """Compare user-visible task data, not the result-reference implementation."""

    detail = _task_detail(repository, task_id)
    events: list[dict[str, Any]] = []
    for event in detail.get("events", []):
        normalized = dict(event)
        payload = dict(normalized.get("payload") or {})
        for key in ("result_id", "result_hash", "result_summary"):
            payload.pop(key, None)
        normalized["payload"] = payload
        events.append(normalized)
    snapshot = detail.get("snapshot", detail)
    return {"snapshot": _semantic_snapshot(snapshot), "events": events}


def _semantic_snapshot(snapshot: Any) -> dict[str, Any]:
    normalized = _json_value(snapshot)
    if not isinstance(normalized, dict):
        raise PerformanceEvidenceError("task snapshot normalization produced a non-object")
    for key in ("result_id", "result_hash", "result_summary"):
        normalized.pop(key, None)
    return normalized


def _history_root_for_tasks(database: Path) -> Path:
    candidate = database.parent / "history"
    return candidate if candidate.is_dir() else database.parent / ".missing-history"


def _package_sites(report: Mapping[str, Any], development: Path) -> tuple[Path, Path]:
    site_name = str(report.get("scope", {}).get("physical_directory") or "")
    if not site_name or Path(site_name).name != site_name:
        raise PerformanceEvidenceError("Site Package physical directory is invalid")
    source_root = _input_directory(Path(str(report.get("source", {}).get("data_root") or "")), development)
    imported_root = _input_directory(Path(str(report.get("imported", {}).get("data_root") or "")), development)
    source_site = _input_directory(source_root / "sites" / site_name, development)
    imported_site = _input_directory(imported_root / "sites" / site_name, development)
    return source_site, imported_site


def _largest_relative_database(site_root: Path, pattern: str) -> Path:
    candidates = [path for path in site_root.glob(pattern) if path.is_file()]
    if not candidates:
        raise PerformanceEvidenceError(f"required Site Package database is missing: {pattern}")
    return max(candidates, key=lambda path: (path.stat().st_size, path.as_posix()))


def _connect(path: Path) -> sqlite3.Connection:
    if not path.is_file() or path.stat().st_size <= 0:
        raise PerformanceEvidenceError(f"SQLite evidence is missing: {path}")
    connection = sqlite3.connect(
        f"{path.resolve().as_uri()}?mode=ro&immutable=1", uri=True, timeout=30.0
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA temp_store=MEMORY")
    return connection


def _percentiles(values: Sequence[float]) -> dict[str, float]:
    ordered = sorted(values)
    if not ordered:
        return {"p50": 0.0, "p95": 0.0, "max": 0.0}

    def pick(fraction: float) -> float:
        return ordered[min(len(ordered) - 1, math.ceil(len(ordered) * fraction) - 1)]

    return {
        "p50": round(pick(0.50), 3),
        "p95": round(pick(0.95), 3),
        "max": round(ordered[-1], 3),
    }


def _json_value(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _json_value(dataclasses.asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, bytes):
        return {"bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()}
    return value


def _hash_json(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PerformanceEvidenceError(f"JSON evidence must be an object: {path}")
    return value


def _file_evidence(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def _input_file(path: Path, development: Path) -> Path:
    candidate = path.resolve(strict=True)
    if not candidate.is_relative_to(development) or not candidate.is_file():
        raise PerformanceEvidenceError(f"input file must remain below D:/study: {candidate}")
    return candidate


def _input_directory(path: Path, development: Path) -> Path:
    candidate = path.resolve(strict=True)
    if not candidate.is_relative_to(development) or not candidate.is_dir():
        raise PerformanceEvidenceError(f"input directory must remain below D:/study: {candidate}")
    return candidate


def _output_file(path: Path, development: Path) -> Path:
    candidate = path.resolve()
    if candidate == development or not candidate.is_relative_to(development):
        raise PerformanceEvidenceError("output must remain in a child below D:/study")
    return candidate


def _git_head(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "--verify", "HEAD"],
        check=False,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        text=True,
    )
    head = result.stdout.strip().casefold()
    if result.returncode or len(head) != 40:
        raise PerformanceEvidenceError("cannot resolve Git HEAD")
    return head


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(
                (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
            )
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
        temporary.unlink()
    finally:
        temporary.unlink(missing_ok=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before-devices", type=Path, required=True)
    parser.add_argument("--after-devices", type=Path, required=True)
    parser.add_argument("--before-tasks", type=Path, required=True)
    parser.add_argument("--after-tasks", type=Path, required=True)
    parser.add_argument("--after-history-root", type=Path, required=True)
    parser.add_argument("--site-package-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--development-root", type=Path, default=DEFAULT_DEVELOPMENT_ROOT)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = benchmark_database_functional_queries(
        before_devices=args.before_devices,
        after_devices=args.after_devices,
        before_tasks=args.before_tasks,
        after_tasks=args.after_tasks,
        after_history_root=args.after_history_root,
        site_package_report=args.site_package_report,
        output_path=args.output,
        iterations=args.iterations,
        repo_root=args.repo_root,
        development_root=args.development_root,
    )
    print(json.dumps({"status": report["status"], "output": str(args.output)}, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
