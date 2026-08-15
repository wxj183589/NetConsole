"""Compare representative History Storage V1 and V2 query latency."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sqlite3
import time
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from netconsole.services.history_store import HistoryStore


_DEVELOPMENT_ROOT = Path("D:/study").resolve()


def _require_development_path(path: Path, *, name: str) -> Path:
    resolved = Path(path).resolve()
    if not resolved.is_relative_to(_DEVELOPMENT_ROOT):
        raise ValueError(f"{name} must remain under D:/study: {resolved}")
    return resolved


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(
        f"{path.resolve().as_uri()}?mode=ro&immutable=1", uri=True, timeout=30.0
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def _percentiles(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    if not ordered:
        return {"p50": 0.0, "p95": 0.0, "max": 0.0}

    def pick(percentile: float) -> float:
        return ordered[min(len(ordered) - 1, math.ceil(len(ordered) * percentile) - 1)]

    return {
        "p50": round(pick(0.50), 3),
        "p95": round(pick(0.95), 3),
        "max": round(ordered[-1], 3),
    }


def _representative(v1_root: Path) -> dict[str, str]:
    candidates: list[tuple[int, str, str]] = []
    ranges: dict[str, tuple[str, str]] = {}
    for shard in sorted(v1_root.glob("devices-????-??.db")):
        with closing(_connect(shard)) as connection:
            row = connection.execute(
                """
                SELECT kind, entity_key, COUNT(*) AS total
                FROM history_events
                GROUP BY kind, entity_key
                ORDER BY total DESC
                LIMIT 1
                """
            ).fetchone()
            if row is not None:
                candidates.append((int(row["total"]), str(row["kind"]), str(row["entity_key"])))
    if not candidates:
        raise ValueError("V1 history has no events")
    _count, kind, entity_key = max(candidates)
    for shard in sorted(v1_root.glob("devices-????-??.db")):
        with closing(_connect(shard)) as connection:
            row = connection.execute(
                "SELECT MIN(collected_at), MAX(collected_at) FROM history_events WHERE kind=?",
                (kind,),
            ).fetchone()
            if row is not None and row[0] is not None:
                ranges[shard.name] = (str(row[0]), str(row[1]))
    return {
        "kind": kind,
        "entity_key": entity_key,
        "collected_from": min(value[0] for value in ranges.values()),
        "collected_to": max(value[1] for value in ranges.values()),
    }


def _v1_rows(
    connection: sqlite3.Connection,
    *,
    kind: str,
    entity_key: str | None,
    collected_from: str | None,
    collected_to: str | None,
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    clauses = ["kind=?", "event_type='legacy'"]
    params: list[Any] = [kind]
    if entity_key is not None:
        clauses.append("entity_key=?")
        params.append(entity_key)
    if collected_from:
        clauses.append("collected_at>=?")
        params.append(collected_from)
    if collected_to:
        clauses.append("collected_at<=?")
        params.append(collected_to)
    params.extend((limit, offset))
    rows = connection.execute(
        "SELECT * FROM history_events WHERE "
        + " AND ".join(clauses)
        + " ORDER BY collected_at DESC, event_id DESC LIMIT ? OFFSET ?",
        params,
    ).fetchall()
    output: list[dict[str, Any]] = []
    for row in rows:
        payload = json.loads(str(row["payload_json"] or "{}"))
        output.append(
            {
                **payload,
                "event_id": str(row["event_id"]),
                "event_type": str(row["event_type"]),
                "collected_at": str(row["collected_at"]),
            }
        )
    return output


def _v2_rows(
    connection: sqlite3.Connection,
    *,
    kind: str,
    entity_key: str | None,
    collected_from: str | None,
    collected_to: str | None,
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    kind_row = connection.execute(
        "SELECT kind_id FROM history_kinds_v2 WHERE name=?", (kind,)
    ).fetchone()
    legacy_row = connection.execute(
        "SELECT event_type_id FROM history_event_types_v2 WHERE name='legacy'"
    ).fetchone()
    if kind_row is None or legacy_row is None:
        return []
    kind_id = int(kind_row[0])
    clauses = ["e.kind_id=?", "e.event_type_id=?"]
    params: list[Any] = [kind_id, int(legacy_row[0])]
    if entity_key is not None:
        entity_row = connection.execute(
            "SELECT entity_id FROM history_entities_v2 "
            "WHERE kind_id=? AND entity_key=?",
            (kind_id, entity_key),
        ).fetchone()
        if entity_row is None:
            return []
        clauses.append("e.entity_id=?")
        params.append(int(entity_row[0]))
    if collected_from:
        clauses.append("e.collected_at>=?")
        params.append(collected_from)
    if collected_to:
        clauses.append("e.collected_at<=?")
        params.append(collected_to)
    params.extend((limit, offset))
    index_name = (
        "idx_history_events_v2_entity_time"
        if entity_key is not None
        else "idx_history_events_v2_kind_time"
    )
    rows = connection.execute(
        """
        SELECT e.event_id, k.name AS kind, n.entity_key, t.name AS event_type,
               e.collected_at, e.payload_codec, e.payload, e.created_at,
               s.payload_schema_version, s.fields_json
        FROM history_events_v2 AS e INDEXED BY """
        + index_name
        + " "
        + """
        JOIN history_kinds_v2 AS k ON k.kind_id=e.kind_id
        JOIN history_entities_v2 AS n ON n.entity_id=e.entity_id
        JOIN history_event_types_v2 AS t ON t.event_type_id=e.event_type_id
        JOIN history_payload_schemas_v2 AS s
          ON s.payload_schema_id=e.payload_schema_id
        WHERE """
        + " AND ".join(clauses)
        + " ORDER BY e.collected_at DESC, e.event_id DESC LIMIT ? OFFSET ?",
        params,
    ).fetchall()
    return [HistoryStore._event_dict_v2(dict(row)) for row in rows]


def _query_plan(
    connection: sqlite3.Connection,
    *,
    version: int,
    kind: str,
    entity_key: str | None,
) -> list[str]:
    if version == 1:
        entity_clause = " AND entity_key=?" if entity_key is not None else ""
        params = (kind, entity_key) if entity_key is not None else (kind,)
        rows = connection.execute(
            f"""
            EXPLAIN QUERY PLAN
            SELECT * FROM history_events
            WHERE kind=?{entity_clause} AND event_type='legacy'
            ORDER BY collected_at DESC, event_id DESC LIMIT 100
            """,
            params,
        ).fetchall()
    else:
        kind_row = connection.execute(
            "SELECT kind_id FROM history_kinds_v2 WHERE name=?", (kind,)
        ).fetchone()
        legacy_row = connection.execute(
            "SELECT event_type_id FROM history_event_types_v2 WHERE name='legacy'"
        ).fetchone()
        if kind_row is None or legacy_row is None:
            return []
        kind_id = int(kind_row[0])
        clauses = ["e.kind_id=?", "e.event_type_id=?"]
        params: list[Any] = [kind_id, int(legacy_row[0])]
        if entity_key is not None:
            entity_row = connection.execute(
                "SELECT entity_id FROM history_entities_v2 "
                "WHERE kind_id=? AND entity_key=?",
                (kind_id, entity_key),
            ).fetchone()
            if entity_row is None:
                return []
            clauses.append("e.entity_id=?")
            params.append(int(entity_row[0]))
        index_name = (
            "idx_history_events_v2_entity_time"
            if entity_key is not None
            else "idx_history_events_v2_kind_time"
        )
        rows = connection.execute(
            """
            EXPLAIN QUERY PLAN
            SELECT e.event_id
            FROM history_events_v2 AS e INDEXED BY """
            + index_name
            + " "
            + """
            WHERE """
            + " AND ".join(clauses)
            + " "
            + """
            ORDER BY e.collected_at DESC, e.event_id DESC LIMIT 100
            """,
            params,
        ).fetchall()
    return [str(row[3]) for row in rows]


def _event_id_digest(rows: list[dict[str, Any]]) -> str:
    serialized = "\n".join(str(row["event_id"]) for row in rows).encode("ascii")
    return hashlib.sha256(serialized).hexdigest()


def _run_case(
    root: Path,
    query: Callable[..., list[dict[str, Any]]],
    *,
    iterations: int,
    params: dict[str, Any],
) -> dict[str, Any]:
    shards = sorted(root.glob("devices-????-??.db"), reverse=True)

    def once() -> list[dict[str, Any]]:
        combined: list[dict[str, Any]] = []
        requested = int(params["limit"]) + int(params["offset"])
        per_shard = {**params, "limit": requested, "offset": 0}
        for shard in shards:
            with closing(_connect(shard)) as connection:
                combined.extend(query(connection, **per_shard))
        unique = {str(row["event_id"]): row for row in combined}
        ordered = sorted(
            unique.values(),
            key=lambda row: (str(row.get("collected_at") or ""), str(row["event_id"])),
            reverse=True,
        )
        start = int(params["offset"])
        return ordered[start : start + int(params["limit"])]

    once()
    timings: list[float] = []
    rows: list[dict[str, Any]] = []
    for _ in range(iterations):
        started = time.perf_counter()
        rows = once()
        timings.append((time.perf_counter() - started) * 1000)
    return {
        "rows": len(rows),
        "event_id_digest": _event_id_digest(rows),
        "latency_ms": _percentiles(timings),
    }


def run_benchmark(
    *, v1_root: Path, v2_root: Path, output_dir: Path, iterations: int
) -> dict[str, Any]:
    representative = _representative(v1_root)
    cases = {
        "single_entity_recent_100": {
            "kind": representative["kind"],
            "entity_key": representative["entity_key"],
            "collected_from": None,
            "collected_to": None,
            "limit": 100,
            "offset": 0,
        },
        "single_entity_time_range": {
            "kind": representative["kind"],
            "entity_key": representative["entity_key"],
            "collected_from": representative["collected_from"],
            "collected_to": representative["collected_to"],
            "limit": 1000,
            "offset": 0,
        },
        "all_type_time_range": {
            "kind": representative["kind"],
            "entity_key": None,
            "collected_from": representative["collected_from"],
            "collected_to": representative["collected_to"],
            "limit": 1000,
            "offset": 0,
        },
        "cross_month_recent_200": {
            "kind": representative["kind"],
            "entity_key": None,
            "collected_from": None,
            "collected_to": None,
            "limit": 200,
            "offset": 0,
        },
        "pagination_offset_500": {
            "kind": representative["kind"],
            "entity_key": None,
            "collected_from": None,
            "collected_to": None,
            "limit": 100,
            "offset": 500,
        },
    }
    results: dict[str, Any] = {}
    for name, params in cases.items():
        v1_result = _run_case(
            v1_root, _v1_rows, iterations=iterations, params=params
        )
        v2_result = _run_case(
            v2_root, _v2_rows, iterations=iterations, params=params
        )
        results[name] = {
            "v1": v1_result,
            "v2": v2_result,
            "event_ids_match": (
                v1_result["rows"] == v2_result["rows"]
                and v1_result["event_id_digest"] == v2_result["event_id_digest"]
            ),
        }
    v1_shard = max(v1_root.glob("devices-????-??.db"), key=lambda path: path.stat().st_size)
    v2_shard = max(v2_root.glob("devices-????-??.db"), key=lambda path: path.stat().st_size)
    with closing(_connect(v1_shard)) as connection:
        v1_entity_plan = _query_plan(
            connection,
            version=1,
            kind=representative["kind"],
            entity_key=representative["entity_key"],
        )
        v1_kind_plan = _query_plan(
            connection,
            version=1,
            kind=representative["kind"],
            entity_key=None,
        )
    with closing(_connect(v2_shard)) as connection:
        v2_entity_plan = _query_plan(
            connection,
            version=2,
            kind=representative["kind"],
            entity_key=representative["entity_key"],
        )
        v2_kind_plan = _query_plan(
            connection,
            version=2,
            kind=representative["kind"],
            entity_key=None,
        )
    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "iterations": iterations,
        "representative": representative,
        "query_plans": {
            "v1_entity_time": v1_entity_plan,
            "v1_time": v1_kind_plan,
            "v2_entity_time": v2_entity_plan,
            "v2_kind_time": v2_kind_plan,
        },
        "cases": results,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "HISTORY_QUERY_BENCHMARK.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v1-history-root", type=Path, required=True)
    parser.add_argument("--v2-history-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=10)
    args = parser.parse_args(argv)
    report = run_benchmark(
        v1_root=_require_development_path(args.v1_history_root, name="V1 history root"),
        v2_root=_require_development_path(args.v2_history_root, name="V2 history root"),
        output_dir=_require_development_path(args.output_dir, name="benchmark output"),
        iterations=max(1, int(args.iterations)),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
