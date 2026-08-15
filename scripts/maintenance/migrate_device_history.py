"""Explicit maintenance CLI for COPY-only legacy device history migration."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from netconsole.core.paths import PathResolver
from netconsole.services.history_legacy_migration import HistoryLegacyMigrationService
from netconsole.services.site_storage import SiteRegistryRepository


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=(
            "inventory",
            "start",
            "pause",
            "resume",
            "status",
            "cutover",
            "rollback",
            "mark-delete-eligible",
            "preview-delete-plan",
            "validate-delete-plan",
        ),
    )
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--site-id", required=True)
    parser.add_argument("--source-db", type=Path)
    parser.add_argument("--history-root", type=Path)
    parser.add_argument("--diagnostics-dir", type=Path)
    parser.add_argument("--migration-id")
    parser.add_argument("--source-table", action="append", default=[])
    parser.add_argument("--expected-revision", type=int)
    parser.add_argument("--reason", default="")
    parser.add_argument("--observation-file", type=Path)
    parser.add_argument("--plan-file", type=Path)
    parser.add_argument("--chunk-rows", type=int, default=250, choices=(100, 250, 500))
    parser.add_argument("--max-elapsed-seconds", type=float, default=2.0)
    parser.add_argument("--slow-storage-delay-seconds", type=float, default=0.0)
    parser.add_argument("--immutable-source", action="store_true")
    parser.add_argument("--unattended-active", action="store_true")
    parser.add_argument(
        "--light",
        action="store_true",
        help="skip exact COUNT/MIN/MAX inventory queries",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="required for COPY and non-destructive authority state changes",
    )
    return parser


def _service(args: argparse.Namespace) -> HistoryLegacyMigrationService:
    paths = PathResolver(data_root=args.data_root)
    site = SiteRegistryRepository(paths).get(args.site_id)
    source_database = (args.source_db or (site.root_path / "db" / "devices.db")).resolve()
    history_root = (args.history_root or (site.root_path / "db" / "history")).resolve()
    run_id = datetime.now(UTC).astimezone().strftime("%Y%m%dT%H%M%S%z")
    diagnostics = (
        args.diagnostics_dir
        or Path("D:/study/diagnostic/NetConsole/device-history-migration") / run_id
    ).resolve()
    return HistoryLegacyMigrationService(
        paths,
        site_id=site.site_id,
        source_database=source_database,
        history_root=history_root,
        diagnostics_dir=diagnostics,
        immutable_source=args.immutable_source,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    service = _service(args)
    if (
        args.command
        in {
            "start",
            "resume",
            "cutover",
            "rollback",
            "mark-delete-eligible",
        }
        and not args.apply
    ):
        raise SystemExit(
            "COPY/authority changes require explicit --apply; source deletion is not implemented"
        )
    if args.command == "inventory":
        result = service.inventory(exact_counts=not args.light)
    elif args.command == "start":
        result = service.start(
            migration_id=args.migration_id,
            chunk_rows=args.chunk_rows,
            max_elapsed_seconds=args.max_elapsed_seconds,
            slow_storage_delay_seconds=args.slow_storage_delay_seconds,
            unattended_active=lambda: bool(args.unattended_active),
        )
    elif args.command == "pause":
        if not args.migration_id:
            raise SystemExit("pause requires --migration-id")
        result = service.pause(args.migration_id)
    elif args.command == "resume":
        if not args.migration_id:
            raise SystemExit("resume requires --migration-id")
        result = service.resume(
            args.migration_id,
            max_elapsed_seconds=args.max_elapsed_seconds,
            slow_storage_delay_seconds=args.slow_storage_delay_seconds,
            unattended_active=lambda: bool(args.unattended_active),
        )
    elif args.command == "status":
        if not args.migration_id:
            raise SystemExit("status requires --migration-id")
        result = service.status(args.migration_id)
    elif args.command in {"cutover", "rollback", "mark-delete-eligible"}:
        if not args.migration_id or len(args.source_table) != 1:
            raise SystemExit(
                f"{args.command} requires --migration-id and exactly one --source-table"
            )
        if args.expected_revision is None or not args.reason.strip():
            raise SystemExit(
                f"{args.command} requires --expected-revision and --reason"
            )
        table = str(args.source_table[0])
        if args.command == "cutover":
            result = service.cutover(
                args.migration_id,
                table,
                expected_revision=args.expected_revision,
                reason=args.reason,
            )
        elif args.command == "rollback":
            result = service.rollback_cutover(
                args.migration_id,
                table,
                expected_revision=args.expected_revision,
                reason=args.reason,
            )
        else:
            if args.observation_file is None:
                raise SystemExit("mark-delete-eligible requires --observation-file")
            observation = json.loads(
                args.observation_file.resolve().read_text(encoding="utf-8")
            )
            if not isinstance(observation, dict):
                raise SystemExit("observation file must contain a JSON object")
            result = service.evaluate_delete_eligibility(
                args.migration_id,
                table,
                expected_revision=args.expected_revision,
                observation=observation,
                reason=args.reason,
            )
    elif args.command == "preview-delete-plan":
        if not args.migration_id:
            raise SystemExit("preview-delete-plan requires --migration-id")
        result = service.preview_delete_plan(
            args.migration_id,
            source_tables=list(args.source_table or []),
        )
    else:
        if args.plan_file is None:
            raise SystemExit("validate-delete-plan requires --plan-file")
        plan = json.loads(args.plan_file.resolve().read_text(encoding="utf-8"))
        if not isinstance(plan, dict):
            raise SystemExit("delete plan file must contain a JSON object")
        result = service.validate_delete_plan(plan)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
