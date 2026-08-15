"""Profile legacy device history and HistoryStore shards on isolated data."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sqlite3
import zlib
from collections import Counter
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from netconsole.services.history_store import LEGACY_HISTORY_TABLES


_DEVELOPMENT_ROOT = Path("D:/study").resolve()
_TIME_COLUMNS = ("collected_at", "created_at")
_V1_FIELDS = (
    "event_id",
    "kind",
    "entity_key",
    "event_type",
    "collected_at",
    "payload_json",
    "created_at",
)


def _require_development_path(path: Path, *, name: str) -> Path:
    resolved = Path(path).resolve()
    if not resolved.is_relative_to(_DEVELOPMENT_ROOT):
        raise ValueError(f"{name} must remain under D:/study: {resolved}")
    return resolved


def _connect_readonly(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(
        f"{Path(path).resolve().as_uri()}?mode=ro&immutable=1", uri=True, timeout=30.0
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA temp_store=MEMORY")
    return connection


def _write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _quote(identifier: str) -> str:
    return '"' + str(identifier).replace('"', '""') + '"'


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _percentiles(values: list[int]) -> dict[str, int]:
    ordered = sorted(values)
    if not ordered:
        return {"p50": 0, "p95": 0, "p99": 0, "max": 0}

    def pick(percentile: float) -> int:
        return ordered[min(len(ordered) - 1, math.ceil(len(ordered) * percentile) - 1)]

    return {
        "p50": pick(0.50),
        "p95": pick(0.95),
        "p99": pick(0.99),
        "max": ordered[-1],
    }


def _schema_objects(
    connection: sqlite3.Connection, table: str
) -> tuple[str, list[tuple[str, str]]]:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    if row is None or not row[0]:
        raise ValueError(f"missing table schema: {table}")
    indexes = [
        (str(item["name"]), str(item["sql"]))
        for item in connection.execute(
            """
            SELECT name, sql FROM sqlite_master
            WHERE type='index' AND tbl_name=? AND sql IS NOT NULL
            ORDER BY name
            """,
            (table,),
        ).fetchall()
    ]
    return str(row[0]), indexes


def _unlink_scratch(path: Path, scratch_root: Path) -> None:
    resolved = path.resolve(strict=False)
    if not resolved.is_relative_to(scratch_root.resolve()):
        raise ValueError(f"refusing to remove non-scratch path: {resolved}")
    if resolved.exists():
        resolved.unlink()
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(resolved) + suffix)
        if sidecar.exists():
            sidecar.unlink()


def _copy_table(
    *,
    source: Path,
    target: Path,
    table: str,
    table_sql: str,
    indexes: list[tuple[str, str]],
    page_size: int,
    scratch_root: Path,
    blank_payload: bool = False,
) -> dict[str, Any]:
    _unlink_scratch(target, scratch_root)
    source_uri = f"{source.resolve().as_uri()}?mode=ro&immutable=1"
    with closing(sqlite3.connect(target, uri=True, timeout=60.0)) as output:
        output.execute(f"PRAGMA page_size={max(512, int(page_size))}")
        output.execute("PRAGMA journal_mode=DELETE")
        output.execute("PRAGMA synchronous=OFF")
        output.execute("PRAGMA temp_store=MEMORY")
        output.execute(table_sql)
        output.execute("ATTACH DATABASE ? AS source_db", (source_uri,))
        if blank_payload:
            columns = [
                str(row[1])
                for row in output.execute(f"PRAGMA table_info({_quote(table)})").fetchall()
            ]
            select_values = ["''" if column == "payload_json" else _quote(column) for column in columns]
            output.execute(
                f"INSERT INTO {_quote(table)} ({', '.join(_quote(item) for item in columns)}) "
                f"SELECT {', '.join(select_values)} FROM source_db.{_quote(table)}"
            )
        else:
            output.execute(
                f"INSERT INTO {_quote(table)} SELECT * FROM source_db.{_quote(table)}"
            )
        output.commit()
        output.execute("DETACH DATABASE source_db")
        output.execute("VACUUM")
    table_bytes = target.stat().st_size
    index_profiles: list[dict[str, Any]] = []
    previous = table_bytes
    for index_name, index_sql in indexes:
        with closing(sqlite3.connect(target, timeout=60.0)) as output:
            output.execute("PRAGMA synchronous=OFF")
            output.execute("PRAGMA temp_store=MEMORY")
            output.execute(index_sql)
            output.commit()
            output.execute("VACUUM")
        current = target.stat().st_size
        index_profiles.append(
            {"index": index_name, "bytes": max(0, current - previous)}
        )
        previous = current
    return {
        "table_bytes": table_bytes,
        "explicit_index_bytes": max(0, previous - table_bytes),
        "total_bytes": previous,
        "indexes": index_profiles,
    }


def _build_combined_legacy(
    *, source: Path, target: Path, tables: list[str], page_size: int, scratch_root: Path
) -> int:
    _unlink_scratch(target, scratch_root)
    source_uri = f"{source.resolve().as_uri()}?mode=ro&immutable=1"
    with closing(_connect_readonly(source)) as source_connection:
        objects = {
            table: _schema_objects(source_connection, table)
            for table in tables
        }
    with closing(sqlite3.connect(target, uri=True, timeout=60.0)) as output:
        output.execute(f"PRAGMA page_size={max(512, int(page_size))}")
        output.execute("PRAGMA journal_mode=DELETE")
        output.execute("PRAGMA synchronous=OFF")
        output.execute("PRAGMA temp_store=MEMORY")
        for table in tables:
            output.execute(objects[table][0])
        output.execute("ATTACH DATABASE ? AS source_db", (source_uri,))
        for table in tables:
            output.execute(
                f"INSERT INTO {_quote(table)} SELECT * FROM source_db.{_quote(table)}"
            )
        output.commit()
        output.execute("DETACH DATABASE source_db")
        for table in tables:
            for _index_name, index_sql in objects[table][1]:
                output.execute(index_sql)
        output.commit()
        output.execute("VACUUM")
    return target.stat().st_size


def profile_legacy_history(
    source: Path, *, output_dir: Path, decompose: bool
) -> dict[str, Any]:
    scratch_root = output_dir / "_scratch"
    scratch_root.mkdir(parents=True, exist_ok=True)
    with closing(_connect_readonly(source)) as connection:
        page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
        page_count = int(connection.execute("PRAGMA page_count").fetchone()[0])
        freelist = int(connection.execute("PRAGMA freelist_count").fetchone()[0])
        quick_check = str(connection.execute("PRAGMA quick_check").fetchone()[0])
        schema_row = connection.execute(
            "SELECT value FROM schema_metadata WHERE key='schema_version'"
        ).fetchone()
        available = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        tables = sorted(table for table in LEGACY_HISTORY_TABLES if table in available)
        profiles: list[dict[str, Any]] = []
        object_schemas: dict[str, tuple[str, list[tuple[str, str]]]] = {}
        for table in tables:
            table_sql, indexes = _schema_objects(connection, table)
            object_schemas[table] = (table_sql, indexes)
            columns = [
                str(row[1])
                for row in connection.execute(f"PRAGMA table_info({_quote(table)})")
            ]
            time_column = next((item for item in _TIME_COLUMNS if item in columns), "")
            time_values = (None, None)
            if time_column:
                time_values = connection.execute(
                    f"SELECT MIN({_quote(time_column)}), MAX({_quote(time_column)}) "
                    f"FROM {_quote(table)}"
                ).fetchone()
            profiles.append(
                {
                    "table": table,
                    "rows": int(
                        connection.execute(
                            f"SELECT COUNT(*) FROM {_quote(table)}"
                        ).fetchone()[0]
                    ),
                    "min_timestamp": time_values[0],
                    "max_timestamp": time_values[1],
                    "explicit_indexes": [name for name, _sql in indexes],
                    "table_bytes": None,
                    "index_bytes": None,
                    "total_bytes": None,
                }
            )
    combined_bytes: int | None = None
    standalone_sum = 0
    if decompose:
        for profile in profiles:
            table = str(profile["table"])
            decomposition = _copy_table(
                source=source,
                target=scratch_root / f"legacy-{table}.db",
                table=table,
                table_sql=object_schemas[table][0],
                indexes=object_schemas[table][1],
                page_size=page_size,
                scratch_root=scratch_root,
            )
            profile.update(
                table_bytes=decomposition["table_bytes"],
                index_bytes=decomposition["explicit_index_bytes"],
                total_bytes=decomposition["total_bytes"],
                index_profile=decomposition["indexes"],
                bytes_per_row=round(
                    int(decomposition["total_bytes"]) / max(1, int(profile["rows"])), 2
                ),
            )
            standalone_sum += int(decomposition["total_bytes"])
            _unlink_scratch(scratch_root / f"legacy-{table}.db", scratch_root)
        combined_target = scratch_root / "legacy-history-combined.db"
        combined_bytes = _build_combined_legacy(
            source=source,
            target=combined_target,
            tables=tables,
            page_size=page_size,
            scratch_root=scratch_root,
        )
        _unlink_scratch(combined_target, scratch_root)
        for profile in profiles:
            profile["percentage"] = round(
                int(profile["total_bytes"] or 0) * 100 / max(1, standalone_sum), 4
            )
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source_path": str(source),
        "source_size_bytes": source.stat().st_size,
        "source_sha256": _sha256(source),
        "quick_check": quick_check,
        "schema_version": str(schema_row[0] if schema_row else ""),
        "page_size": page_size,
        "page_count": page_count,
        "freelist_count": freelist,
        "supported_table_count": len(profiles),
        "supported_rows": sum(int(item["rows"]) for item in profiles),
        "physical_method": (
            "controlled isolated reconstruction; implicit UNIQUE indexes are included in table_bytes"
            if decompose
            else "NOT_EXECUTED"
        ),
        "combined_physical_bytes": combined_bytes,
        "standalone_sum_bytes": standalone_sum if decompose else None,
        "tables": profiles,
        "destructive_production_operations": {
            "DELETE": "NO",
            "DROP": "NO",
            "VACUUM": "NO",
        },
    }


def _field_statistics(
    connection: sqlite3.Connection, *, table: str, rows: int
) -> tuple[dict[str, Any], dict[str, Any]]:
    expressions = ", ".join(
        f"COALESCE(SUM(length(CAST({_quote(field)} AS BLOB))), 0)"
        for field in _V1_FIELDS
    )
    totals = connection.execute(f"SELECT {expressions} FROM {_quote(table)}").fetchone()
    stride = max(1, rows // 10_000)
    samples: dict[str, list[int]] = {field: [] for field in _V1_FIELDS}
    payload_candidate = Counter()
    payload_schemas: set[tuple[str, ...]] = set()
    source_metadata_bytes = 0
    duplicate_time_bytes = 0
    sampled_payload_bytes = 0
    query = (
        "SELECT "
        + ", ".join(_quote(field) for field in _V1_FIELDS)
        + f" FROM {_quote(table)} WHERE rowid % ? = 0"
    )
    for row in connection.execute(query, (stride,)):
        for field in _V1_FIELDS:
            value = row[field]
            samples[field].append(
                len(value if isinstance(value, bytes) else str(value or "").encode("utf-8"))
            )
        payload_text = str(row["payload_json"] or "{}")
        payload = json.loads(payload_text)
        if not isinstance(payload, dict):
            payload = {"value": payload}
        sampled_payload_bytes += len(payload_text.encode("utf-8"))
        source_metadata_bytes += len(
            json.dumps(
                {
                    key: payload[key]
                    for key in ("legacy_source_table", "legacy_source_id")
                    if key in payload
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        duplicate_time_bytes += len(
            json.dumps(
                {key: payload[key] for key in ("collected_at",) if key in payload},
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        compact = {
            str(key): value
            for key, value in payload.items()
            if str(key)
            not in {"collected_at", "legacy_source_table", "legacy_source_id"}
        }
        fields = tuple(sorted(compact))
        payload_schemas.add(fields)
        encoded = json.dumps(
            [compact[field] for field in fields],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        compressed = zlib.compress(encoded, level=1)
        payload_candidate.update(
            raw=len(payload_text.encode("utf-8")),
            schema_array=len(encoded),
            zlib1=min(len(encoded), len(compressed)),
        )
    field_profiles = {
        field: {
            "total_bytes": int(totals[index] or 0),
            "avg_bytes": round(int(totals[index] or 0) / max(1, rows), 2),
            "sample_stride": stride,
            "sample_rows": len(samples[field]),
            **_percentiles(samples[field]),
        }
        for index, field in enumerate(_V1_FIELDS)
    }
    candidate = {
        "sample_rows": len(samples["payload_json"]),
        "distinct_payload_shapes": len(payload_schemas),
        "raw_payload_bytes": payload_candidate["raw"],
        "schema_array_bytes": payload_candidate["schema_array"],
        "zlib1_bytes": payload_candidate["zlib1"],
        "schema_array_ratio": round(
            payload_candidate["schema_array"] / max(1, payload_candidate["raw"]), 6
        ),
        "zlib1_ratio": round(
            payload_candidate["zlib1"] / max(1, payload_candidate["raw"]), 6
        ),
        "migration_metadata_sample_bytes": source_metadata_bytes,
        "duplicate_collected_at_sample_bytes": duplicate_time_bytes,
        "sampled_payload_bytes": sampled_payload_bytes,
    }
    return field_profiles, candidate


def profile_v1_history(
    history_root: Path, *, output_dir: Path, decompose: bool
) -> dict[str, Any]:
    scratch_root = output_dir / "_scratch"
    scratch_root.mkdir(parents=True, exist_ok=True)
    shards: list[dict[str, Any]] = []
    aggregate_candidate = Counter()
    all_indexes: Counter[str] = Counter()
    for shard_path in sorted(history_root.glob("devices-????-??.db")):
        with closing(_connect_readonly(shard_path)) as connection:
            if not connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='history_events'"
            ).fetchone():
                continue
            rows = int(connection.execute("SELECT COUNT(*) FROM history_events").fetchone()[0])
            page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
            page_count = int(connection.execute("PRAGMA page_count").fetchone()[0])
            freelist = int(connection.execute("PRAGMA freelist_count").fetchone()[0])
            quick_check = str(connection.execute("PRAGMA quick_check").fetchone()[0])
            table_sql, indexes = _schema_objects(connection, "history_events")
            fields, candidate = _field_statistics(
                connection, table="history_events", rows=rows
            )
        for key in ("raw_payload_bytes", "schema_array_bytes", "zlib1_bytes"):
            aggregate_candidate[key] += int(candidate[key])
        decomposition: dict[str, Any] = {}
        if decompose:
            target = scratch_root / f"v1-{shard_path.stem}.db"
            decomposition = _copy_table(
                source=shard_path,
                target=target,
                table="history_events",
                table_sql=table_sql,
                indexes=indexes,
                page_size=page_size,
                scratch_root=scratch_root,
            )
            _unlink_scratch(target, scratch_root)
            blank_target = scratch_root / f"v1-{shard_path.stem}-blank-payload.db"
            blank = _copy_table(
                source=shard_path,
                target=blank_target,
                table="history_events",
                table_sql=table_sql,
                indexes=[],
                page_size=page_size,
                scratch_root=scratch_root,
                blank_payload=True,
            )
            _unlink_scratch(blank_target, scratch_root)
            decomposition["payload_physical_bytes"] = max(
                0, int(decomposition["table_bytes"]) - int(blank["table_bytes"])
            )
            decomposition["envelope_and_primary_index_bytes"] = int(blank["table_bytes"])
            decomposition["rebuild_fragmentation_bytes"] = max(
                0, shard_path.stat().st_size - int(decomposition["total_bytes"])
            )
            for item in decomposition["indexes"]:
                all_indexes[str(item["index"])] += int(item["bytes"])
        shards.append(
            {
                "file": shard_path.name,
                "size_bytes": shard_path.stat().st_size,
                "page_size": page_size,
                "page_count": page_count,
                "freelist_count": freelist,
                "free_bytes": page_size * freelist,
                "rows": rows,
                "avg_bytes_per_event": round(shard_path.stat().st_size / max(1, rows), 2),
                "quick_check": quick_check,
                "fields": fields,
                "payload_candidate_sample": candidate,
                "physical_decomposition": decomposition or "NOT_EXECUTED",
            }
        )
    catalog_path = history_root / "catalog.db"
    catalog_bytes = catalog_path.stat().st_size if catalog_path.is_file() else 0
    actual_shard_bytes = sum(int(item["size_bytes"]) for item in shards)
    actual_total_bytes = actual_shard_bytes + catalog_bytes
    payload_physical = sum(
        int((item["physical_decomposition"] or {}).get("payload_physical_bytes", 0))
        for item in shards
        if isinstance(item["physical_decomposition"], dict)
    )
    envelope_physical = sum(
        int(
            (item["physical_decomposition"] or {}).get(
                "envelope_and_primary_index_bytes", 0
            )
        )
        for item in shards
        if isinstance(item["physical_decomposition"], dict)
    )
    index_physical = sum(all_indexes.values())
    fragmentation = sum(
        int((item["physical_decomposition"] or {}).get("rebuild_fragmentation_bytes", 0))
        for item in shards
        if isinstance(item["physical_decomposition"], dict)
    )
    components = {
        "payload": payload_physical,
        "envelope_and_primary_index": envelope_physical,
        "secondary_indexes": index_physical,
        "rebuild_fragmentation": fragmentation,
        "catalog": catalog_bytes,
    }
    for name, value in list(components.items()):
        components[name] = {
            "bytes": value,
            "percentage_of_actual_total": round(value * 100 / max(1, actual_total_bytes), 4),
            "bytes_per_event": round(
                value * 1.0 / max(1, sum(int(item["rows"]) for item in shards)), 2
            ),
        }
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "history_root": str(history_root),
        "catalog_bytes": catalog_bytes,
        "shard_bytes": actual_shard_bytes,
        "target_total_bytes": actual_total_bytes,
        "rows": sum(int(item["rows"]) for item in shards),
        "components": components,
        "index_profile": [
            {"index": name, "bytes": value}
            for name, value in sorted(all_indexes.items())
        ],
        "payload_candidate_sample": {
            **dict(aggregate_candidate),
            "schema_array_ratio": round(
                aggregate_candidate["schema_array_bytes"]
                / max(1, aggregate_candidate["raw_payload_bytes"]),
                6,
            ),
            "zlib1_ratio": round(
                aggregate_candidate["zlib1_bytes"]
                / max(1, aggregate_candidate["raw_payload_bytes"]),
                6,
            ),
        },
        "shards": shards,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", type=Path, required=True)
    parser.add_argument("--v1-history-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--decompose", action="store_true")
    args = parser.parse_args(argv)
    source = _require_development_path(args.source_db, name="source snapshot")
    history_root = _require_development_path(
        args.v1_history_root, name="V1 history root"
    )
    output_dir = _require_development_path(args.output_dir, name="diagnostics output")
    if not source.is_file():
        raise SystemExit(f"source snapshot is missing: {source}")
    if not history_root.is_dir():
        raise SystemExit(f"V1 history root is missing: {history_root}")
    output_dir.mkdir(parents=True, exist_ok=True)
    legacy = profile_legacy_history(
        source, output_dir=output_dir, decompose=args.decompose
    )
    v1 = profile_v1_history(
        history_root, output_dir=output_dir, decompose=args.decompose
    )
    _write_json(output_dir / "LEGACY_HISTORY_PHYSICAL_BASELINE.json", legacy)
    _write_json(output_dir / "HISTORY_STORAGE_PROFILE.json", v1)
    summary = {
        "legacy_physical_bytes": legacy["combined_physical_bytes"],
        "v1_target_bytes": v1["target_total_bytes"],
        "v1_amplification": round(
            int(v1["target_total_bytes"])
            / max(1, int(legacy["combined_physical_bytes"] or 0)),
            6,
        )
        if legacy["combined_physical_bytes"]
        else None,
        "outputs": [
            str(output_dir / "LEGACY_HISTORY_PHYSICAL_BASELINE.json"),
            str(output_dir / "HISTORY_STORAGE_PROFILE.json"),
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
