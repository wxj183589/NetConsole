"""Inspect or explicitly change one site's task result storage rollout."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from netconsole.core.runtime_environment import (
    data_environment,
    require_data_root_write_allowed,
)
from netconsole.core.paths import PathResolver
from netconsole.services.database_upgrade.coordinator import (
    database_maintenance_lock,
    site_database_maintenance_key,
)
from netconsole.services.job_center.task_result_rollout import (
    TaskResultRolloutError,
    TaskResultRolloutService,
)
from netconsole.services.production_database_maintenance import (
    PRODUCTION_SITE_ALLOWLIST,
    ProductionMaintenanceError,
    resolve_production_database_scope,
)
from netconsole.services.site_storage import SiteRegistryRepository


TASK_RESULT_ROLLOUT_AUTHORIZATION = "TASK_RESULT_ROLLOUT_AUTHORIZED"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("status", "enable-dual-write", "disable-dual-write"),
    )
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--site-id", required=True)
    parser.add_argument("--expected-revision", type=int)
    parser.add_argument("--reason", default="")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="required for an explicit persisted rollout transition",
    )
    parser.add_argument(
        "--allow-production-write",
        action="store_true",
        help="明确授权对 production 数据根执行 rollout 变更",
    )
    parser.add_argument(
        "--authorization",
        default="",
        help="Production rollout operation authorization",
    )
    return parser


def _production_scope_required(args: argparse.Namespace) -> bool:
    site_id = str(args.site_id or "").strip().casefold()
    root = Path(args.data_root).expanduser()
    marker = root / "runtime_mode.json"
    if marker.is_file():
        try:
            environment = data_environment(root)
        except RuntimeError as exc:
            raise SystemExit(
                f"PRODUCTION_DATA_ENVIRONMENT_INVALID: {root}"
            ) from exc
        if environment.is_production:
            return True
    return bool(args.allow_production_write) or site_id in PRODUCTION_SITE_ALLOWLIST


def _task_database(args: argparse.Namespace) -> tuple[PathResolver, Path, bool]:
    paths = PathResolver(data_root=args.data_root)
    if _production_scope_required(args):
        try:
            site_id, database, _site = resolve_production_database_scope(
                paths, args.site_id, "tasks.db"
            )
        except ProductionMaintenanceError as exc:
            raise SystemExit(str(exc)) from exc
        return paths, database, True

    site = SiteRegistryRepository(paths).get(args.site_id)
    database = site.root_path / "db" / "tasks.db"
    return paths, database.resolve(), False


def _assert_writer_quiescent(database: Path) -> None:
    wal = database.with_name(f"{database.name}-wal")
    if wal.is_file() and wal.stat().st_size:
        raise SystemExit("TASK_RESULT_ROLLOUT_WRITER_NOT_QUIESCENT: tasks.db WAL is non-empty")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "enable-dual-write" and args.apply:
        raise SystemExit(
            "TASK_RESULT_RUNTIME_ROLLOUT_DISABLED: current runtime writer "
            "is fixed at LEGACY_DUAL_FULL; enable-dual-write is not an "
            "effective production operation"
        )
    paths, database, canonical_production = _task_database(args)
    service = TaskResultRolloutService(database)
    if args.command == "status":
        result = service.status()
    else:
        if not args.apply:
            raise SystemExit("rollout transitions require explicit --apply")
        require_data_root_write_allowed(
            args.data_root,
            "TASK_RESULT_ROLLOUT",
            allow_production_write=args.allow_production_write,
        )
        if canonical_production and args.authorization != TASK_RESULT_ROLLOUT_AUTHORIZATION:
            raise SystemExit(
                "TASK_RESULT_ROLLOUT_AUTHORIZATION_REQUIRED: explicit operation authorization is required"
            )
        if args.expected_revision is None or not args.reason.strip():
            raise SystemExit(
                "rollout transitions require --expected-revision and --reason"
            )
        try:
            with database_maintenance_lock(
                paths, site_database_maintenance_key(str(args.site_id).strip())
            ):
                _assert_writer_quiescent(database)
                # The service owns the SQLite CAS transaction.  The lock and
                # the canonical path check above keep this operation bound to
                # one site/database while that CAS is evaluated.
                service.disable_dual_write(
                    expected_revision=args.expected_revision,
                    reason=args.reason,
                    updated_by="maintenance-cli",
                )
        except TaskResultRolloutError as exc:
            raise SystemExit(f"{exc.code}: {exc}") from exc
        result = service.status()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
