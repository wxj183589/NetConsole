"""Explicit production database maintenance boundary.

The command is intentionally fail-closed.  ``preflight`` is read-only;
``execute`` and ``rollback`` require ``--mode production``, the exact
authorization token, a verified owner in the storage registry, and every
production gate set to ``true``.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from uuid import uuid4

from netconsole.core.paths import PathResolver
from netconsole.services.database_footprint_maintenance import assert_development_path
from netconsole.services.production_database_maintenance import (
    PRODUCTION_GATE_KEYS,
    ProductionMaintenanceCapability,
    ProductionRollbackOwner,
    build_exact_manifest,
    write_exact_manifest,
)
from netconsole.services.history_legacy_migration import HistoryLegacyMigrationService


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=(
            "manifest",
            "bootstrap-rollback",
            "promote",
            "orchestrate",
            "preflight",
            "execute",
            "rollback",
        ),
    )
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
    parser.add_argument("--row-identity-json", type=Path)
    parser.add_argument("--mode", default="")
    parser.add_argument("--authorization", default="")
    parser.add_argument("--quiescence-evidence", type=Path)
    parser.add_argument("--restart-evidence", type=Path)
    parser.add_argument("--functional-evidence", type=Path)
    parser.add_argument("--operation-id", default=f"production-maintenance-{uuid4().hex[:12]}")
    parser.add_argument("--gate", action="append", default=[])
    parser.add_argument("--owner-evidence", type=Path)
    parser.add_argument("--history-plan", type=Path)
    parser.add_argument("--history-state", default="")
    parser.add_argument("--task-state", default="")
    parser.add_argument("--retirement-state", default="")
    parser.add_argument("--perform-replace", action="store_true")
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


def _wait_evidence_pass(
    path: Path | None,
    *,
    label: str,
    site_id: str,
    operation_id: str,
    git_head: str,
    timeout_seconds: float = 240.0,
) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while True:
        if _evidence_pass(
            path,
            label=label,
            site_id=site_id,
            operation_id=operation_id,
            git_head=git_head,
        ):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)


def _json_object(path: Path, *, label: str) -> dict[str, object]:
    try:
        value = json.loads(Path(path).resolve().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"cannot read {label}: {path}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"{label} must contain a JSON object")
    return value


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
    if args.owner_evidence is not None:
        owner = ProductionRollbackOwner.from_mapping(
            _json_object(args.owner_evidence, label="rollback owner evidence")
        )
        owners[(owner.site_id, owner.database)] = owner
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
    if args.command == "bootstrap-rollback":
        if args.database is None:
            raise SystemExit("bootstrap-rollback requires --database")
        contract = owners.get((args.site_id, args.database))
        if contract is None:
            raise SystemExit("rollback owner contract is not registered")
        result = capability.bootstrap_rollback(
            args.database,
            owner_contract=contract,
            operation_id=args.operation_id,
            mode=args.mode,
            authorization=args.authorization,
            writer_quiescent=writer_quiescent,
        ).as_dict()
    elif args.command == "promote":
        if args.manifest is None or args.candidate is None:
            raise SystemExit("promote requires --manifest and --candidate")
        manifest_value = _json_object(args.manifest, label="manifest")
        database = str(manifest_value.get("database") or "")
        owner = owners.get((args.site_id, database))
        if owner is None:
            raise SystemExit("VERIFIED rollback owner evidence is required")
        result = capability.promote_executable_manifest(
            args.manifest,
            operation_id=args.operation_id,
            candidate=args.candidate,
            rollback_owner=owner,
            history_state=args.history_state,
            task_state=args.task_state,
            retirement_state=args.retirement_state,
            mode=args.mode,
            authorization=args.authorization,
            writer_quiescent=writer_quiescent,
            gates=gates,
        )
    elif args.command == "orchestrate":
        if args.database is None or args.row_identity_json is None:
            raise SystemExit("orchestrate requires --database and --row-identity-json")
        contract = owners.get((args.site_id, args.database))
        if contract is None:
            raise SystemExit("rollback owner contract is not registered")
        row_identity = _json_object(args.row_identity_json, label="row identity")
        history_plan = None
        migration = None
        if args.database == "devices.db":
            if args.history_plan is None:
                raise SystemExit("devices.db orchestrate requires --history-plan")
            history_plan = _json_object(args.history_plan, label="History retirement plan")
            site = capability._site_and_database(args.database)[1]
            migration = HistoryLegacyMigrationService(
                paths,
                site_id=args.site_id,
                source_database=site.root_path / "db" / "devices.db",
                history_root=site.root_path / "db" / "history",
                diagnostics_dir=paths.migrations_dir / "production-maintenance" / args.operation_id,
            )
        result = capability.execute_cutover_chain(
            args.database,
            operation_id=args.operation_id,
            owner_contract=contract,
            row_identity=row_identity,
            history_migration=migration,
            history_plan=history_plan,
            mode=args.mode,
            authorization=args.authorization,
            writer_quiescent=writer_quiescent,
            gates=gates,
            perform_replace=args.perform_replace,
            restart_verifier=(
                lambda: _wait_evidence_pass(
                    args.restart_evidence,
                    label="production-restart-v1",
                    site_id=args.site_id,
                    operation_id=args.operation_id,
                    git_head=args.git_head,
                )
            ),
            functional_gate=(
                lambda: _wait_evidence_pass(
                    args.functional_evidence,
                    label="production-functional-gate-v1",
                    site_id=args.site_id,
                    operation_id=args.operation_id,
                    git_head=args.git_head,
                )
            ),
        )
    elif args.command == "preflight":
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
            restart_verifier=lambda: _wait_evidence_pass(
                args.restart_evidence,
                label="production-restart-v1",
                site_id=args.site_id,
                operation_id=args.operation_id,
                git_head=args.git_head,
            ),
            functional_gate=lambda: _wait_evidence_pass(
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
