"""Preview or explicitly retire GUI-removed Task Center rows.

This is a one-time operational cleanup command, not an automatic retention
worker.  The default is read-only preview.  ``--apply`` reuses
``TaskCleanupService`` and ``TaskRepository.delete_task_owned_rows``; it never
deletes application logs, Artifact files, business databases, Ground data or
Online MR mappings.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from netconsole.core.paths import PathResolver
from netconsole.repositories.task_repository import TaskRepository
from netconsole.repositories.task_cleanup_schema import (
    TaskCleanupSchemaError,
    inspect_task_cleanup_schema,
)
from netconsole.services.job_center.task_authority_index import TaskAuthorityIndex
from netconsole.services.job_center.task_cleanup_service import TaskCleanupService


DEFAULT_DATA_ROOT = Path("D:/NetConsoleData-dev").resolve()
PRODUCTION_DATA_ROOT = Path("D:/NetConsoleData").resolve()


class _ReadOnlyTaskRepository(TaskRepository):
    """TaskRepository projection that never initializes or writes a database."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self._verified_result_cache = {}

    def _connect(self) -> sqlite3.Connection:
        uri = f"{self.db_path.resolve().as_uri()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection


def _site_databases(data_root: Path, site: str | None, all_sites: bool) -> list[tuple[str, Path]]:
    if site:
        return [(site, data_root / "sites" / site / "db" / "tasks.db")]
    if not all_sites:
        raise SystemExit("必须指定 --site 或 --all-sites")
    sites_root = data_root / "sites"
    if not sites_root.is_dir():
        return []
    return [
        (item.name, item / "db" / "tasks.db")
        for item in sorted(sites_root.iterdir(), key=lambda path: path.name.casefold())
        if item.is_dir() and (item / "db" / "tasks.db").is_file()
    ]


def _removed_candidates(database: Path) -> list[dict[str, Any]]:
    with closing(_ReadOnlyTaskRepository(database)._connect()) as connection:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_schema WHERE type='table'"
            ).fetchall()
        }
        if "task_snapshots" not in tables:
            return []
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(task_snapshots)").fetchall()
        }
        if "dismissed_at" not in columns:
            return []
        rows = connection.execute(
            """
            SELECT task_id, status, created_time, finished_time, dismissed_at
            FROM task_snapshots
            WHERE dismissed_at <> ''
              AND status IN ('COMPLETED', 'FAILED', 'CANCELLED')
            ORDER BY dismissed_at, task_id
            """
        ).fetchall()
        return [dict(row) for row in rows]


