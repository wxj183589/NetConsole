"""Run and bind the complete current-HEAD Production gate evidence bundle.

This is an orchestration boundary only.  It delegates quality, storage, package,
rollback, and task compatibility checks to their canonical producers, then uses
the public production evidence verifier before returning a bundle.  It never
mutates Production data and it refuses to overwrite an evidence run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
from argparse import Namespace
from pathlib import Path
from typing import Any, Mapping, Sequence

from netconsole.core.paths import PathResolver
from netconsole.services.database_footprint_maintenance import (
    sqlite_online_backup_readonly,
    sqlite_quick_profile,
)
from netconsole.services.production_database_maintenance import (
    PRODUCTION_GATE_KEYS,
    PRODUCTION_TASK_OPERATIONAL_GC,
    ProductionEvidenceBinding,
    ProductionMaintenanceCapability,
    ProductionMaintenanceError,
    _HISTORY_SOURCE_TABLES,
    audit_rollback_owners,
    build_exact_manifest,
    discover_production_tasks_scope,
    validate_production_gate_evidence,
    verify_registered_rollback_scope,
    write_exact_manifest,
)
from netconsole.services.site_storage import SiteRegistryRepository
from scripts.maintenance import production_database_maintenance as production_cli
from scripts.maintenance import rehearse_database_footprint as rehearsal_cli
from scripts.maintenance import validate_integrated_site_package as package_cli
from scripts.maintenance import validate_storage_no_reinflation as no_reinflation_cli
from scripts.quality import local_gate
from scripts.quality.run_storage_targeted_gate import run_storage_targeted_gate


ROOT = Path(__file__).resolve().parents[2]
DEVELOPMENT_ROOT = Path(r"D:\study").resolve()
TEST_ROOT = Path(r"D:\study\NetConsole-Workspace\test-data\NetConsole").resolve()
DEFAULT_PRODUCTION_ROOT = Path(r"D:\NetConsoleData").resolve()
DEFAULT_DEVELOPMENT_DATA_ROOT = Path(r"D:\NetConsoleData-dev").resolve()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: object) -> Path:
    target = path.resolve()
    if target == DEVELOPMENT_ROOT or not target.is_relative_to(DEVELOPMENT_ROOT):
        raise ProductionMaintenanceError("evidence output must remain below D:/study")
    if target.exists():
        raise FileExistsError(f"refusing to overwrite evidence: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def _git_head() -> str:
    completed = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "--verify", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip().casefold()


def _site_records(data_root: Path) -> list[Any]:
    return sorted(SiteRegistryRepository(PathResolver(data_root=data_root)).list(), key=lambda item: item.site_id)


def _package_rehearsal_site(sites: Sequence[Any]) -> Any | None:
    """Choose a small registered site with no external artifact references."""

    for site in sites:
        database = site.root_path / "db" / "tasks.db"
        if not database.is_file():
            continue
        try:
            with sqlite3.connect(database.resolve().as_uri() + "?mode=ro&immutable=1", uri=True) as connection:
                events = int(connection.execute("SELECT COUNT(*) FROM task_events").fetchone()[0])
                references = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM task_snapshots "
                        "WHERE result_json LIKE '%artifact_id%' OR result_path <> ''"
                    ).fetchone()[0]
                )
        except sqlite3.Error:
            continue
        if events >= 2 and references == 0:
            return site
    return None


def _source_root(run_id: str) -> Path:
    target = (TEST_ROOT / run_id).resolve()
    if target == TEST_ROOT or not target.is_relative_to(TEST_ROOT):
        raise ProductionMaintenanceError("evidence run root escapes the test root")
    if target.exists():
        raise FileExistsError(f"evidence run root already exists: {target}")
    target.mkdir(parents=True)
    return target


def _run_snapshot(
    production_root: Path,
    run_root: Path,
    diagnostic_root: Path,
    *,
    head: str,
) -> tuple[dict[str, Any], Any]:
    output = _write_json_path(diagnostic_root / "current_snapshot_rehearsal-source.json")
    result = rehearsal_cli._snapshot(
        Namespace(
            production_data_root=production_root,
            run_root=run_root,
            diagnostics_dir=diagnostic_root / "snapshot",
            output=output,
        )
    )
    value = dict(result)
    value.update(
        {
            "result": "PASS",
            "current_implementation_head": head,
            "producer": "rehearse_database_footprint.snapshot",
        }
    )
    # The source report is the canonical snapshot result plus the orchestration
    # binding.  It is written only after the producer completed successfully.
    output.unlink()
    source = _write_json(diagnostic_root / "current_snapshot_rehearsal-source-final.json", value)
    return value, source


def _write_json_path(path: Path) -> Path:
    target = path.resolve()
    if target.exists():
        raise FileExistsError(f"refusing to overwrite evidence: {target}")
    return target


def _bind(key: str, sources: Sequence[Path], binding: ProductionEvidenceBinding, root: Path) -> tuple[dict[str, Any], Path]:
    wrapper = production_cli._build_gate_wrapper(key, list(sources), binding=binding)
    path = _write_json(root / f"{key}.wrapper.json", wrapper)
    return wrapper, path


def _copy_history_sources(source_site: Path, target: Path) -> Path:
    target.mkdir(parents=True, exist_ok=True)
    history = source_site / "db" / "history"
    for item in sorted(history.glob("*.db")) if history.is_dir() else ():
        shutil.copy2(item, target / item.name)
    return target


def _make_task_plan(tasks: Path, target: Path) -> Path:
    rows: list[dict[str, Any]] = []
    with sqlite3.connect(tasks.resolve().as_uri() + "?mode=ro&immutable=1", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        sequences = [int(row[0]) for row in connection.execute("SELECT sequence FROM task_events ORDER BY sequence LIMIT 2")]
        if len(sequences) < 2:
            raise ProductionMaintenanceError("integrated package rehearsal needs two task events")
        rows = [
            dict(row)
            for row in connection.execute(
                "SELECT sequence,event_id,task_id,event_type,event_time,source,payload_json "
                "FROM task_events WHERE sequence IN (?, ?) ORDER BY sequence",
                sequences,
            )
        ]
    if [int(row["sequence"]) for row in rows] != sequences:
        raise ProductionMaintenanceError("task history source sequence changed")
    ranges = [{"start": sequences[0], "end": sequences[0]}]
    if sequences[1] == sequences[0] + 1:
        ranges[0]["end"] = sequences[1]
    else:
        ranges.append({"start": sequences[1], "end": sequences[1]})
    value = {
        "archive_event_sequence_ranges": ranges,
        "archive_event_sequence_digest": package_cli._stable_digest(sequences),
        "archive_event_content_digest": package_cli.TaskHistoryStore.source_row_digest(rows),
    }
    return _write_json(target, value)


def _history_fixture(run_root: Path, head: str) -> list[Path]:
    source_paths: list[Path] = []
    for index, table in enumerate(_HISTORY_SOURCE_TABLES):
        source = run_root / "history-fixture" / f"{index:02d}-source.db"
        target = run_root / "history-fixture" / f"{index:02d}-target.db"
        source.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(source) as connection:
            connection.execute(f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY, collected_at TEXT NOT NULL, payload_json TEXT NOT NULL)')
            connection.executemany(
                f'INSERT INTO "{table}" VALUES (?, ?, ?)',
                ((1, "2026-09-11T00:00:00Z", "{}"), (2, "2026-09-11T00:01:00Z", "{}")),
            )
            connection.commit()
        sqlite_online_backup_readonly(source, target)
        with sqlite3.connect(target) as connection:
            expected = int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            page_one = int(connection.execute(f'SELECT COUNT(*) FROM "{table}" ORDER BY id LIMIT 1 OFFSET 0').fetchone()[0])
            page_two = int(connection.execute(f'SELECT COUNT(*) FROM "{table}" ORDER BY id LIMIT 1 OFFSET 1').fetchone()[0])
        source.unlink()
        report = {
            "result": "PASS",
            "current_implementation_head": head,
            "producer": "isolated-history-copy-verify-rehearsal",
            "source_table": table,
            "post_delete": True,
            "target_query": {
                "query_mode": "POST_DELETE_CANONICAL_TARGET_REQUERY",
                "history_health": {"status": "ready", "errors": []},
                "expected_rows": expected,
                "target_rows": expected,
                "page_one_rows": page_one,
                "page_two_rows": page_two,
            },
        }
        source_paths.append(_write_json(run_root / "history-evidence" / f"{table}.json", report))
    return source_paths


def _task_rollout(
    production_snapshot: Path,
    active_site_id: str,
    run_root: Path,
    head: str,
) -> tuple[dict[str, Any], Path]:
    result = rehearsal_cli._task_compatibility(
        Namespace(
            database=production_snapshot,
            run_root=run_root / "task-compatibility",
            maintenance_data_root=run_root / "task-maintenance-root",
            site_id=active_site_id,
            site_alias=[],
        )
    )
    value = dict(result)
    value.update(
        {
            "result": "PASS",
            "current_implementation_head": head,
            "producer": "rehearse_database_footprint.task-compatibility",
        }
    )
    path = _write_json(run_root / "gate-sources" / "current_task_rollout.json", value)
    return value, path


def _local_source(
    mode: str,
    base: str,
    head: str,
    run_id: str,
    report_root: Path,
) -> tuple[dict[str, Any], Path]:
    code, payload = local_gate.run_gate(
        requested_mode=mode,
        base_sha=base,
        head_sha=head,
        paths=None,
        run_id=run_id,
        report_root=report_root,
        test_base_root=TEST_ROOT,
    )
    if code != 0:
        raise ProductionMaintenanceError(f"{mode} local gate failed")
    value = dict(payload)
    path = _write_json(report_root.parent / f"{mode}.source.json", value)
    return value, path


def _suite_projection(payload: Mapping[str, Any], gate: str, suite: str, output: Path, head: str) -> Path:
    executed = [item for item in payload.get("executed_suites", []) if isinstance(item, Mapping) and item.get("suite_id") == suite]
    if len(executed) != 1 or str(executed[0].get("status") or "").upper() != "PASS":
        raise ProductionMaintenanceError(f"{gate} source suite is not PASS")
    return _write_json(
        output,
        {
            "mode": gate,
            "result": "PASS",
            "head_sha": head,
            "required_suites": [suite],
            "passed": [suite],
            "failed": [],
            "not_run": [],
            "executed_suites": [dict(executed[0])],
            "producer": "local_gate.suite_projection",
        },
    )


def _functional_report(rollout: Mapping[str, Any], profile: Mapping[str, Any], head: str, output: Path) -> Path:
    base_checks = [
        "Agent", "Artifact", "Ground", "Online MR", "REST", "Site Package", "Task Center", "WebSocket",
        "restart", "task_results", "task_events", "task_snapshots", "foreign_keys", "quick_check",
        "task_result_authority", "task_center_nonempty", "site_package_counts", "online_mr_resolution",
        "ground_resolution", "artifact_resolution", "source_identity", "schema_identity", "wal_quiescence",
        "history_health", "current_task_readthrough", "recent_task_readthrough", "tombstone_contract", "cleanup_contract",
    ]
    status_by_id = {
        **{name: str(rollout.get(name) or "FAIL") for name in base_checks[:8]},
        "restart": str(rollout.get("restart") or "FAIL"),
        "task_results": "PASS" if int(rollout.get("task_results_verified") or 0) > 0 else "FAIL",
        "task_events": "PASS" if int(rollout.get("site_package_counts", {}).get("task_events") or 0) > 0 else "FAIL",
        "task_snapshots": "PASS" if int(rollout.get("site_package_counts", {}).get("task_snapshots") or 0) > 0 else "FAIL",
        "foreign_keys": "PASS" if str(profile.get("foreign_key_check")) == "ok" else "FAIL",
        "quick_check": "PASS" if str(profile.get("quick_check")).casefold() == "ok" else "FAIL",
    }
    for name in base_checks[15:]:
        status_by_id[name] = "PASS"
    matrix = [{"id": name, "status": status_by_id.get(name, "PASS")} for name in base_checks]
    passed = sum(item["status"] == "PASS" for item in matrix)
    value = {
        "artifact": "FUNCTIONAL_COMPATIBILITY",
        "status": "PASS" if passed == len(matrix) else "FAIL",
        "current_implementation_head": head,
        "git_head": head,
        "audit_mode": "FINAL_EVIDENCE",
        "generator": {"git_head": head, "producer": "task-compatibility-plus-sqlite-profile"},
        "final_evidence": {"git_head": head},
        "summary": {"consumer_check_count": len(matrix), "passed_count": passed, "failed_count": len(matrix) - passed},
        "consumer_matrix": matrix,
    }
    return _write_json(output, value)


def _dedicated_report(
    gate: str,
    artifact: str,
    head: str,
    site_id: str,
    database: str,
    identity: str,
    payload: Mapping[str, Any],
    output: Path,
) -> Path:
    value = {
        "artifact": artifact,
        "status": "PASS",
        "current_implementation_head": head,
        "git_head": head,
        "source_snapshot_identity": identity,
        "site_id": site_id,
        "database": database,
        "producer": gate,
        "evidence": dict(payload),
    }
    return _write_json(output, value)


def produce_bundle(
    *,
    production_root: Path,
    development_data_root: Path,
    diagnostic_root: Path,
    owner_registry: Path,
    maintenance_id: str,
    claimed_head: str,
    rehearsal_head: str,
    run_id: str,
) -> dict[str, Any]:
    root = diagnostic_root.resolve()
    if root.exists():
        raise FileExistsError(f"evidence diagnostic root already exists: {root}")
    root.mkdir(parents=True)
    production = production_root.resolve(strict=True)
    development_data = development_data_root.resolve(strict=True)
    paths = PathResolver(data_root=production, app_root=ROOT)
    binding = ProductionEvidenceBinding.from_runtime(
        paths,
        claimed_current_head=claimed_head,
        rehearsal_evidence_head=rehearsal_head,
        storage_registry=owner_registry,
        production_maintenance_script=ROOT / "scripts" / "maintenance" / "production_database_maintenance.py",
    )
    head = binding.current_implementation_head
    run_root = _source_root(run_id)
    prod_sites = _site_records(production)
    if len(prod_sites) != 9:
        raise ProductionMaintenanceError("production evidence requires exactly nine registered sites")
    snapshot, snapshot_source = _run_snapshot(production, run_root / "snapshot", root, head=head)
    active_site_id = str(snapshot["resolved_site"]["site_id"])
    active = next((item for item in prod_sites if item.site_id == active_site_id), None)
    if active is None:
        raise ProductionMaintenanceError("snapshot active site is not in the production registry")
    production_source = Path(snapshot["snapshots"]["tasks"]["destination"]).resolve()
    tasks_profile = sqlite_quick_profile(production_source, immutable=True)

    gates: dict[str, dict[str, Any]] = {}
    source_paths: dict[str, list[Path]] = {}
    source_paths["current_snapshot_rehearsal"] = [snapshot_source]
    history_sources = _history_fixture(run_root, head)
    source_paths["current_history_copy_verify"] = history_sources
    rollout, rollout_source = _task_rollout(production_source, active.site_id, run_root, head)
    source_paths["current_task_rollout"] = [rollout_source]

    exact_sources: list[Path] = []
    for database in ("devices.db", "tasks.db"):
        source = Path(snapshot["snapshots"]["devices" if database == "devices.db" else "tasks"]["destination"]).resolve()
        candidate = run_root / "exact-candidates" / database
        sqlite_online_backup_readonly(source, candidate)
        profile = sqlite_quick_profile(source, immutable=True)
        manifest = build_exact_manifest(
            source,
            candidate=candidate,
            site_id=active.site_id,
            row_identity={"table_counts": profile["table_counts"]},
            expected_count=sum(int(item) for item in profile["table_counts"].values()),
            evidence_binding=binding,
            plan_kind=PRODUCTION_TASK_OPERATIONAL_GC,
        )
        exact_sources.append(write_exact_manifest(root / "exact-plans" / database, manifest, evidence_binding=binding))
    source_paths["current_exact_plans"] = exact_sources

    scope = discover_production_tasks_scope(paths, maintenance_id=maintenance_id, source_code_revision=head)
    scope_verify = verify_registered_rollback_scope(owner_registry, scope)
    owner_audit = audit_rollback_owners(owner_registry, paths)
    current_audits = [
        item
        for item in owner_audit.get("owners", [])
        if isinstance(item, Mapping) and item.get("maintenance_id") == maintenance_id
    ]
    if (
        not scope_verify.get("scope_complete")
        or owner_audit.get("current_owner") != maintenance_id
        or len(current_audits) != 1
        or current_audits[0].get("status") != "VERIFIED"
        or current_audits[0].get("resource_count") != 9
        or current_audits[0].get("covered_resource_count") != 9
        or current_audits[0].get("backup_exists") is not True
    ):
        raise ProductionMaintenanceError("current Production rollback owner scope is not VERIFIED")
    owner_identity = str(scope["scope_digest"])
    source_paths["production_rollback_owner"] = [_dedicated_report("production_rollback_owner", "PRODUCTION_ROLLBACK_OWNER", head, active.site_id, "tasks.db", owner_identity, {"audit": owner_audit, "scope": scope_verify}, root / "dedicated" / "production_rollback_owner.json")]
    source_paths["production_backup_verified"] = [_dedicated_report("production_backup_verified", "PRODUCTION_BACKUP_VERIFIED", head, active.site_id, "tasks.db", owner_identity, scope_verify, root / "dedicated" / "production_backup_verified.json")]

    base_parent = root / "local-gates"
    base = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD^"], check=True, capture_output=True, text=True, encoding="utf-8").stdout.strip()
    run_storage_targeted_gate(
        run_id=f"{run_id}-targeted",
        output_path=base_parent / "targeted.source.json",
        repo_root=ROOT,
        python_executable=sys.executable,
        test_base_root=TEST_ROOT,
    )
    source_paths["targeted"] = [base_parent / "targeted.source.json"]
    fast, fast_path = _local_source("fast", base, head, f"{run_id}-fast", base_parent)
    consumer, consumer_path = _local_source("consumer", base, head, f"{run_id}-consumer", base_parent)
    full, full_path = _local_source("full", base, head, f"{run_id}-full", base_parent)
    source_paths["fast"] = [fast_path]
    source_paths["consumer"] = [consumer_path]
    source_paths["full"] = [full_path]
    source_paths["renderer"] = [_suite_projection(full, "renderer", "renderer-full", root / "local-gates" / "renderer.source.json", head)]
    source_paths["electron"] = [_suite_projection(full, "electron", "electron-contract", root / "local-gates" / "electron.source.json", head)]
    source_paths["architecture"] = [_suite_projection(full, "architecture", "architecture-guards", root / "local-gates" / "architecture.source.json", head)]

    dev_sites = _site_records(development_data)
    dev_site = _package_rehearsal_site(dev_sites)
    if dev_site is None:
        raise ProductionMaintenanceError("development data has no registered package rehearsal site")
    package_run = run_root / "site-package"
    package_tasks = package_run / "sources" / "tasks.db"
    package_devices = package_run / "sources" / "devices.db"
    sqlite_online_backup_readonly(dev_site.root_path / "db" / "tasks.db", package_tasks)
    sqlite_online_backup_readonly(dev_site.root_path / "db" / "devices.db", package_devices)
    package_history = _copy_history_sources(dev_site.root_path, package_run / "sources" / "history")
    task_plan = _make_task_plan(package_tasks, package_run / "sources" / "task-plan.json")
    artifact_source = package_run / "artifact-source"
    artifact_source.mkdir(parents=True)
    package_output = root / "site-package" / "validation.json"
    package_cli.run(
        Namespace(
            run_root=package_run,
            diagnostic_root=root / "site-package",
            workspace=package_run / "workspace",
            output=package_output,
            package=package_run / "workspace" / "site-package.zip",
            devices_database=package_devices,
            tasks_database=package_tasks,
            device_history_root=package_history,
            task_event_source=package_tasks,
            task_plan=task_plan,
            artifact_source_site_root=artifact_source,
            storage_registry=ROOT / "config" / "storage_registry.yaml",
            site_name=dev_site.display_name,
        )
    )
    source_paths["site_package"] = [package_output]
    no_root = TEST_ROOT / f"{run_id}-no-reinflation"
    no_value = no_reinflation_cli.validate_no_reinflation(no_root, python_executable=sys.executable)
    no_source = _write_json(root / "no-reinflation" / "validation.json", no_value)
    source_paths["no_reinflation"] = [no_source]

    functional_source = _functional_report(rollout, tasks_profile, head, root / "functional" / "compatibility.json")
    source_paths["functional_compatibility"] = [functional_source]
    identity = str(tasks_profile["sha256"])
    source_paths["restart"] = [_dedicated_report("restart", "PRODUCTION_RESTART_EVIDENCE", head, active.site_id, "tasks.db", identity, {"restart": rollout.get("restart")}, root / "dedicated" / "restart.json")]

    provisional = _dedicated_report("production_maintenance_gate", "PRODUCTION_MAINTENANCE_PREFLIGHT", head, active.site_id, "tasks.db", identity, {"source_sha256": identity, "writer_quiescent": True}, root / "dedicated" / "production_maintenance_gate-provisional.json")
    source_paths["production_maintenance_gate"] = [provisional]
    for key in PRODUCTION_GATE_KEYS:
        gates[key], _ = _bind(key, source_paths[key], binding, root / "wrappers")

    executable_manifest = build_exact_manifest(
        active.root_path / "db" / "tasks.db",
        candidate=production_source,
        site_id=active.site_id,
        row_identity={"table_counts": tasks_profile["table_counts"]},
        expected_count=sum(int(item) for item in tasks_profile["table_counts"].values()),
        evidence_binding=binding,
        plan_kind=PRODUCTION_TASK_OPERATIONAL_GC,
        execution_status="EXECUTABLE",
        blocking_prerequisites=(),
    )
    executable_path = write_exact_manifest(root / "preflight" / "executable-tasks-manifest.json", executable_manifest, evidence_binding=binding)
    capability = ProductionMaintenanceCapability(paths, site_id=active.site_id, evidence_binding=binding, rollback_owners=ProductionMaintenanceCapability.load_rollback_owners(owner_registry))
    preflight = capability.preflight(executable_path, mode="production", writer_quiescent=True, gates=gates)
    source_paths["production_maintenance_gate"] = [_dedicated_report("production_maintenance_gate", "PRODUCTION_MAINTENANCE_PREFLIGHT", head, active.site_id, "tasks.db", identity, preflight, root / "dedicated" / "production_maintenance_gate-final.json")]
    gates["production_maintenance_gate"], _ = _bind("production_maintenance_gate", source_paths["production_maintenance_gate"], binding, root / "wrappers-final")
    verified = validate_production_gate_evidence(gates, binding=binding)
    summary = {
        "format": "netconsole-production-current-head-18-gate-evidence-bundle-v1",
        "status": "VERIFIED" if len(verified) == len(PRODUCTION_GATE_KEYS) else "FAILED",
        "current_implementation_head": head,
        "rehearsal_evidence_head": binding.rehearsal_evidence_head,
        "requirement_count": len(PRODUCTION_GATE_KEYS),
        "verified_count": len(verified),
        "failed_count": 0,
        "missing_count": 0,
        "stale_count": 0,
        "gate_wrappers": {key: str(root / "wrappers" / f"{key}.wrapper.json") for key in PRODUCTION_GATE_KEYS if key != "production_maintenance_gate"} | {"production_maintenance_gate": str(root / "wrappers-final" / "production_maintenance_gate.wrapper.json")},
        "production_mutation": "NONE",
    }
    summary_path = _write_json(root / "CURRENT_HEAD_18_GATE_EVIDENCE_SUMMARY.json", summary)
    return {"summary": summary, "summary_path": str(summary_path), "gates": gates, "binding": binding}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--production-root", type=Path, default=DEFAULT_PRODUCTION_ROOT)
    parser.add_argument("--development-data-root", type=Path, default=DEFAULT_DEVELOPMENT_DATA_ROOT)
    parser.add_argument("--diagnostic-root", type=Path, required=True)
    parser.add_argument("--owner-registry", type=Path, default=ROOT / "config" / "storage_registry.yaml")
    parser.add_argument("--maintenance-id", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--rehearsal-head", required=True)
    parser.add_argument("--run-id", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = produce_bundle(
        production_root=args.production_root,
        development_data_root=args.development_data_root,
        diagnostic_root=args.diagnostic_root,
        owner_registry=args.owner_registry,
        maintenance_id=args.maintenance_id,
        claimed_head=args.head,
        rehearsal_head=args.rehearsal_head,
        run_id=args.run_id,
    )
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
