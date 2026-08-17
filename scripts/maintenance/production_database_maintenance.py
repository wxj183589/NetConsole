"""Explicit production database maintenance boundary.

The command is intentionally fail-closed.  ``preflight`` is read-only;
``execute`` and ``rollback`` require ``--mode production``, the exact
authorization token, a verified owner in the storage registry, and every
production gate set to ``true``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import uuid4

from netconsole.core.paths import PathResolver
from netconsole.services.database_footprint_maintenance import assert_development_path
from netconsole.services.production_database_maintenance import (
    PRODUCTION_GATE_KEYS,
    ProductionMaintenanceCapability,
    build_exact_manifest,
    write_exact_manifest,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("manifest", "preflight", "execute", "rollback"))
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--site-id", required=True)
    parser.add_argument("--database")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--rollback", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--registry", type=Path, default=Path("config/storage_registry.yaml"))
    parser.add_argument("--git-head", required=True)
    parser.add_argument("--plan-kind", default="production-database-maintenance")
    parser.add_argument("--expected-count", type=int, default=0)
    parser.add_argument("--row-identity", action="append", default=[])
    parser.add_argument(
        "--row-identity-json",
        help="structured row identity JSON; cannot be combined with --row-identity",
    )
    parser.add_argument("--mode", default="")
    parser.add_argument("--authorization", default="")
    parser.add_argument("--quiescence-evidence", type=Path)
    parser.add_argument("--restart-evidence", type=Path)
    parser.add_argument("--functional-evidence", type=Path)
    parser.add_argument("--operation-id", default=f"production-maintenance-{uuid4().hex[:12]}")
    parser.add_argument("--gate", action="append", default=[])
    return parser


def _gates(values: list[str]) -> dict[str, bool]:
    parsed: dict[str, bool] = {}
    for value in values:
        key, separator, raw = str(value).partition("=")
        if not separator or key not in PRODUCTION_GATE_KEYS or raw.casefold() not in {"true", "false"}:
            raise SystemExit(f"--gate must use known-key=true|false: {value}")
        parsed[key] = raw.casefold() == "true"
    return parsed


def _write_output(path: Path | None, value: object) -> None:
    if path is None:
        return
    target = assert_development_path(path)
    if target.exists():
        raise FileExistsError(f"output already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _evidence_pass(
    path: Path | None,
    *,
    label: str,
    site_id: str,
    operation_id: str,
    git_head: str,
) -> bool:
    if path is None:
        return False
    source = Path(path).resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return bool(
        isinstance(value, dict)
        and str(value.get("evidence_type") or "") == label
        and str(value.get("status") or "") == "PASS"
        and str(value.get("site_id") or "") == site_id
        and str(value.get("operation_id") or "") == operation_id
        and str(value.get("generated_git_head") or "") == git_head
        and str(value.get("verified_at") or "").strip()
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    paths = PathResolver(data_root=args.data_root)
    output = assert_development_path(args.output) if args.output is not None else None
    if output is not None and output.exists():
        raise FileExistsError(f"output already exists: {output}")
    if args.command == "manifest":
        if args.source is None or args.candidate is None or args.manifest is None:
            raise SystemExit("manifest requires --source, --candidate and --manifest")
        manifest_path = assert_development_path(args.manifest)
        if output is not None and output == manifest_path:
            raise SystemExit("--output must differ from --manifest")
        if args.row_identity_json and args.row_identity:
            raise SystemExit(
                "--row-identity-json cannot be combined with --row-identity"
            )
        if args.row_identity_json:
            try:
                parsed_identity = json.loads(args.row_identity_json)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"--row-identity-json is invalid: {exc}") from exc
            if not isinstance(parsed_identity, dict):
                raise SystemExit("--row-identity-json must contain an object")
            row_identity = parsed_identity
        else:
            row_identity: dict[str, str] = {}
            for item in args.row_identity:
                key, separator, value = str(item).partition("=")
                if not separator or not key.strip():
                    raise SystemExit("--row-identity must use key=value")
                row_identity[key.strip()] = value
        value = build_exact_manifest(
            args.source,
            candidate=args.candidate,
            site_id=args.site_id,
            row_identity=row_identity,
            expected_count=args.expected_count,
            generated_git_head=args.git_head,
            plan_kind=args.plan_kind,
        )
        write_exact_manifest(manifest_path, value)
        _write_output(output, value)
        print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    if args.database is None and args.manifest is None:
        raise SystemExit(f"{args.command} requires --database or --manifest")
    owners = ProductionMaintenanceCapability.load_rollback_owners(args.registry)
    capability = ProductionMaintenanceCapability(
        paths,
        site_id=args.site_id,
        authoritative_git_head=args.git_head,
        rollback_owners=owners,
    )
    gates = _gates(args.gate)
    writer_quiescent = _evidence_pass(
        args.quiescence_evidence,
        label="production-writer-quiescence-v1",
        site_id=args.site_id,
        operation_id=args.operation_id,
        git_head=args.git_head,
    )
    if args.command == "preflight":
        if args.manifest is None:
            raise SystemExit("preflight requires --manifest")
        result = capability.preflight(
            args.manifest,
            mode=args.mode,
            writer_quiescent=writer_quiescent,
            gates=gates,
        )
    elif args.command == "execute":
        if args.manifest is None or args.candidate is None or args.rollback is None:
            raise SystemExit("execute requires --manifest, --candidate and --rollback")
        result = capability.execute_replace(
            args.manifest,
            candidate=args.candidate,
            rollback=args.rollback,
            mode=args.mode,
            authorization=args.authorization,
            writer_quiescent=writer_quiescent,
            gates=gates,
            operation_id=args.operation_id,
            restart_verifier=lambda: _evidence_pass(
                args.restart_evidence,
                label="production-restart-v1",
                site_id=args.site_id,
                operation_id=args.operation_id,
                git_head=args.git_head,
            ),
            functional_gate=lambda: _evidence_pass(
                args.functional_evidence,
                label="production-functional-gate-v1",
                site_id=args.site_id,
                operation_id=args.operation_id,
                git_head=args.git_head,
            ),
        )
    else:
        if args.database is None or args.rollback is None:
            raise SystemExit("rollback requires --database and --rollback")
        result = capability.rollback(
            args.database,
            args.rollback,
            mode=args.mode,
            authorization=args.authorization,
            writer_quiescent=writer_quiescent,
            operation_id=args.operation_id,
        )
    _write_output(output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
