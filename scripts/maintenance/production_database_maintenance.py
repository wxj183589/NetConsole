"""Explicit production database maintenance boundary.

The command is intentionally fail-closed.  ``preflight`` is read-only;
``execute`` and ``rollback`` require ``--mode production``, the exact
authorization token, a verified owner in the storage registry, and every
production gate backed by current-HEAD PASS evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from netconsole.core.paths import PathResolver
from netconsole.services.database_footprint_maintenance import assert_development_path
from netconsole.services.production_database_maintenance import (
    PRODUCTION_GATE_KEYS,
    ProductionEvidenceBinding,
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
    parser.add_argument("--rehearsal-evidence-head", required=True)
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
    parser.add_argument("--gate-evidence", type=Path, action="append", default=[])
    return parser


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _gate_evidence(
    paths: list[Path],
    *,
    binding: ProductionEvidenceBinding,
) -> dict[str, dict[str, str]]:
    parsed: dict[str, dict[str, str]] = {}
    for raw_path in paths:
        source = assert_development_path(raw_path)
        if not source.is_file():
            raise SystemExit(f"production gate evidence is not a file: {source}")
        try:
            value = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SystemExit(f"invalid production gate evidence: {source}") from exc
        if not isinstance(value, dict):
            raise SystemExit(f"production gate evidence must be an object: {source}")
        key = str(value.get("gate") or "")
        if key not in PRODUCTION_GATE_KEYS or key in parsed:
            raise SystemExit(f"unknown or duplicate production gate evidence: {key}")
        if (
            str(value.get("evidence_type") or "")
            != "production-current-head-gate-v1"
            or str(value.get("status") or "") != "PASS"
            or str(value.get("current_implementation_head") or "").casefold()
            != binding.current_implementation_head
            or str(value.get("rehearsal_evidence_head") or "").casefold()
            != binding.rehearsal_evidence_head
            or not str(value.get("verified_at") or "").strip()
        ):
            raise SystemExit(f"production gate evidence is not current-HEAD PASS: {key}")
        parsed[key] = {
            "status": "PASS",
            "current_implementation_head": binding.current_implementation_head,
            "evidence_sha256": _sha256_file(source),
        }
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
    binding: ProductionEvidenceBinding,
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
        and str(value.get("current_implementation_head") or "").casefold()
        == binding.current_implementation_head
        and str(value.get("rehearsal_evidence_head") or "").casefold()
        == binding.rehearsal_evidence_head
        and str(value.get("verified_at") or "").strip()
        and (
            label != "production-writer-quiescence-v1"
            or all(
                value.get(key) is True
                for key in (
                    "runtime_writer_stopped",
                    "database_owner_inactive",
                    "wal_zero",
                    "sqlite_sidecars_quiescent",
                )
            )
        )
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    paths = PathResolver(data_root=args.data_root)
    binding = ProductionEvidenceBinding.from_runtime(
        paths,
        claimed_current_head=args.git_head,
        rehearsal_evidence_head=args.rehearsal_evidence_head,
        storage_registry=args.registry,
        production_maintenance_script=Path(__file__),
    )
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
            evidence_binding=binding,
            plan_kind=args.plan_kind,
        )
        binding.assert_current(paths)
        write_exact_manifest(
            manifest_path,
            value,
            evidence_binding=binding,
        )
        _write_output(output, value)
        print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    if args.database is None and args.manifest is None:
        raise SystemExit(f"{args.command} requires --database or --manifest")
    owners = ProductionMaintenanceCapability.load_rollback_owners(args.registry)
    capability = ProductionMaintenanceCapability(
        paths,
        site_id=args.site_id,
        evidence_binding=binding,
        rollback_owners=owners,
    )
    gates = _gate_evidence(args.gate_evidence, binding=binding)
    writer_quiescent = _evidence_pass(
        args.quiescence_evidence,
        label="production-writer-quiescence-v1",
        site_id=args.site_id,
        operation_id=args.operation_id,
        binding=binding,
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
                binding=binding,
            ),
            functional_gate=lambda: _evidence_pass(
                args.functional_evidence,
                label="production-functional-gate-v1",
                site_id=args.site_id,
                operation_id=args.operation_id,
                binding=binding,
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
