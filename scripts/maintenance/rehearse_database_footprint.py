"""Development-root-only database footprint snapshot and rehearsal CLI."""

from __future__ import annotations

import argparse
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from netconsole.core.paths import PathResolver
from netconsole.services.database_footprint_maintenance import (
    DevelopmentDatabaseCompactService,
    assert_development_path,
    resolve_registered_active_site_readonly,
    sqlite_online_backup_readonly,
    sqlite_quick_profile,
)
from netconsole.services.database_upgrade.sqlite_consistency import sha256_file
from netconsole.services.job_center.task_result_maintenance import (
    TaskResultMaintenanceService,
)
from netconsole.services.job_center.task_result_rollout import (
    TaskResultRolloutService,
)
from netconsole.services.job_center.task_application_service import (
    TaskApplicationService,
)
from netconsole.repositories.task_repository import TaskRepository
from netconsole.services.site_retention import SiteRetentionService
from netconsole.services.site_sync import _apply_task_merge


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=(
            "snapshot",
            "prepare-rehearsal",
            "profile",
            "task-backfill-analysis",
            "task-profile",
            "task-enable-dual-write",
            "task-backfill",
            "task-ref-authority",
            "task-retention-preview",
            "task-retention-apply",
            "task-compatibility",
            "compact",
            "replace",
            "rollback",
        ),
    )
    parser.add_argument("--production-data-root", type=Path)
    parser.add_argument("--run-root", type=Path)
    parser.add_argument("--diagnostics-dir", type=Path)
    parser.add_argument("--maintenance-data-root", type=Path)
    parser.add_argument("--site-id")
    parser.add_argument("--site-alias", action="append", default=[])
    parser.add_argument("--database", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--plan-file", type=Path)
    parser.add_argument("--expected-plan-digest")
    parser.add_argument("--expected-revision", type=int)
    parser.add_argument("--reason", default="")
    parser.add_argument("--updated-by", default="database-footprint-rehearsal")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--compacted", type=Path)
    parser.add_argument("--rollback-path", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--allow-development-root-only", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "snapshot":
        result = _snapshot(args)
    elif args.command == "prepare-rehearsal":
        result = _prepare_rehearsal(args)
    elif args.command == "profile":
        result = sqlite_quick_profile(_required_path(args.database, "--database"))
    elif args.command.startswith("task-"):
        result = (
            _task_compatibility(args)
            if args.command == "task-compatibility"
            else _task_command(args)
        )
    elif args.command == "compact":
        service = _compact_service(args)
        result = service.compact(
            _required_path(args.source, "--source"),
            _required_path(args.compacted, "--compacted"),
        )
    elif args.command == "replace":
        _require_apply(args)
        result = _compact_service(args).replace(
            _required_path(args.source, "--source"),
            _required_path(args.compacted, "--compacted"),
            _required_path(args.rollback_path, "--rollback-path"),
        )
    else:
        _require_apply(args)
        result = _compact_service(args).rollback(
            _required_path(args.source, "--source"),
            _required_path(args.rollback_path, "--rollback-path"),
        )
    payload = _jsonable(result)
    if args.output:
        _write_json(args.output, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _snapshot(args: argparse.Namespace) -> dict[str, Any]:
    production_root = _required_path(
        args.production_data_root, "--production-data-root"
    ).resolve()
    run_root = assert_development_path(
        _required_path(args.run_root, "--run-root")
    )
    diagnostics = assert_development_path(
        _required_path(args.diagnostics_dir, "--diagnostics-dir")
    )
    paths = PathResolver(data_root=production_root)
    metadata_paths = [
        paths.app_config_path,
        paths.config_dir / "site_registry.json",
    ]
    metadata_before = {
        str(path): {
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
            "modified_ns": path.stat().st_mtime_ns,
        }
        for path in metadata_paths
    }
    site = resolve_registered_active_site_readonly(paths)
    resolved = {
        "site_id": site.site_id,
        "display_name": site.display_name,
        "site_root": str(site.root_path),
        "db_root": str(site.root_path / "db"),
        "devices_database": str(site.root_path / "db" / "devices.db"),
        "tasks_database": str(site.root_path / "db" / "tasks.db"),
        "history_root": str(site.root_path / "db" / "history"),
        "registry_site_count": len(
            json.loads(
                (paths.config_dir / "site_registry.json").read_text(encoding="utf-8")
            ).get("sites", [])
        ),
    }
    _write_json(diagnostics / "RESOLVED_SITE.json", resolved)
    source = run_root / "source"
    devices = sqlite_online_backup_readonly(
        site.root_path / "db" / "devices.db", source / "devices.db"
    )
    tasks = sqlite_online_backup_readonly(
        site.root_path / "db" / "tasks.db", source / "tasks.db"
    )
    metadata_after = {
        str(path): {
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
            "modified_ns": path.stat().st_mtime_ns,
        }
        for path in metadata_paths
    }
    if metadata_before != metadata_after:
        raise RuntimeError("production site metadata changed during read-only resolution")
    return {
        "resolved_site": resolved,
        "snapshots": {"devices": devices, "tasks": tasks},
        "production_metadata_unchanged": True,
        "production_operations": {
            "sqlite_online_backup_read": "YES",
            "DML": "NO",
            "DDL": "NO",
            "checkpoint": "NO",
            "vacuum": "NO",
        },
    }


def _prepare_rehearsal(args: argparse.Namespace) -> dict[str, Any]:
    run_root = assert_development_path(
        _required_path(args.run_root, "--run-root")
    )
    source = run_root / "source"
    devices = sqlite_online_backup_readonly(
        source / "devices.db", run_root / "devices-rehearsal" / "devices.db"
    )
    tasks = sqlite_online_backup_readonly(
        source / "tasks.db", run_root / "tasks-rehearsal" / "tasks.db"
    )
    (run_root / "devices-rehearsal" / "history").mkdir(
        parents=True, exist_ok=False
    )
    return {"devices": devices, "tasks": tasks, "source_preserved": True}


def _task_command(args: argparse.Namespace) -> dict[str, Any]:
    database = _required_path(args.database, "--database")
    maintenance_root = _required_path(
        args.maintenance_data_root, "--maintenance-data-root"
    )
    site_id = str(args.site_id or "").strip()
    if not site_id:
        raise SystemExit("task maintenance requires --site-id")
    paths = PathResolver(data_root=maintenance_root)
    if args.command in {
        "task-profile",
        "task-enable-dual-write",
        "task-backfill-analysis",
        "task-backfill",
        "task-ref-authority",
    }:
        service = TaskResultMaintenanceService(
            paths, site_id=site_id, tasks_database=database
        )
        if args.command == "task-profile":
            return service.profile()
        if args.command == "task-enable-dual-write":
            _require_apply(args)
            if args.expected_revision is None or not args.reason.strip():
                raise SystemExit(
                    "task-enable-dual-write requires --expected-revision and --reason"
                )
            updated = TaskResultRolloutService(database).enable_dual_write(
                expected_revision=args.expected_revision,
                reason=args.reason,
                updated_by=args.updated_by,
            )
            return {
                "state": updated.state.value,
                "revision": updated.revision,
                "updated_at": updated.updated_at,
            }
        if args.command == "task-backfill-analysis":
            return service.analyze_backfill()
        if args.command == "task-backfill":
            return service.backfill(
                apply=args.apply,
                allow_development_root_only=args.allow_development_root_only,
            )
        if args.expected_revision is None or not args.reason.strip():
            raise SystemExit(
                "task-ref-authority requires --expected-revision and --reason"
            )
        return service.enable_ref_authority(
            expected_revision=args.expected_revision,
            reason=args.reason,
            updated_by=args.updated_by,
            apply=args.apply,
            allow_development_root_only=args.allow_development_root_only,
        )
    retention = SiteRetentionService(paths)
    if args.command == "task-retention-preview":
        return retention.preview_typed_task_retention(
            site_id, tasks_database=database
        )
    plan_path = _required_path(args.plan_file, "--plan-file")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if not isinstance(plan, dict) or not args.expected_plan_digest:
        raise SystemExit(
            "task-retention-apply requires an object plan and --expected-plan-digest"
        )
    return retention.apply_typed_task_retention(
        plan,
        expected_plan_digest=args.expected_plan_digest,
        apply=args.apply,
        allow_development_root_only=args.allow_development_root_only,
    )


def _compact_service(args: argparse.Namespace) -> DevelopmentDatabaseCompactService:
    data_root = _required_path(
        args.maintenance_data_root, "--maintenance-data-root"
    )
    site_id = str(args.site_id or "").strip()
    if not site_id:
        raise SystemExit("compact maintenance requires --site-id")
    return DevelopmentDatabaseCompactService(
        PathResolver(data_root=data_root), site_id=site_id
    )


def _task_compatibility(args: argparse.Namespace) -> dict[str, Any]:
    database = assert_development_path(
        _required_path(args.database, "--database")
    )
    run_root = assert_development_path(_required_path(args.run_root, "--run-root"))
    maintenance_root = _required_path(
        args.maintenance_data_root, "--maintenance-data-root"
    )
    site_id = str(args.site_id or "").strip()
    if not site_id:
        raise SystemExit("task compatibility requires --site-id")
    paths = PathResolver(data_root=maintenance_root)
    repository = TaskRepository(database)
    status = TaskResultRolloutService(database).status()
    if status["task_result_storage_state"] != "RESULT_REF_AUTHORITY":
        raise RuntimeError("task compatibility requires RESULT_REF_AUTHORITY")

    with repository._connect() as connection:
        result_rows = [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM task_results ORDER BY result_id"
            ).fetchall()
        ]
        for row in result_rows:
            repository._verified_result_row(row)
        online_columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(online_mr_task_sessions)"
            ).fetchall()
        }
        online_column = (
            "controller_task_id"
            if "controller_task_id" in online_columns
            else "task_id"
        )
        online_ids = [
            str(row[0])
            for row in connection.execute(
                f'SELECT "{online_column}" FROM online_mr_task_sessions'
            ).fetchall()
        ]
        ground_ids = [
            str(row[0])
            for row in connection.execute(
                "SELECT task_id FROM task_snapshots "
                "WHERE lower(task_type) LIKE '%ground%'"
            ).fetchall()
        ]
        artifact_ids = [
            str(row[0])
            for row in connection.execute(
                "SELECT s.task_id FROM task_snapshots AS s "
                "LEFT JOIN task_results AS r ON r.result_id=s.result_id "
                "WHERE s.result_path<>'' OR s.result_json LIKE '%\"artifact_id\"%' "
                "OR r.canonical_json LIKE '%\"artifact_id\"%'"
            ).fetchall()
        ]

    task_center = repository.list(limit=200)
    if not task_center:
        raise RuntimeError("Task Center compatibility returned no rows")
    service = TaskApplicationService(
        paths, site_name=site_id, reconcile_on_start=False
    )
    service._repositories[site_id] = repository
    compatibility_task = "database-footprint-ref-compatibility"
    if repository.get(compatibility_task) is None:
        service.create_external_task(
            task_id=compatibility_task,
            task_type="agent_task",
            task_name="Database Footprint Ref Compatibility",
            source="agent",
            site_name=site_id,
        )
        stream = service.events.open_stream()
        result = {"status": "COMPLETED", "rows": 17, "source": "agent"}
        snapshot = service.record_external_event(
            compatibility_task,
            "finished",
            {"message": "done", "result": result},
            source="agent",
            site_name=site_id,
            event_id="finished-database-footprint-ref-compatibility",
            event_time="2026-08-16T05:00:00Z",
        )
        live = stream.get(timeout=2)
        stream.close()
        if snapshot.result != result or live["payload"].get("result") != result:
            raise RuntimeError("Agent/WebSocket ref compatibility failed")
    rest_snapshot = service.get_task(compatibility_task)
    rest_events = service.list_events(compatibility_task)
    if (
        rest_snapshot is None
        or not rest_snapshot.result
        or not rest_events
        or not rest_events[-1]["payload"].get("result")
    ):
        raise RuntimeError("REST task ref read-through failed")
    with closing(sqlite3.connect(database)) as connection:
        raw_snapshot = connection.execute(
            "SELECT result_json FROM task_snapshots WHERE task_id=?",
            (compatibility_task,),
        ).fetchone()[0]
        raw_event = json.loads(
            connection.execute(
                "SELECT payload_json FROM task_events WHERE task_id=? "
                "AND event_type='finished'",
                (compatibility_task,),
            ).fetchone()[0]
        )
    if raw_snapshot != "{}" or "result" in raw_event:
        raise RuntimeError("ref authority persisted an unexpected full result copy")
    restarted = TaskRepository(database)
    if restarted.get(compatibility_task).result != rest_snapshot.result:
        raise RuntimeError("restart ref read-through failed")

    online_resolved = sum(repository.get(task_id) is not None for task_id in online_ids)
    ground_resolved = sum(repository.get(task_id) is not None for task_id in ground_ids)
    artifact_resolved = sum(
        repository.get(task_id) is not None for task_id in artifact_ids
    )

    exported = run_root / "site-package-export" / "tasks.db"
    imported = run_root / "site-package-import" / "tasks.db"
    export_result = (
        {"destination": str(exported), **sqlite_quick_profile(exported)}
        if exported.is_file()
        else sqlite_online_backup_readonly(database, exported)
    )
    TaskRepository(imported)
    merge = _apply_task_merge(
        imported,
        exported,
        {},
        site_id=site_id,
        site_aliases=args.site_alias,
    )
    source_counts = _task_package_counts(exported)
    imported_counts = _task_package_counts(imported)
    if source_counts != imported_counts:
        raise RuntimeError("Site Package task table counts do not match")
    imported_repository = TaskRepository(imported)
    imported_snapshot = imported_repository.get(compatibility_task)
    if imported_snapshot is None or imported_snapshot.result != rest_snapshot.result:
        raise RuntimeError("Site Package imported ref read-through failed")
    idempotent_merge = _apply_task_merge(
        imported,
        exported,
        {},
        site_id=site_id,
        site_aliases=args.site_alias,
    )
    return {
        "Task Center": "PASS",
        "REST": "PASS",
        "WebSocket": "PASS",
        "Agent": "PASS",
        "restart": "PASS",
        "Online MR": "PASS" if online_resolved == len(online_ids) else "PARTIAL",
        "Ground": "PASS" if ground_resolved == len(ground_ids) else "PARTIAL",
        "Artifact": "PASS" if artifact_resolved == len(artifact_ids) else "PARTIAL",
        "Site Package": "PASS",
        "task_results_verified": len(result_rows),
        "online_mr_mappings": len(online_ids),
        "online_mr_tasks_resolved": online_resolved,
        "ground_tasks": len(ground_ids),
        "ground_tasks_resolved": ground_resolved,
        "artifact_tasks": len(artifact_ids),
        "artifact_tasks_resolved": artifact_resolved,
        "site_package_export": export_result,
        "site_package_merge": merge,
        "site_package_idempotent_merge": idempotent_merge,
        "site_package_counts": source_counts,
    }


def _task_package_counts(path: Path) -> dict[str, int]:
    with closing(sqlite3.connect(path)) as connection:
        return {
            table: int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            for table in (
                "task_results",
                "task_snapshots",
                "task_events",
                "online_mr_task_sessions",
            )
        }


def _require_apply(args: argparse.Namespace) -> None:
    if not args.apply or not args.allow_development_root_only:
        raise SystemExit(
            "operation requires --apply and --allow-development-root-only"
        )


def _required_path(value: Path | None, name: str) -> Path:
    if value is None:
        raise SystemExit(f"command requires {name}")
    return value


def _write_json(path: Path, value: object) -> None:
    target = assert_development_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise FileExistsError(f"diagnostic output already exists: {target}")
    target.write_text(
        json.dumps(_jsonable(value), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def _jsonable(value: object) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return {
            field: _jsonable(getattr(value, field))
            for field in value.__dataclass_fields__  # type: ignore[attr-defined]
        }
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


if __name__ == "__main__":
    raise SystemExit(main())
