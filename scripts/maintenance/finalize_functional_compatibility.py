"""Bind complete database functional-compatibility evidence to one final Git HEAD."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


DEFAULT_DEVELOPMENT_ROOT = Path("D:/study")
OUTPUT_FILENAMES = (
    "FUNCTIONAL_BASELINE.json",
    "FUNCTIONAL_AFTER.json",
    "FUNCTIONAL_COMPATIBILITY.json",
)
CORE_CHECKS = frozenset(
    {
        "devices.current_business_tables",
        "tasks.auxiliary_business_tables",
        "tasks.repository_transparent_read",
        "history.migration_and_post_replace_parity",
    }
)
NO_REINFLATION_SCENARIOS = frozenset(
    {
        "task_progress_and_result",
        "ground_current_state",
        "online_mr_raw_authority",
        "ground_ping_syslog_raw_growth",
        "device_lldp_ap_state",
        "mesh_source_and_reparse",
        "site_package_staging",
        "backup_same_revision",
    }
)
PERFORMANCE_CASES = frozenset(
    {
        "current_device_query",
        "fit_ap_query",
        "lldp_query",
        "history_range_query",
        "cross_shard_history_query",
        "task_center_list",
        "task_detail",
        "mr_mesh_history",
        "ground_history",
    }
)
GATE_SUITES = {
    "targeted": frozenset({"storage-targeted"}),
    "fast": frozenset(
        {
            "change-impact",
            "ruff-changed",
            "python-direct",
            "renderer-direct",
            "electron-direct",
            "architecture-targeted",
            "git-diff-check",
        }
    ),
    "consumer": frozenset(
        {
            "renderer-full",
            "python-full",
            "electron-contract",
            "architecture-guards",
            "main-contract-smoke",
        }
    ),
    "full": frozenset(
        {
            "renderer-full",
            "python-full",
            "electron-contract",
            "architecture-guards",
            "main-contract-smoke",
            "ruff-full",
            "docs-path-guards",
            "git-diff-check",
        }
    ),
}

MATRIX_DEFINITIONS: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "Device Management",
        ("devices.current_business_tables",),
        ("tests/test_device_management_web_api.py",),
    ),
    (
        "Interfaces",
        ("devices.current_business_tables",),
        ("tests/test_device_detail_query_service.py",),
    ),
    (
        "LLDP",
        ("devices.current_business_tables",),
        ("tests/test_device_detail_query_service.py",),
    ),
    (
        "Optical",
        ("devices.current_business_tables",),
        ("tests/test_device_detail_query_service.py",),
    ),
    (
        "FIT-AP",
        ("devices.current_business_tables",),
        ("tests/test_ac_management_web_api.py",),
    ),
    (
        "FIT-AP Radio",
        ("devices.current_business_tables",),
        ("tests/test_ac_management_query_service.py",),
    ),
    (
        "Trackside AP",
        ("devices.current_business_tables",),
        ("tests/test_trackside_ap_business_snapshot.py",),
    ),
    (
        "AP Identity",
        ("devices.current_business_tables",),
        ("tests/test_ap_identity_index.py",),
    ),
    (
        "Rail Base Data",
        ("devices.current_business_tables",),
        ("tests/test_rail_transit_base_data_query_service.py",),
    ),
    (
        "History",
        (
            "devices.current_business_tables",
            "history.migration_and_post_replace_parity",
        ),
        ("tests/test_history_store.py",),
    ),
    (
        "Task Center",
        ("tasks.auxiliary_business_tables", "tasks.repository_transparent_read"),
        ("tests/test_job_center_web_api.py",),
    ),
    (
        "REST",
        ("devices.current_business_tables", "tasks.repository_transparent_read"),
        ("scripts/quality/run_main_contract_smoke.py",),
    ),
    (
        "WebSocket",
        ("tasks.repository_transparent_read",),
        ("tests/test_job_center_web_api.py",),
    ),
    (
        "Agent",
        ("tasks.repository_transparent_read",),
        ("tests/test_agent_controller.py", "apps/agent/internal/api/server_test.go"),
    ),
    (
        "Online MR",
        ("tasks.repository_transparent_read",),
        ("tests/test_online_mr_application_service.py",),
    ),
    (
        "Ground",
        ("tasks.repository_transparent_read",),
        ("tests/test_ground_unattended_api.py",),
    ),
    (
        "MR Collection",
        ("tasks.repository_transparent_read",),
        ("tests/test_online_mr_collection.py",),
    ),
    ("MR Raw Import", (), ("tests/test_online_mr_agent_package_importer.py",)),
    (
        "MESH Analysis",
        (),
        ("tests/test_mesh_analysis_web_api.py", "tests/test_mesh_log_analysis.py"),
    ),
    ("RSSI / Link / Switch", (), ("tests/test_mesh_log_analysis.py",)),
    ("Ping", (), ("tests/test_ground_unattended_fleet_ping.py",)),
    ("Syslog", (), ("tests/test_ground_unattended_syslog_field_validation.py",)),
    (
        "Artifact",
        ("tasks.repository_transparent_read",),
        ("tests/test_artifact_reconciliation.py",),
    ),
    ("Import", (), ("tests/test_integrated_site_package_validation.py",)),
    ("Export", (), ("tests/test_export_process_framework.py",)),
    ("Site Package", (), ("tests/test_integrated_site_package_validation.py",)),
    (
        "Restart Recovery",
        (
            "history.migration_and_post_replace_parity",
            "tasks.repository_transparent_read",
        ),
        ("tests/test_integrated_site_package_validation.py",),
    ),
    ("Performance Regression", (), ("DATABASE_PERFORMANCE.json",)),
    ("No-Reinflation", (), ("tests/test_storage_no_reinflation.py",)),
)


class FunctionalFinalizationError(ValueError):
    """Raised when one final functional-compatibility prerequisite is incomplete."""


def finalize_functional_compatibility(
    *,
    baseline_path: Path,
    after_path: Path,
    compatibility_path: Path,
    site_package_path: Path,
    no_reinflation_path: Path,
    performance_path: Path,
    storage_footprint_path: Path,
    gate_paths: Sequence[Path],
    output_dir: Path,
    repo_root: Path | None = None,
    development_root: Path = DEFAULT_DEVELOPMENT_ROOT,
    overwrite: bool = False,
) -> dict[str, Path]:
    root = (repo_root or Path(__file__).resolve().parents[2]).resolve(strict=True)
    head = _git_head(root)
    _validate_matrix_test_ids(root)
    development = development_root.resolve(strict=True)
    inputs = {
        "baseline": _input_file(baseline_path, development),
        "after": _input_file(after_path, development),
        "compatibility": _input_file(compatibility_path, development),
        "site_package": _input_file(site_package_path, development),
        "no_reinflation": _input_file(no_reinflation_path, development),
        "performance": _input_file(performance_path, development),
        "storage_footprint": _input_file(storage_footprint_path, development),
    }
    gates = [_input_file(path, development) for path in gate_paths]
    destination = _output_directory(output_dir, development)
    output_paths = {name: destination / name for name in OUTPUT_FILENAMES}
    existing = [path.name for path in output_paths.values() if path.exists()]
    if existing and not overwrite:
        raise FunctionalFinalizationError(
            "refusing to overwrite final functional outputs: "
            + ", ".join(sorted(existing))
        )

    baseline = _load_object(inputs["baseline"])
    after = _load_object(inputs["after"])
    compatibility = _load_object(inputs["compatibility"])
    site_package = _load_object(inputs["site_package"])
    no_reinflation = _load_object(inputs["no_reinflation"])
    performance = _load_object(inputs["performance"])
    footprint = _load_object(inputs["storage_footprint"])
    gate_reports = [_load_object(path) for path in gates]

    core_by_id, before_observations, after_observations = _validate_core_functional(
        baseline,
        after,
        compatibility,
        head=head,
        repo_root=root,
        development_root=development,
    )
    _validate_site_package(site_package, head=head, repo_root=root)
    _validate_no_reinflation(no_reinflation, head=head, repo_root=root)
    _validate_performance(performance, head=head)
    _validate_storage_footprint(footprint, head=head)
    _validate_gates(gate_reports, head=head)
    if site_package.get("storage_registry", {}).get("sha256") != footprint.get(
        "storage_registry", {}
    ).get("sha256"):
        raise FunctionalFinalizationError(
            "Site Package and final storage footprint use different storage registries"
        )

    input_paths = {
        **inputs,
        **{f"gate_{index}": path for index, path in enumerate(gates)},
    }
    input_hashes = {
        name: _sha256_file(path) for name, path in sorted(input_paths.items())
    }
    binding = {
        "git_head": head,
        "finalizer_script_sha256": _sha256_file(Path(__file__).resolve(strict=True)),
        "input_sha256": input_hashes,
    }
    binding["binding_sha256"] = _hash_json(binding)
    common_evidence = _common_evidence(
        inputs=inputs,
        gate_paths=gates,
        site_package=site_package,
        no_reinflation=no_reinflation,
        performance=performance,
        footprint=footprint,
    )
    matrix = _build_matrix(
        core_by_id,
        common_evidence=common_evidence,
        before_observations=before_observations,
        after_observations=after_observations,
    )
    if len(matrix) != len(MATRIX_DEFINITIONS) or any(
        item["status"] != "PASS" for item in matrix
    ):
        raise FunctionalFinalizationError(
            "final functional consumer matrix is incomplete"
        )

    final_baseline = copy.deepcopy(baseline)
    final_after = copy.deepcopy(after)
    final_compatibility = copy.deepcopy(compatibility)
    for artifact in (final_baseline, final_after, final_compatibility):
        artifact["audit_mode"] = "FINAL_EVIDENCE"
        artifact["git_head"] = head
        artifact["final_evidence"] = copy.deepcopy(binding)
    final_baseline["consumer_matrix"] = [
        {"id": item["id"], "status": "PASS", "evidence": item["baseline_evidence"]}
        for item in matrix
    ]
    final_after["consumer_matrix"] = [
        {"id": item["id"], "status": "PASS", "evidence": item["after_evidence"]}
        for item in matrix
    ]
    final_compatibility["consumer_matrix"] = matrix
    final_compatibility["status"] = "PASS"
    final_compatibility["summary"] = {
        "core_check_count": len(core_by_id),
        "consumer_check_count": len(matrix),
        "passed_count": len(matrix),
        "failed_count": 0,
        "aggregate_hash": _hash_json(
            [{"id": item["id"], "status": item["status"]} for item in matrix]
        ),
    }
    payloads = {
        "FUNCTIONAL_BASELINE.json": final_baseline,
        "FUNCTIONAL_AFTER.json": final_after,
        "FUNCTIONAL_COMPATIBILITY.json": final_compatibility,
    }
    _atomic_publish(output_paths, payloads, overwrite=overwrite)
    return output_paths


def _validate_core_functional(
    baseline: Mapping[str, Any],
    after: Mapping[str, Any],
    compatibility: Mapping[str, Any],
    *,
    head: str,
    repo_root: Path,
    development_root: Path,
) -> tuple[
    dict[str, Mapping[str, Any]],
    Mapping[str, Mapping[str, Any]],
    Mapping[str, Mapping[str, Any]],
]:
    if (
        baseline.get("artifact") != "FUNCTIONAL_BASELINE"
        or baseline.get("status") != "PASS"
    ):
        raise FunctionalFinalizationError("FUNCTIONAL_BASELINE is not PASS")
    if after.get("artifact") != "FUNCTIONAL_AFTER" or after.get("status") != "PASS":
        raise FunctionalFinalizationError("FUNCTIONAL_AFTER is not PASS")
    if (
        compatibility.get("artifact") != "FUNCTIONAL_COMPATIBILITY"
        or compatibility.get("status") != "PASS"
    ):
        raise FunctionalFinalizationError(
            "database functional compatibility is not PASS"
        )
    generator = (
        repo_root / "scripts/maintenance/validate_database_functional_compatibility.py"
    )
    for label, report in (
        ("FUNCTIONAL_BASELINE", baseline),
        ("FUNCTIONAL_AFTER", after),
        ("FUNCTIONAL_COMPATIBILITY", compatibility),
    ):
        _validate_generator(report, label=label, head=head, script=generator)
    before_observations = _validate_observation_bundle(
        baseline,
        label="FUNCTIONAL_BASELINE",
        head=head,
        development_root=development_root,
    )
    after_observations = _validate_observation_bundle(
        after, label="FUNCTIONAL_AFTER", head=head, development_root=development_root
    )
    if set(before_observations) != set(after_observations):
        raise FunctionalFinalizationError(
            "before/after consumer observation IDs differ"
        )
    before_binding = baseline["consumer_observations"]["snapshot_binding"]
    after_binding = after["consumer_observations"]["snapshot_binding"]
    if (
        before_binding.get("site_id") != "ningbo-line-12"
        or after_binding.get("site_id") != "ningbo-line-12"
        or before_binding.get("snapshot_id") != after_binding.get("snapshot_id")
        or before_binding.get("isolated_copy") is not True
        or after_binding.get("isolated_copy") is not True
    ):
        raise FunctionalFinalizationError(
            "before/after consumer observations are not bound to the same isolated Ningbo Line 12 snapshot"
        )
    checks = {
        str(item.get("id")): item
        for item in compatibility.get("checks", [])
        if isinstance(item, Mapping)
    }
    if set(checks) != CORE_CHECKS or any(
        item.get("status") != "PASS" for item in checks.values()
    ):
        raise FunctionalFinalizationError(
            "database functional compatibility core checks are incomplete"
        )
    return checks, before_observations, after_observations


def _validate_observation_bundle(
    report: Mapping[str, Any],
    *,
    label: str,
    head: str,
    development_root: Path,
) -> Mapping[str, Mapping[str, Any]]:
    bundle = report.get("consumer_observations")
    if not isinstance(bundle, Mapping):
        raise FunctionalFinalizationError(f"{label} consumer observations are missing")
    binding = bundle.get("snapshot_binding")
    observations = bundle.get("observations")
    if not isinstance(binding, Mapping) or not isinstance(observations, Mapping):
        raise FunctionalFinalizationError(
            f"{label} consumer observations are incomplete"
        )
    expected_ids = {name for name, _core, _tests in MATRIX_DEFINITIONS}
    if set(str(value) for value in observations) != expected_ids:
        raise FunctionalFinalizationError(
            f"{label} consumer observation IDs are incomplete"
        )
    root = Path(str(binding.get("root") or "")).resolve()
    if (
        binding.get("site_id") != "ningbo-line-12"
        or binding.get("isolated_copy") is not True
        or not str(binding.get("snapshot_id") or "").strip()
        or not root.is_relative_to(development_root)
        or not root.is_dir()
    ):
        raise FunctionalFinalizationError(f"{label} snapshot binding is invalid")
    report_generator = report.get("generator")
    if not isinstance(report_generator, Mapping):
        raise FunctionalFinalizationError(f"{label} generator binding is missing")
    validated: dict[str, Mapping[str, Any]] = {}
    for name in sorted(expected_ids):
        item = observations.get(name)
        if not isinstance(item, Mapping) or item.get("status") != "PASS":
            raise FunctionalFinalizationError(
                f"{label} consumer observation failed: {name}"
            )
        digest = str(item.get("query_digest") or "").casefold()
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise FunctionalFinalizationError(
                f"{label} consumer query digest is invalid: {name}"
            )
        paths = item.get("source_paths")
        if (
            not isinstance(paths, Sequence)
            or isinstance(paths, (str, bytes))
            or not paths
        ):
            raise FunctionalFinalizationError(
                f"{label} consumer source paths are missing: {name}"
            )
        for raw_path in paths:
            path = Path(str(raw_path)).resolve()
            if not path.is_relative_to(development_root) or not path.is_file():
                raise FunctionalFinalizationError(
                    f"{label} consumer source path is invalid: {name}"
                )
        for field in ("producer", "repository", "consumer", "lifecycle_owner", "query"):
            if not str(item.get(field) or "").strip():
                raise FunctionalFinalizationError(
                    f"{label} consumer observation field is missing: {name}.{field}"
                )
        authority = item.get("authority_evidence")
        if not isinstance(authority, Mapping) or authority.get("status") != "PASS":
            raise FunctionalFinalizationError(
                f"{label} consumer observation authority evidence is missing: {name}"
            )
        if not str(authority.get("authority") or "").strip():
            raise FunctionalFinalizationError(
                f"{label} consumer observation authority is missing: {name}"
            )
        test_ids = authority.get("test_ids")
        if (
            not isinstance(test_ids, Sequence)
            or isinstance(test_ids, (str, bytes))
            or not test_ids
        ):
            raise FunctionalFinalizationError(
                f"{label} consumer observation authority tests are missing: {name}"
            )
        generator = item.get("generator")
        if not isinstance(generator, Mapping) or dict(generator) != dict(
            report_generator
        ):
            raise FunctionalFinalizationError(
                f"{label} consumer observation generator is stale: {name}"
            )
        validated[name] = item
    return validated


def _validate_site_package(
    report: Mapping[str, Any], *, head: str, repo_root: Path
) -> None:
    if (
        report.get("format") != "netconsole-integrated-site-package-validation-v1"
        or report.get("status") != "PASS"
    ):
        raise FunctionalFinalizationError(
            "integrated Site Package evidence is not PASS"
        )
    _validate_generator(
        report,
        label="integrated Site Package",
        head=head,
        script=repo_root / "scripts/maintenance/validate_integrated_site_package.py",
    )
    parity = report.get("parity")
    if not isinstance(parity, Mapping):
        raise FunctionalFinalizationError("integrated Site Package parity is missing")
    for name in ("operational", "authorities", "repository_api"):
        values = parity.get(name)
        if (
            not isinstance(values, Mapping)
            or not values
            or not all(value is True for value in values.values())
        ):
            raise FunctionalFinalizationError(
                f"integrated Site Package {name} parity is incomplete"
            )
    registered = parity.get("registered_storage")
    if not isinstance(registered, Mapping) or registered.get("status") != "PASS":
        raise FunctionalFinalizationError(
            "integrated Site Package registered storage parity failed"
        )
    if report.get("imported", {}).get("restart") != "PASS":
        raise FunctionalFinalizationError(
            "integrated Site Package restart evidence failed"
        )
    cleanup = report.get("staging_cleanup", {})
    for field in (
        "export_success",
        "import_success",
        "import_failure",
        "failure_rollback",
    ):
        if cleanup.get(field) is not True:
            raise FunctionalFinalizationError(
                f"Site Package cleanup evidence failed: {field}"
            )
    interruption = cleanup.get("interruption_recovery")
    if (
        not isinstance(interruption, Mapping)
        or interruption.get("status") != "PASS"
        or interruption.get("failures")
        or int(interruption.get("restored_site_imports") or 0) < 1
        or int(interruption.get("removed_publish_files") or 0) < 1
        or int(interruption.get("removed_internal_entries") or 0) < 2
        or cleanup.get("interruption_remaining")
    ):
        raise FunctionalFinalizationError(
            "Site Package cleanup evidence failed: interruption_recovery"
        )


def _validate_no_reinflation(
    report: Mapping[str, Any], *, head: str, repo_root: Path
) -> None:
    if report.get("status") != "PASS":
        raise FunctionalFinalizationError("No-Reinflation report is not PASS")
    _validate_generator(
        report,
        label="No-Reinflation",
        head=head,
        script=repo_root / "scripts/maintenance/validate_storage_no_reinflation.py",
    )
    scenarios = {
        str(item.get("scenario_id")): item
        for item in report.get("scenarios", [])
        if isinstance(item, Mapping)
    }
    if set(scenarios) != NO_REINFLATION_SCENARIOS or any(
        item.get("status") != "PASS" for item in scenarios.values()
    ):
        raise FunctionalFinalizationError("No-Reinflation scenarios are incomplete")
    aggregate = report.get("storage_amplification_factor")
    if not isinstance(aggregate, Mapping):
        raise FunctionalFinalizationError(
            "No-Reinflation amplification evidence is missing"
        )
    _validate_amplification(aggregate, label="No-Reinflation aggregate")
    for scenario_id, item in scenarios.items():
        metric = item.get("storage_amplification")
        if (
            not isinstance(metric, Mapping)
            or metric.get("measurement_status") != "PASS"
        ):
            raise FunctionalFinalizationError(
                f"No-Reinflation measurement is incomplete: {scenario_id}"
            )
        _validate_amplification(metric, label=f"No-Reinflation {scenario_id}")


def _validate_amplification(metric: Mapping[str, Any], *, label: str) -> None:
    if (
        int(metric.get("declared_input_events") or 0) <= 0
        or int(metric.get("file_count") or 0) <= 0
        or int(metric.get("total_physical_bytes") or 0) <= 0
        or not isinstance(metric.get("bytes_per_input_event"), (int, float))
        or float(metric["bytes_per_input_event"]) <= 0
    ):
        raise FunctionalFinalizationError(f"{label} has no non-zero byte evidence")


def _validate_generator(
    report: Mapping[str, Any],
    *,
    label: str,
    head: str,
    script: Path,
) -> None:
    generator = report.get("generator")
    if not isinstance(generator, Mapping):
        raise FunctionalFinalizationError(f"{label} generator binding is missing")
    expected_path = script.resolve(strict=True)
    repository = Path(__file__).resolve().parents[2]
    if (
        str(report.get("git_head") or "").casefold() != head
        or str(generator.get("git_head") or "").casefold() != head
        or str(generator.get("script_path") or "")
        != expected_path.relative_to(repository).as_posix()
        or str(generator.get("script_sha256") or "").casefold()
        != _sha256_file(expected_path)
    ):
        raise FunctionalFinalizationError(
            f"{label} is not bound to the final HEAD and current generator"
        )


def _validate_performance(report: Mapping[str, Any], *, head: str) -> None:
    if (
        report.get("format") != "netconsole-database-performance-comparison-v1"
        or report.get("status") != "PASS"
    ):
        raise FunctionalFinalizationError("database performance comparison is not PASS")
    if str(report.get("git_head") or "").casefold() != head:
        raise FunctionalFinalizationError(
            "database performance evidence is not bound to final HEAD"
        )
    cases = {
        str(item.get("id")): item
        for item in report.get("cases", [])
        if isinstance(item, Mapping)
    }
    if set(cases) != PERFORMANCE_CASES or any(
        item.get("status") != "PASS" for item in cases.values()
    ):
        raise FunctionalFinalizationError("database performance cases are incomplete")
    for item in cases.values():
        for side in ("before", "after"):
            latency = item.get(side, {}).get("latency_ms", {})
            if not all(
                isinstance(latency.get(key), (int, float))
                for key in ("p50", "p95", "max")
            ):
                raise FunctionalFinalizationError(
                    f"performance latency is incomplete: {item.get('id')}.{side}"
                )


def _validate_storage_footprint(report: Mapping[str, Any], *, head: str) -> None:
    evidence = report.get("final_evidence", {})
    if report.get("audit_mode") != "FINAL_EVIDENCE" or evidence.get("git_head") != head:
        raise FunctionalFinalizationError(
            "storage footprint is not final-HEAD evidence"
        )
    if (
        report.get("optimization_impact", {}).get("status")
        != "ISOLATED_REHEARSAL_MEASURED"
    ):
        raise FunctionalFinalizationError(
            "storage footprint has no measured optimization impact"
        )


def _validate_gates(reports: Sequence[Mapping[str, Any]], *, head: str) -> None:
    by_mode = {str(report.get("mode")): report for report in reports}
    if set(by_mode) != set(GATE_SUITES):
        raise FunctionalFinalizationError(
            "TARGETED, FAST, CONSUMER and FULL gate reports are all required"
        )
    for mode, required in GATE_SUITES.items():
        report = by_mode[mode]
        passed = {str(value) for value in report.get("passed", [])}
        if (
            report.get("result") != "PASS"
            or report.get("failed")
            or report.get("not_run")
        ):
            raise FunctionalFinalizationError(f"{mode} gate is not PASS")
        if str(report.get("head_sha") or "").casefold() != head:
            raise FunctionalFinalizationError(f"{mode} gate is not bound to final HEAD")
        if not required <= passed:
            raise FunctionalFinalizationError(f"{mode} gate is missing required suites")


def _common_evidence(
    *,
    inputs: Mapping[str, Path],
    gate_paths: Sequence[Path],
    site_package: Mapping[str, Any],
    no_reinflation: Mapping[str, Any],
    performance: Mapping[str, Any],
    footprint: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "baseline": {
            "path": str(inputs["baseline"]),
            "sha256": _sha256_file(inputs["baseline"]),
        },
        "after": {
            "path": str(inputs["after"]),
            "sha256": _sha256_file(inputs["after"]),
        },
        "site_package": {
            "path": str(inputs["site_package"]),
            "sha256": _sha256_file(inputs["site_package"]),
            "package_sha256": site_package.get("package", {}).get("sha256"),
        },
        "no_reinflation": {
            "path": str(inputs["no_reinflation"]),
            "sha256": _sha256_file(inputs["no_reinflation"]),
            "scenarios": sorted(NO_REINFLATION_SCENARIOS),
        },
        "performance": {
            "path": str(inputs["performance"]),
            "sha256": _sha256_file(inputs["performance"]),
            "cases": sorted(PERFORMANCE_CASES),
        },
        "storage_footprint": {
            "path": str(inputs["storage_footprint"]),
            "sha256": _sha256_file(inputs["storage_footprint"]),
            "registry_sha256": footprint.get("storage_registry", {}).get("sha256"),
        },
        "gates": [
            {"path": str(path), "sha256": _sha256_file(path)} for path in gate_paths
        ],
    }


def _build_matrix(
    core_by_id: Mapping[str, Mapping[str, Any]],
    *,
    common_evidence: Mapping[str, Any],
    before_observations: Mapping[str, Mapping[str, Any]],
    after_observations: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    matrix: list[dict[str, Any]] = []
    for name, core_ids, test_ids in MATRIX_DEFINITIONS:
        core = [core_by_id[check_id] for check_id in core_ids]
        differences = [
            difference for item in core for difference in item.get("differences", [])
        ]
        before_observation = before_observations[name]
        after_observation = after_observations[name]
        if (
            before_observation.get("status") != "PASS"
            or after_observation.get("status") != "PASS"
        ):
            differences.append(
                {
                    "item": "consumer_observation_status",
                    "before": before_observation.get("status"),
                    "after": after_observation.get("status"),
                }
            )
        if before_observation.get("query_digest") != after_observation.get(
            "query_digest"
        ):
            differences.append(
                {
                    "item": "consumer_observation_query_digest",
                    "before": before_observation.get("query_digest"),
                    "after": after_observation.get("query_digest"),
                }
            )
        matrix.append(
            {
                "id": name,
                "status": "PASS" if not differences else "FAIL",
                "baseline_evidence": [common_evidence["baseline"]],
                "after_evidence": [
                    common_evidence["after"],
                    common_evidence["site_package"],
                    common_evidence["storage_footprint"],
                ],
                "test_ids": [*test_ids, "FAST", "CONSUMER", "FULL"],
                "differences": differences,
                "observations": {
                    "before": {
                        "query": before_observation["query"],
                        "query_digest": before_observation["query_digest"],
                        "source_paths": before_observation["source_paths"],
                        "authority_evidence": before_observation["authority_evidence"],
                        "generator": before_observation["generator"],
                    },
                    "after": {
                        "query": after_observation["query"],
                        "query_digest": after_observation["query_digest"],
                        "source_paths": after_observation["source_paths"],
                        "authority_evidence": after_observation["authority_evidence"],
                        "generator": after_observation["generator"],
                    },
                },
                "supporting_evidence": {
                    "core_checks": list(core_ids),
                    "gates": common_evidence["gates"],
                    "no_reinflation": common_evidence["no_reinflation"],
                    "performance": common_evidence["performance"],
                },
            }
        )
    return matrix


def _validate_matrix_test_ids(repo_root: Path) -> None:
    missing: list[str] = []
    for _name, _core_ids, test_ids in MATRIX_DEFINITIONS:
        for test_id in test_ids:
            source = test_id.split("::", 1)[0]
            if "/" not in source or source == "DATABASE_PERFORMANCE.json":
                continue
            if not (repo_root / source).is_file():
                missing.append(source)
    if missing:
        raise FunctionalFinalizationError(
            "functional matrix references missing tests: "
            + ", ".join(sorted(set(missing)))
        )


def _input_file(path: Path, development_root: Path) -> Path:
    candidate = path.resolve(strict=True)
    if not candidate.is_relative_to(development_root) or not candidate.is_file():
        raise FunctionalFinalizationError(
            f"evidence must be a file below D:/study: {candidate}"
        )
    return candidate


def _output_directory(path: Path, development_root: Path) -> Path:
    candidate = path.resolve()
    if candidate == development_root or not candidate.is_relative_to(development_root):
        raise FunctionalFinalizationError("output must be a child below D:/study")
    if path.exists() and (path.is_symlink() or not path.is_dir()):
        raise FunctionalFinalizationError(f"unsafe output directory: {candidate}")
    return candidate


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FunctionalFinalizationError(
            f"invalid JSON evidence {path}: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise FunctionalFinalizationError(f"JSON evidence must be an object: {path}")
    return value


def _git_head(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "--verify", "HEAD"],
        check=False,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        text=True,
    )
    head = result.stdout.strip().casefold()
    if result.returncode or len(head) != 40:
        raise FunctionalFinalizationError("cannot resolve final Git HEAD")
    return head


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_json(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def _atomic_publish(
    paths: Mapping[str, Path],
    payloads: Mapping[str, Mapping[str, Any]],
    *,
    overwrite: bool,
) -> None:
    destination = next(iter(paths.values())).parent
    destination.mkdir(parents=True, exist_ok=True)
    temporary: dict[str, Path] = {}
    try:
        for name, target in paths.items():
            temp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
            with temp.open("xb") as stream:
                stream.write(
                    (
                        json.dumps(
                            payloads[name], ensure_ascii=False, indent=2, sort_keys=True
                        )
                        + "\n"
                    ).encode("utf-8")
                )
                stream.flush()
                os.fsync(stream.fileno())
            temporary[name] = temp
        for name, target in paths.items():
            if overwrite:
                os.replace(temporary[name], target)
            else:
                os.link(temporary[name], target)
                temporary[name].unlink()
    finally:
        for path in temporary.values():
            path.unlink(missing_ok=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--compatibility", type=Path, required=True)
    parser.add_argument("--site-package", type=Path, required=True)
    parser.add_argument("--no-reinflation", type=Path, required=True)
    parser.add_argument("--performance", type=Path, required=True)
    parser.add_argument("--storage-footprint", type=Path, required=True)
    parser.add_argument("--gate-report", type=Path, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument(
        "--development-root", type=Path, default=DEFAULT_DEVELOPMENT_ROOT
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    outputs = finalize_functional_compatibility(
        baseline_path=args.baseline,
        after_path=args.after,
        compatibility_path=args.compatibility,
        site_package_path=args.site_package,
        no_reinflation_path=args.no_reinflation,
        performance_path=args.performance,
        storage_footprint_path=args.storage_footprint,
        gate_paths=args.gate_report,
        output_dir=args.output_dir,
        repo_root=args.repo_root,
        development_root=args.development_root,
        overwrite=args.overwrite,
    )
    print(
        json.dumps(
            {
                "status": "PASS",
                "outputs": {name: str(path) for name, path in outputs.items()},
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