def _preview_site(paths: PathResolver, site: str, database: Path, *, apply: bool) -> dict[str, Any]:
    schema_profile = inspect_task_cleanup_schema(database)
    schema_ready_for_preview = bool(schema_profile.get("preview_compatible"))
    schema_ready_for_apply = bool(schema_profile.get("apply_compatible"))
    if apply and not schema_ready_for_apply:
        raise TaskCleanupSchemaError(
            "TASK_SCHEMA_COMPATIBILITY apply blocked: "
            f"site={site} database={database}"
        )
    candidates = _removed_candidates(database)
    if schema_ready_for_preview:
        read_repository = _ReadOnlyTaskRepository(database)
        service = TaskCleanupService(read_repository, paths=paths, site_name=site)
        decisions = service.preview_cleanup([str(row["task_id"]) for row in candidates])
    else:
        decisions = {"decisions": []}
    decision_by_id = {
        str(item["task_id"]): item
        for item in decisions.get("decisions", [])
        if isinstance(item, dict)
    }
    rows = []
    for candidate in candidates:
        task_id = str(candidate["task_id"])
        decision = decision_by_id.get(task_id, {})
        reasons = [str(value) for value in decision.get("reasons", [])]
        if not schema_ready_for_apply:
            reasons.append("TASK_SCHEMA_COMPATIBILITY_REQUIRED")
        rows.append(
            {
                "task_id": task_id,
                "state": str(candidate["status"] or ""),
                "created_at": str(candidate["created_time"] or ""),
                "finished_at": str(candidate["finished_time"] or ""),
                "visible_in_gui": False,
                "user_removed": True,
                "active_reference": bool(
                    set(reasons)
                    & {
                        "ACTIVE_TASK",
                        "ONLINE_MR_MAPPING",
                        "GROUND_CURRENT_MAPPING",
                        "RESOURCE_REFERENCE",
                    }
                ),
                "events_rows": int(decision.get("event_rows") or 0),
                "snapshots_rows": int(decision.get("snapshot_rows") or 0),
                "result_rows": int(decision.get("result_rows") or 0),
                "payload_bytes": int(
                    decision.get("event_payload_bytes") or 0
                )
                + int(decision.get("snapshot_payload_bytes") or 0)
                + int(decision.get("result_bytes") or 0),
                "logs_preserved": True,
                "artifact_preserved": True,
                "safe_to_retire": bool(
                    schema_ready_for_apply and decision.get("can_cleanup")
                ),
                "classification": (
                    "GUI_REMOVED_OPERATIONAL_RESIDUAL"
                    if schema_ready_for_apply
                    else "SAFE_BUT_SCHEMA_BLOCKED"
                ),
                "reason": reasons or ["SAFE_EXPLICIT_OPERATIONAL_RETIREMENT"],
            }
        )

    applied: dict[str, Any] = {}
    if apply and candidates:
        repository = TaskRepository(database)
        cleanup = TaskCleanupService(repository, paths=paths, site_name=site)
        applied = cleanup.cleanup_tasks([str(row["task_id"]) for row in candidates])
        TaskAuthorityIndex(paths).remove(
            list(applied.get("deleted_task_ids") or []), site_name=site
        )
    return {
        "site": site,
        "database": str(database),
        "candidates": rows,
        "candidate_count": len(rows),
        "safe_to_retire_count": sum(bool(row["safe_to_retire"]) for row in rows),
        "schema_compatibility": schema_profile,
        "migration_required": bool(schema_profile.get("migration_required")),
        "cleanup_ready": schema_ready_for_apply,
        "apply": bool(apply),
        "applied": applied,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="预览或显式回收 GUI 已从任务中心移除的 tasks.db Operational rows"
    )
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--site")
    parser.add_argument("--all-sites", action="store_true")
    parser.add_argument("--apply", action="store_true", help="执行已通过引用检查的 Operational GC")
    parser.add_argument(
        "--allow-production",
        action="store_true",
        help="允许 --apply 触及 D:/NetConsoleData；默认拒绝",
    )
    parser.add_argument("--output", type=Path, help="将 JSON 计划/结果写到指定路径")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    data_root = args.data_root.resolve()
    if args.apply and data_root == PRODUCTION_DATA_ROOT and not args.allow_production:
        raise SystemExit("生产 tasks.db 仅允许显式 --allow-production --apply")
    paths = PathResolver(app_root=Path.cwd(), data_root=data_root)
    targets = _site_databases(data_root, args.site, args.all_sites)
    reports = []
    if args.apply:
        preflight_reports = [
            _preview_site(paths, site, database, apply=False)
            for site, database in targets
        ]
        blocked = [
            str(item.get("site") or "")
            for item in preflight_reports
            if not bool(item.get("cleanup_ready"))
        ]
        if blocked:
            raise TaskCleanupSchemaError(
                "TASK_SCHEMA_COMPATIBILITY all-sites gate blocked: "
                + ", ".join(blocked)
            )
    for site, database in targets:
        if not database.is_file():
            reports.append({"site": site, "database": str(database), "error": "tasks.db 不存在"})
            continue
        reports.append(_preview_site(paths, site, database, apply=args.apply))
    report = {
        "schema": "retired-task-operational-gc/v1",
        "data_root": str(data_root),
        "read_only_preview": not args.apply,
        "production_apply_guard": data_root == PRODUCTION_DATA_ROOT,
        "sites": reports,
        "candidate_count": sum(int(item.get("candidate_count") or 0) for item in reports),
        "safe_to_retire_count": sum(
            int(item.get("safe_to_retire_count") or 0) for item in reports
        ),
        "task_schema_compatibility": {
            "required_databases": len(reports),
            "passed_databases": sum(
                1 for item in reports if bool(item.get("cleanup_ready"))
            ),
            "status": "PASS"
            if all(bool(item.get("cleanup_ready")) for item in reports)
            else "BLOCKED",
        },
    }
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
        args.output.resolve().write_text(encoded, encoding="utf-8")
        print(
            json.dumps(
                {
                    "output": str(args.output.resolve()),
                    "candidate_count": report["candidate_count"],
                    "safe_to_retire_count": report["safe_to_retire_count"],
                    "apply": report["read_only_preview"] is False,
                },
                ensure_ascii=False,
            )
        )
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
