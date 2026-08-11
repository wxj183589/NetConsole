from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import statistics
import time
import tracemalloc
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from netconsole.core.paths import PathResolver
from netconsole.repositories.mesh_mr_repository import MeshMrRepository, SCHEMA_VERSION
from netconsole.services.mesh_catalog_index_service import MeshCatalogIndexService
from netconsole.services.mesh_storage_service import MeshStorageService
from netconsole.services.rail_transit.mesh_analysis_query_service import (
    MeshAnalysisQueryService,
)


class CountingQueryService(MeshAnalysisQueryService):
    def __init__(self, paths: PathResolver) -> None:
        super().__init__(paths, schedule_catalog_index=False)
        self.database_opens = 0
        self.detail_database_opens = 0
        self.sql_statements = 0

    def _connect_readonly(self, path: Path) -> sqlite3.Connection:
        self.database_opens += 1
        if path.name.endswith(".mesh.sqlite"):
            self.detail_database_opens += 1
        connection = super()._connect_readonly(path)
        connection.set_trace_callback(self._count_sql)
        return connection

    def _count_sql(self, _statement: str) -> None:
        self.sql_statements += 1


def _insert_sources(database: Path, *, mr_id: str, detail: Path, count: int) -> None:
    rows = [
        (
            mr_id,
            f"source-{index}.log",
            f"source-{index}.log",
            str(detail),
            f"source-{index}.log",
            f"source-{index}.log",
            f"sha-{mr_id}-{index}",
            1024,
            f"2026-07-30 10:{index % 60:02d}:00.000",
            SCHEMA_VERSION,
            "success",
            f"2026-07-30 10:{index % 60:02d}:00.000",
            f"2026-07-30 10:{index % 60:02d}:59.000",
            index,
        )
        for index in range(1, count + 1)
    ]
    with sqlite3.connect(database) as connection:
        connection.executemany(
            """
            INSERT INTO source_files (
                mr_id, original_path, archived_path, parsed_db_path,
                original_filename, archived_filename, sha256, file_size,
                imported_at, parser_version, parse_status, first_sample_time,
                last_sample_time, source_file_order
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )


def _fixture(root: Path, profiles: int, sources: int) -> PathResolver:
    os.environ["NETCONSOLE_RUNTIME_MODE"] = "test"
    os.environ["NETCONSOLE_DATA_ROOT"] = str(root)
    paths = PathResolver(app_root=Path(__file__).resolve().parents[2], data_root=root)
    paths.site_dir("demo").mkdir(parents=True, exist_ok=True)
    storage = MeshStorageService("demo", paths)
    quotient, remainder = divmod(sources, profiles)
    for index in range(profiles):
        profile = storage.create_mr_profile(
            f"列车{index + 1:02d}-MR-{'CT' if index % 2 == 0 else 'CW'}"
        )
        detail = (
            paths.mesh_mr_parsed_dir("demo", profile.safe_folder_name)
            / "shared.mesh.sqlite"
        )
        MeshMrRepository(detail)
        count = quotient + int(index < remainder)
        _insert_sources(
            paths.mesh_mr_db_path("demo", profile.safe_folder_name),
            mr_id=profile.mr_id,
            detail=detail,
            count=count,
        )
    return paths


def _measure(service: CountingQueryService, legacy: bool) -> dict[str, object]:
    tracemalloc.start()
    started = time.perf_counter()
    if legacy:
        contexts = service._session_rows("demo")
        for context in contexts:
            service._stats(context)
        for context in contexts:
            service._session_dto(context)
        total = len(contexts)
    else:
        summary = service.get_summary("demo")
        page = service.list_analysis_sessions("demo", page=1, page_size=50)
        total = summary.session_count
        assert page.total == total
    elapsed = time.perf_counter() - started
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {
        "elapsed_seconds": round(elapsed, 4),
        "session_count": total,
        "database_opens": service.database_opens,
        "detail_database_opens": service.detail_database_opens,
        "sql_statements": service.sql_statements,
        "peak_memory_mib": round(peak / 1024 / 1024, 3),
    }


def _chart_fixture(root: Path, record_count: int) -> Path:
    database = root / f"chart-{record_count}.mesh.sqlite"
    MeshMrRepository(database)
    base = datetime(2026, 7, 30, 10, 0, 0)
    frame_width = 10
    frame_count = (record_count + frame_width - 1) // frame_width
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA synchronous = OFF")
        connection.execute(
            """
            INSERT INTO source_files (
                mr_id, original_path, archived_path, original_filename, archived_filename,
                sha256, file_size, imported_at, parser_version, parse_status
            ) VALUES ('benchmark-mr', 'benchmark.log', 'benchmark.log', 'benchmark.log',
                      'benchmark.log', 'benchmark-sha', ?, '2026-07-30 10:00:00.000', ?, 'ok')
            """,
            (record_count, SCHEMA_VERSION),
        )
        for start in range(0, frame_count, 10_000):
            stop = min(start + 10_000, frame_count)
            samples = []
            for frame_index in range(start, stop):
                timestamp = base + timedelta(seconds=frame_index)
                sample_time = timestamp.strftime("%Y-%m-%d %H:%M:%S.000")
                samples.append(
                    (
                        frame_index + 1,
                        1,
                        1,
                        sample_time,
                        int(timestamp.timestamp() * 1000),
                        "",
                    )
                )
            connection.executemany(
                """
                INSERT INTO samples (
                    id, source_file_id, radio, sample_time, sample_time_epoch_ms, timestamp_tag
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                samples,
            )
        for start in range(0, record_count, 10_000):
            stop = min(start + 10_000, record_count)
            links = []
            for index in range(start, stop):
                frame_index, slot = divmod(index, frame_width)
                sample_time = (base + timedelta(seconds=frame_index)).strftime(
                    "%Y-%m-%d %H:%M:%S.000"
                )
                peer_index = (frame_index + slot) % 64
                peer_mac = f"{peer_index + 1:012x}"
                role = "ACTIVE" if slot == 0 else "STANDBY"
                links.append(
                    (
                        index + 1,
                        frame_index + 1,
                        1,
                        1,
                        index + 1,
                        index + 1,
                        1,
                        sample_time,
                        role,
                        role,
                        peer_mac,
                        peer_mac,
                        peer_mac,
                        f"AP-{peer_index:02d}",
                        f"0d 00h 00m {frame_index % 60:02d}s",
                        1,
                        35 + (frame_index % 20),
                        38 + (frame_index % 20),
                        f"benchmark-{index + 1}",
                    )
                )
            connection.executemany(
                """
                INSERT INTO mesh_links (
                    id, sample_id, source_file_id, source_file_order, record_seq,
                    source_line_number, radio, sample_time, link_state_raw, link_state,
                    peer_mac_raw, peer_mac_normalized, peer_radio_mac, peer_ap_name,
                    duration_text, duration_seconds, local_rssi_db, peer_rssi_db,
                    record_fingerprint
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                links,
            )
        events = []
        for frame_index in range(1_000, frame_count, 1_000):
            event_time = (base + timedelta(seconds=frame_index)).strftime(
                "%Y-%m-%d %H:%M:%S.000"
            )
            previous_time = (base + timedelta(seconds=frame_index - 1)).strftime(
                "%Y-%m-%d %H:%M:%S.000"
            )
            events.append(
                (
                    "ACTIVE_SWITCH",
                    event_time,
                    1,
                    previous_time,
                    event_time,
                    1_000,
                    "000000000001",
                    "000000000002",
                    "{}",
                    1,
                )
            )
        connection.executemany(
            """
            INSERT INTO switch_events (
                event_type, event_time, radio, previous_sample_time, current_sample_time,
                observed_window_ms, from_peer_mac, to_peer_mac, details_json, source_file_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            events,
        )
    return database


def _measure_chart_query_once(database: Path, kind: str) -> dict[str, object]:
    repository = MeshMrRepository(database, read_only=True)
    tracemalloc.start()
    query_started = time.perf_counter()
    if kind == "active_path":
        payload = repository.query_active_link_chart_segments(
            source_file_id=1,
            max_rows=8_000,
            max_events=256,
        )
    else:
        payload = repository.query_trackside_link_chart_segment(
            source_file_id=1,
            max_rows=50_000,
            max_frames=2_000,
            max_series=512,
            max_events=256,
        )
    query_seconds = time.perf_counter() - query_started
    segment = dict(payload.get("run_segment") or {})
    rows = list(segment.get("rows") or [])
    events = list(segment.get("events") or [])
    transform_started = time.perf_counter()
    response_objects = [
        {
            "timestamp": row.get("sample_time"),
            "radio": row.get("radio"),
            "state": row.get("link_state"),
            "peer": row.get("peer_mac_normalized"),
            "local_rssi": row.get("local_rssi_db"),
            "peer_rssi": row.get("peer_rssi_db"),
        }
        for row in rows
    ]
    transform_seconds = time.perf_counter() - transform_started
    serialization_started = time.perf_counter()
    encoded = json.dumps(
        {"points": response_objects, "events": events},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    serialization_seconds = time.perf_counter() - serialization_started
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {
        "sql_query_seconds": round(query_seconds, 4),
        "python_build_seconds": round(transform_seconds, 4),
        "json_serialize_seconds": round(serialization_seconds, 4),
        "payload_bytes": len(encoded),
        "payload_mib": round(len(encoded) / 1024 / 1024, 3),
        "source_rows": int(segment.get("source_total_rows") or segment.get("total_rows") or len(rows)),
        "selected_rows": len(rows),
        "event_objects": len(events),
        "response_objects": len(response_objects) + len(events),
        "peak_memory_mib": round(peak / 1024 / 1024, 3),
        "repository_downsampled": bool(segment.get("repository_downsampled")),
    }


def _aggregate_chart_runs(runs: list[dict[str, object]]) -> dict[str, object]:
    numeric_fields = (
        "sql_query_seconds",
        "python_build_seconds",
        "json_serialize_seconds",
        "payload_bytes",
        "payload_mib",
        "source_rows",
        "selected_rows",
        "event_objects",
        "response_objects",
        "peak_memory_mib",
    )
    result: dict[str, object] = {}
    for field in numeric_fields:
        values = [float(run[field]) for run in runs]
        median = statistics.median(values)
        result[field] = (
            round(median, 4)
            if field.endswith("seconds") or field.endswith("mib")
            else int(round(median))
        )
    result["repository_downsampled"] = any(
        bool(run["repository_downsampled"]) for run in runs
    )
    return result


def _measure_chart_query(database: Path, kind: str) -> dict[str, object]:
    # The first fresh connection is reported separately from three subsequent
    # runs.  This distinguishes connection/page-cache warm-up from steady state
    # without pretending that a Python process can flush the Windows file cache.
    runs = [_measure_chart_query_once(database, kind) for _ in range(4)]
    warm_runs = runs[1:]
    return {
        "cold": {"first": runs[0]},
        "warm": {
            "first": warm_runs[0],
            "median": _aggregate_chart_runs(warm_runs),
            "best": min(
                warm_runs,
                key=lambda run: float(run["sql_query_seconds"])
                + float(run["python_build_seconds"])
                + float(run["json_serialize_seconds"]),
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profiles", type=int, default=36)
    parser.add_argument("--sources", type=int, default=1000)
    parser.add_argument(
        "--chart-records",
        action="append",
        type=int,
        choices=(50_000, 75_000, 100_000, 150_000, 200_000, 500_000, 1_000_000),
        default=[],
        help="追加图表链路基准规模；可重复传入 50k/75k/100k/150k/200k/500k/1m。",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(r"D:\NetConsoleTestData") / f"mesh-perf-{uuid4().hex}",
    )
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()
    args.root.mkdir(parents=True, exist_ok=False)
    try:
        paths = _fixture(args.root, args.profiles, args.sources)
        before = _measure(CountingQueryService(paths), legacy=True)
        index_started = time.perf_counter()
        MeshCatalogIndexService(paths).rebuild_now("demo")
        index_seconds = time.perf_counter() - index_started
        after = _measure(CountingQueryService(paths), legacy=False)
        chart_results: dict[str, object] = {}
        for record_count in args.chart_records:
            chart_database = _chart_fixture(args.root, record_count)
            chart_results[str(record_count)] = {
                "active_path": _measure_chart_query(chart_database, "active_path"),
                "trackside_signal": _measure_chart_query(
                    chart_database,
                    "trackside_signal",
                ),
            }
        print(
            json.dumps(
                {
                    "fixture": {
                        "profiles": args.profiles,
                        "sources": args.sources,
                    },
                    "before": before,
                    "catalog_backfill_seconds": round(index_seconds, 4),
                    "after": after,
                    "chart_loading": chart_results,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    finally:
        if not args.keep:
            shutil.rmtree(args.root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
