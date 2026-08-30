"""Explicit maintenance CLI for COPY-only legacy device history migration."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from netconsole.core.runtime_environment import require_data_root_write_allowed
from netconsole.core.paths import PathResolver
from netconsole.services.history_legacy_migration import HistoryLegacyMigrationService
from netconsole.services.site_storage import SiteRegistryRepository


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("inventory", "start", "pause", "resume", "status"))
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--site-id", required=True)
    parser.add_argument("--source-db", type=Path)
    parser.add_argument("--history-root", type=Path)
    parser.add_argument("--diagnostics-dir", type=Path)
    parser.add_argument("--migration-id")
    parser.add_argument("--chunk-rows", type=int, default=250, choices=(100, 250, 500))
    parser.add_argument("--max-elapsed-seconds", type=float, default=2.0)
    parser.add_argument("--slow-storage-delay-seconds", type=float, default=0.0)
    parser.add_argument("--immutable-source", action="store_true")
    parser.add_argument("--unattended-active", action="store_true")
    parser.add_argument("--light", action="store_true", help="skip exact COUNT/MIN/MAX inventory queries")
    parser.add_argument("--apply", action="store_true", help="required for start/resume")
    parser.add_argument(
        "--allow-production-write",
        action="store_true",
        help="明确授权对 production 数据根执行历史迁移",
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
        or Path("D:/study/NetConsole-Workspace/diagnostic/device-history-migration") / run_id
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
    if args.command in {"start", "resume"}:
        require_data_root_write_allowed(
            args.data_root,
            "migrate_device_history",
            allow_production_write=args.allow_production_write,
        )
    service = _service(args)
    if args.command in {"start", "resume"} and not args.apply:
        raise SystemExit("start/resume require explicit --apply; source deletion is not implemented")
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
    else:
        if not args.migration_id:
            raise SystemExit("status requires --migration-id")
        result = service.status(args.migration_id)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
