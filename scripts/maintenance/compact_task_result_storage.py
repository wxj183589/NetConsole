"""Build and optionally atomically replace a compact DEV tasks.db candidate.

The candidate phase is intentionally separate from result Blob migration:
logical readers are switched to Blob-first first, then verified ready rows may
release the duplicate ``task_results.canonical_json`` bytes.  The source DB is
opened read-only until the final atomic replacement and no source VACUUM or
checkpoint is performed.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import uuid
from collections.abc import Iterable
from contextlib import closing
from pathlib import Path

from netconsole.repositories.task_result_blob_repository import (
    TaskResultBlobError,
    verify_task_result_authority,
)


DEV_ROOT = Path(r"D:\NetConsoleData-dev")
PRODUCTION_ROOT = Path(r"D:\NetConsoleData")
DEFAULT_STAGING = Path(r"D:\study\NetConsole-Workspace\diagnostic\tasks-db-compaction-candidates")


def _quote(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def _open(path: Path, *, read_only: bool) -> sqlite3.Connection:
    if read_only:
        uri = f"{path.resolve().as_uri()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=10.0)
    else:
        conn = sqlite3.connect(path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _quick_check(path: Path) -> str:
    with closing(_open(path, read_only=True)) as conn:
        return str(conn.execute("PRAGMA quick_check").fetchone()[0])


def _physical_bytes(path: Path) -> int:
    """Count the database plus SQLite sidecars used by the live DB."""

    return sum(
        item.stat().st_size
        for item in (
            path,
            path.with_name(f"{path.name}-wal"),
            path.with_name(f"{path.name}-shm"),
        )
        if item.is_file()
    )


def _replace_compact_candidate(candidate: Path, source: Path) -> None:
    """Replace one closed DEV DB without leaving its old WAL sidecars behind."""

    wal = source.with_name(f"{source.name}-wal")
    shm = source.with_name(f"{source.name}-shm")
    if wal.is_file() and wal.stat().st_size:
        raise RuntimeError(
            f"source database has a non-empty WAL; stop writers before replace: {source}"
        )
    # A zero-length WAL and a shared-memory file are transient state belonging
    # to the old database.  They must not survive beside the new main file.
    for sidecar in (wal, shm):
        if sidecar.is_file():
            sidecar.unlink()
    os.replace(candidate, source)


def _task_rows(path: Path) -> dict[str, tuple[object, ...]]:
    with closing(_open(path, read_only=True)) as conn:
        if not _table_exists(conn, "task_snapshots"):
            return {}
        return {
            str(row["task_id"]): tuple(row)
            for row in conn.execute(
                "SELECT task_id, task_type, status, created_time, started_time, "
                "finished_time, updated_time, result_path, result_id, result_hash, "
                "result_summary_json, site_name FROM task_snapshots ORDER BY task_id"
            )
        }


def _result_rows(path: Path) -> dict[str, dict[str, object]]:
    with closing(_open(path, read_only=True)) as conn:
        if not _table_exists(conn, "task_results"):
            return {}
        output: dict[str, dict[str, object]] = {}
        for raw in conn.execute("SELECT * FROM task_results ORDER BY result_id"):
            try:
                verified = verify_task_result_authority(conn, dict(raw))
            except (sqlite3.DatabaseError, TaskResultBlobError) as exc:
                raise RuntimeError(
                    f"result authority invalid: {raw['result_id']}: {exc}"
                ) from exc
            output[str(verified["result_id"])] = {
                "result_id": verified["result_id"],
                "task_id": verified["task_id"],
                "terminal_event_type": verified["terminal_event_type"],
                "sha256": verified["sha256"],
                "byte_size": verified["byte_size"],
                "result": verified["result"],
            }
        return output


def _mapping_rows(path: Path) -> list[tuple[object, ...]]:
    with closing(_open(path, read_only=True)) as conn:
        if not _table_exists(conn, "online_mr_task_sessions"):
            return []
        return [
            tuple(row)
            for row in conn.execute(
                "SELECT * FROM online_mr_task_sessions ORDER BY controller_task_id"
            )
        ]


def _parity(source: Path, candidate: Path) -> dict[str, object]:
    source_tasks = _task_rows(source)
    candidate_tasks = _task_rows(candidate)
    source_results = _result_rows(source)
    candidate_results = _result_rows(candidate)
    source_mappings = _mapping_rows(source)
    candidate_mappings = _mapping_rows(candidate)
    task_list_parity = source_tasks == candidate_tasks
    result_ids = sorted(set(source_results) | set(candidate_results))
    result_parity = all(source_results.get(key) == candidate_results.get(key) for key in result_ids)
    mapping_parity = source_mappings == candidate_mappings
    source_status_counts = _status_counts(source_tasks.values())
    candidate_status_counts = _status_counts(candidate_tasks.values())
    sample_ids = _sample_task_ids(source_tasks)
    task_detail_parity = all(
        source_tasks.get(task_id) == candidate_tasks.get(task_id) for task_id in sample_ids
    ) and all(
        _result_for_task(source_tasks, source_results, task_id)
        == _result_for_task(candidate_tasks, candidate_results, task_id)
        for task_id in sample_ids
    )
    with closing(_open(candidate, read_only=True)) as conn:
        canonical_bytes = int(
            conn.execute(
                "SELECT COALESCE(SUM(length(CAST(canonical_json AS BLOB))), 0) "
                "FROM task_results WHERE blob_ready=1"
            ).fetchone()[0]
        ) if _table_exists(conn, "task_results") else 0
    return {
        "task_list_parity": "PASS" if task_list_parity else "FAIL",
        "task_detail_parity": "PASS" if task_detail_parity else "FAIL",
        "task_result_parity": "PASS" if result_parity else "FAIL",
        "online_mr_mapping_parity": "PASS" if mapping_parity else "FAIL",
        "source_status_counts": source_status_counts,
        "candidate_status_counts": candidate_status_counts,
        "sample_task_ids": sample_ids,
        "ready_canonical_bytes_after": canonical_bytes,
        "result_rows_source": len(source_results),
        "result_rows_candidate": len(candidate_results),
        "mapping_rows_source": len(source_mappings),
        "mapping_rows_candidate": len(candidate_mappings),
    }


def _result_for_task(
    tasks: dict[str, tuple[object, ...]],
    results: dict[str, dict[str, object]],
    task_id: str,
) -> dict[str, object] | None:
    row = tasks.get(task_id)
    if row is None:
        return None
    result_id = str(row[8] or "")
    return results.get(result_id)


def _status_counts(rows: Iterable[tuple[object, ...]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        status = str(row[2] or "UNKNOWN").upper()
        counts[status] = counts.get(status, 0) + 1
    return dict(sorted(counts.items()))


def _sample_task_ids(tasks: dict[str, tuple[object, ...]]) -> list[str]:
    ids = sorted(tasks)
    selected: list[str] = []
    for status in ("PENDING", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"):
        selected.extend(task_id for task_id in ids if tasks[task_id][2] == status)  # type: ignore[index]
    selected.extend(ids[:5])
    selected.extend(ids[-5:])
    return list(dict.fromkeys(selected))


def _build_candidate(source: Path, candidate: Path) -> dict[str, object]:
    candidate.parent.mkdir(parents=True, exist_ok=True)
    if candidate.exists():
        raise FileExistsError(f"candidate already exists: {candidate}")
    with closing(_open(source, read_only=True)) as source_conn, closing(
        _open(candidate, read_only=False)
    ) as candidate_conn:
        source_conn.backup(candidate_conn)
        candidate_conn.commit()
    with closing(_open(candidate, read_only=False)) as conn:
        if not _table_exists(conn, "task_results"):
            conn.commit()
            return {"released_rows": 0, "released_bytes": 0}
        rows = conn.execute(
            "SELECT result_id, length(CAST(canonical_json AS BLOB)) AS bytes "
            "FROM task_results WHERE blob_ready=1 AND canonical_json<>''"
        ).fetchall()
        released_rows = len(rows)
        released_bytes = sum(int(row["bytes"] or 0) for row in rows)
        conn.execute("DROP TRIGGER IF EXISTS trg_task_results_immutable")
        conn.execute(
            "UPDATE task_results SET canonical_json='' "
            "WHERE blob_ready=1 AND canonical_json<>''"
        )
        conn.commit()

    # Recreate the shared immutable trigger without constructing a repository
    # (repository initialization owns a long-lived SQLite handle on Windows).
    with closing(_open(candidate, read_only=False)) as conn:
        conn.execute("DROP TRIGGER IF EXISTS trg_task_results_immutable")
        conn.execute(
            """
            CREATE TRIGGER trg_task_results_immutable
            BEFORE UPDATE ON task_results
            WHEN NOT (
                OLD.result_id = NEW.result_id
                AND OLD.task_id = NEW.task_id
                AND OLD.terminal_event_type = NEW.terminal_event_type
                AND OLD.canonical_json = NEW.canonical_json
                AND OLD.sha256 = NEW.sha256
                AND OLD.byte_size = NEW.byte_size
                AND OLD.schema_version = NEW.schema_version
                AND OLD.created_time = NEW.created_time
                AND (
                    (OLD.content_sha256 = NEW.content_sha256
                     AND OLD.blob_codec = NEW.blob_codec
                     AND OLD.blob_ready = NEW.blob_ready)
                    OR (OLD.blob_ready = 0
                        AND NEW.blob_ready = 1
                        AND NEW.content_sha256 = OLD.sha256
                        AND NEW.blob_codec = 'zlib')
                )
            )
            BEGIN
                SELECT RAISE(ABORT, 'task_results rows are immutable');
            END;
            """
        )
        conn.commit()
    vacuumed = candidate.with_name(f"{candidate.stem}.vacuum.db")
    if vacuumed.exists():
        raise FileExistsError(f"candidate vacuum output already exists: {vacuumed}")
    with closing(_open(candidate, read_only=False)) as conn:
        conn.execute(f"VACUUM INTO {_quote(str(vacuumed))}")
    # Windows keeps the SQLite handle alive until the context is closed; only
    # then replace the pre-vacuum candidate with the compact output.
    candidate.unlink()
    os.replace(vacuumed, candidate)
    return {"released_rows": released_rows, "released_bytes": released_bytes}


def compact_database(
    site: str,
    source: Path,
    *,
    staging_dir: Path,
    apply: bool,
) -> dict[str, object]:
    if not source.is_file():
        return {"site": site, "source": str(source), "status": "MISSING"}
    token = uuid.uuid4().hex
    candidate = staging_dir / f"{site}.{token}.tasks.compact.candidate.db"
    before_bytes = _physical_bytes(source)
    build = _build_candidate(source, candidate)
    parity = _parity(source, candidate)
    quick_check = _quick_check(candidate)
    after_bytes = _physical_bytes(candidate)
    gates = {
        "task_list_parity": parity["task_list_parity"] == "PASS",
        "task_detail_parity": parity["task_detail_parity"] == "PASS",
        "task_result_parity": parity["task_result_parity"] == "PASS",
        "online_mr_mapping_parity": parity["online_mr_mapping_parity"] == "PASS",
        "quick_check": quick_check == "ok",
        "size_reduction": after_bytes < before_bytes,
    }
    replaced = False
    if apply and all(gates.values()):
        _replace_compact_candidate(candidate, source)
        replaced = True
    else:
        candidate.unlink(missing_ok=True)
    return {
        "site": site,
        "source": str(source),
        "status": "PASS" if all(gates.values()) else "FAIL",
        "mode": "APPLY" if apply else "DRY_RUN",
        "replaced": replaced,
        "before_bytes": before_bytes,
        "after_bytes": after_bytes,
        "reclaimed_bytes": max(0, before_bytes - after_bytes),
        "reclaim_percent": round(max(0, before_bytes - after_bytes) * 100 / before_bytes, 4) if before_bytes else 0.0,
        "external_bytes_created": 0,
        "build": build,
        "quick_check": quick_check,
        "parity": parity,
        "gates": gates,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="构建并验证 tasks.db 压缩候选库")
    parser.add_argument("--data-root", type=Path, default=DEV_ROOT)
    parser.add_argument("--site")
    parser.add_argument("--all-sites", action="store_true")
    parser.add_argument("--staging-dir", type=Path, default=DEFAULT_STAGING)
    parser.add_argument("--apply", action="store_true", help="通过全部候选验证后原子替换 DEV tasks.db")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = args.data_root.resolve()
    if root == PRODUCTION_ROOT.resolve():
        raise SystemExit("禁止压缩生产数据根 D:\\NetConsoleData")
    if bool(args.site) == bool(args.all_sites):
        raise SystemExit("必须指定 --site 或 --all-sites（二选一）")
    if args.apply and root != DEV_ROOT.resolve():
        raise SystemExit("--apply 只允许 D:\\NetConsoleData-dev")
    sites_root = root / "sites"
    sites = [args.site] if args.site else sorted(
        item.name for item in sites_root.iterdir() if item.is_dir()
    )
    reports: list[dict[str, object]] = []
    for site in sites:
        reports.append(
            compact_database(
                site,
                sites_root / site / "db" / "tasks.db",
                staging_dir=args.staging_dir.resolve(),
                apply=bool(args.apply),
            )
        )
    payload = {
        "schema": "task-result-storage-compaction/v1",
        "data_root": str(root),
        "apply": bool(args.apply),
        "reports": reports,
        "status": "PASS" if all(item["status"] in {"PASS", "MISSING"} for item in reports) else "FAIL",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
