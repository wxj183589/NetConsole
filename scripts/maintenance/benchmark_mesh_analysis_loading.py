from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import time
import tracemalloc
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profiles", type=int, default=36)
    parser.add_argument("--sources", type=int, default=1000)
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
