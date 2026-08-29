"""Inspect or explicitly change one site's task result storage rollout."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from netconsole.core.runtime_environment import require_data_root_write_allowed
from netconsole.core.paths import PathResolver
from netconsole.services.job_center.task_result_rollout import (
    TaskResultRolloutError,
    TaskResultRolloutService,
)
from netconsole.services.site_storage import SiteRegistryRepository


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
    return parser


def _service(args: argparse.Namespace) -> TaskResultRolloutService:
    paths = PathResolver(data_root=args.data_root)
    site = SiteRegistryRepository(paths).get(args.site_id)
    return TaskResultRolloutService(site.root_path / "db" / "tasks.db")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "enable-dual-write" and args.apply:
        raise SystemExit(
            "TASK_RESULT_RUNTIME_ROLLOUT_DISABLED: current runtime writer "
            "is fixed at LEGACY_DUAL_FULL; enable-dual-write is not an "
            "effective production operation"
        )
    service = _service(args)
    if args.command == "status":
        result = service.status()
    else:
        if not args.apply:
            raise SystemExit("rollout transitions require explicit --apply")
        require_data_root_write_allowed(
            args.data_root,
            "manage_task_result_rollout",
            allow_production_write=args.allow_production_write,
        )
        if args.expected_revision is None or not args.reason.strip():
            raise SystemExit(
                "rollout transitions require --expected-revision and --reason"
            )
        try:
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
