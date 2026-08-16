from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from scripts.maintenance.benchmark_database_functional_queries import REQUIRED_CASES
from scripts.maintenance.finalize_functional_compatibility import (
    GATE_SUITES,
    MATRIX_DEFINITIONS,
    NO_REINFLATION_SCENARIOS,
    PERFORMANCE_CASES,
    FunctionalFinalizationError,
    finalize_functional_compatibility,
)


def test_finalizer_performance_contract_matches_benchmark() -> None:
    assert PERFORMANCE_CASES == frozenset(REQUIRED_CASES)


def _write(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()


def _generator(relative: str) -> dict[str, str]:
    repository = Path(__file__).resolve().parents[1]
    script = repository / relative
    return {
        "git_head": _head(),
        "script_path": relative,
        "script_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
    }


def _amplification(*, measurement: bool = False) -> dict[str, object]:
    value: dict[str, object] = {
        "declared_input_events": 100,
        "file_count": 1,
        "total_physical_bytes": 4096,
        "bytes_per_input_event": 40.96,
    }
    if measurement:
        value["measurement_status"] = "PASS"
    return value


def _fixture(tmp_path: Path) -> dict[str, object]:
    checks = [
        {"id": check_id, "status": "PASS", "differences": []}
        for check_id in (
            "devices.current_business_tables",
            "tasks.auxiliary_business_tables",
            "tasks.repository_transparent_read",
            "history.migration_and_post_replace_parity",
        )
    ]
    functional_generator = _generator(
        "scripts/maintenance/validate_database_functional_compatibility.py"
    )
    snapshot_root = tmp_path / "ningbo-line-12-isolated-snapshot"
    snapshot_root.mkdir(parents=True, exist_ok=True)

    def observations(side: str) -> dict[str, object]:
        result: dict[str, object] = {}
        for name, _core_ids, _tests in MATRIX_DEFINITIONS:
            safe_name = (
                name.lower().replace(" ", "-").replace("/", "-").replace("\\", "-")
            )
            source = tmp_path / "source" / f"{side}-{safe_name}.json"
            _write(source, {"consumer": name, "canonical_result": "unchanged"})
            result[name] = {
                "status": "PASS",
                "query": f"read_only_query:{name}:{side}",
                "query_digest": hashlib.sha256(source.read_bytes()).hexdigest(),
                "source_paths": [str(source)],
                "producer": f"{name} producer",
                "repository": f"{name} repository",
                "consumer": f"{name} consumer",
                "lifecycle_owner": f"{name} owner",
                "authority_evidence": {
                    "status": "PASS",
                    "authority": f"{name} authority",
                    "test_ids": ["tests/test_finalize_functional_compatibility.py"],
                },
                "generator": functional_generator,
            }
        return {
            "schema_version": 1,
            "snapshot_binding": {
                "site_id": "ningbo-line-12",
                "snapshot_id": "pytest-ningbo-line-12",
                "root": str(snapshot_root),
                "isolated_copy": True,
            },
            "observations": result,
        }

    baseline = _write(
        tmp_path / "source" / "FUNCTIONAL_BASELINE.json",
        {
            "artifact": "FUNCTIONAL_BASELINE",
            "status": "PASS",
            "git_head": _head(),
            "generator": functional_generator,
            "consumer_observations": observations("before"),
        },
    )
    after = _write(
        tmp_path / "source" / "FUNCTIONAL_AFTER.json",
        {
            "artifact": "FUNCTIONAL_AFTER",
            "status": "PASS",
            "git_head": _head(),
            "generator": functional_generator,
            "consumer_observations": observations("after"),
        },
    )
    compatibility = _write(
        tmp_path / "source" / "FUNCTIONAL_COMPATIBILITY.json",
        {
            "artifact": "FUNCTIONAL_COMPATIBILITY",
            "status": "PASS",
            "checks": checks,
            "git_head": _head(),
            "generator": functional_generator,
        },
    )
    site_package = _write(
        tmp_path / "source" / "SITE_PACKAGE.json",
        {
            "format": "netconsole-integrated-site-package-validation-v1",
            "status": "PASS",
            "git_head": _head(),
            "generator": _generator(
                "scripts/maintenance/validate_integrated_site_package.py"
            ),
            "package": {"sha256": "a" * 64},
            "parity": {
                "operational": {"devices": True},
                "authorities": {"history": True},
                "repository_api": {"tasks": True},
                "registered_storage": {"status": "PASS"},
            },
            "imported": {"restart": "PASS"},
            "staging_cleanup": {
                "export_success": True,
                "import_success": True,
                "import_failure": True,
                "failure_rollback": True,
                "interruption_recovery": {
                    "status": "PASS",
                    "removed_internal_entries": 2,
                    "removed_publish_files": 1,
                    "removed_journals": 2,
                    "restored_site_imports": 1,
                    "completed_site_imports": 0,
                    "failures": [],
                },
                "interruption_remaining": [],
            },
            "storage_registry": {"sha256": "b" * 64},
        },
    )
    no_reinflation = _write(
        tmp_path / "source" / "STORAGE_NO_REINFLATION.json",
        {
            "status": "PASS",
            "git_head": _head(),
            "generator": _generator(
                "scripts/maintenance/validate_storage_no_reinflation.py"
            ),
            "scenarios": [
                {
                    "scenario_id": scenario,
                    "status": "PASS",
                    "storage_amplification": _amplification(measurement=True),
                }
                for scenario in sorted(NO_REINFLATION_SCENARIOS)
            ],
            "storage_amplification_factor": _amplification(),
        },
    )
    performance = _write(
        tmp_path / "source" / "DATABASE_PERFORMANCE.json",
        {
            "format": "netconsole-database-performance-comparison-v1",
            "status": "PASS",
            "git_head": _head(),
            "cases": [
                {
                    "id": case,
                    "status": "PASS",
                    "before": {"latency_ms": {"p50": 1, "p95": 2, "max": 3}},
                    "after": {"latency_ms": {"p50": 1, "p95": 2, "max": 3}},
                }
                for case in sorted(PERFORMANCE_CASES)
            ],
        },
    )
    footprint = _write(
        tmp_path / "source" / "SITE_STORAGE_FOOTPRINT.json",
        {
            "audit_mode": "FINAL_EVIDENCE",
            "final_evidence": {"git_head": _head()},
            "optimization_impact": {"status": "ISOLATED_REHEARSAL_MEASURED"},
            "storage_registry": {"sha256": "b" * 64},
        },
    )
    gates = []
    for mode, suites in GATE_SUITES.items():
        gates.append(
            _write(
                tmp_path / "source" / f"gate-{mode}.json",
                {
                    "mode": mode,
                    "result": "PASS",
                    "head_sha": _head(),
                    "passed": sorted(suites),
                    "failed": [],
                    "not_run": [],
                },
            )
        )
    return {
        "baseline_path": baseline,
        "after_path": after,
        "compatibility_path": compatibility,
        "site_package_path": site_package,
        "no_reinflation_path": no_reinflation,
        "performance_path": performance,
        "storage_footprint_path": footprint,
        "gate_paths": gates,
        "output_dir": tmp_path / "output",
        "development_root": tmp_path.parent.parent,
    }


def test_finalizer_emits_complete_matrix_bound_to_head(tmp_path: Path) -> None:
    arguments = _fixture(tmp_path)

    outputs = finalize_functional_compatibility(**arguments)

    reports = {
        name: json.loads(path.read_text(encoding="utf-8"))
        for name, path in outputs.items()
    }
    compatibility = reports["FUNCTIONAL_COMPATIBILITY.json"]
    assert compatibility["status"] == "PASS"
    assert compatibility["audit_mode"] == "FINAL_EVIDENCE"
    assert compatibility["git_head"] == _head()
    assert len(compatibility["consumer_matrix"]) == len(MATRIX_DEFINITIONS)
    assert all(item["status"] == "PASS" for item in compatibility["consumer_matrix"])
    assert {item["id"] for item in compatibility["consumer_matrix"]} >= {
        "Ground",
        "Online MR",
        "MESH Analysis",
        "Site Package",
        "Restart Recovery",
        "Performance Regression",
    }
    for name in ("FUNCTIONAL_BASELINE.json", "FUNCTIONAL_AFTER.json"):
        assert reports[name]["final_evidence"]["git_head"] == _head()
        assert len(reports[name]["consumer_matrix"]) == len(MATRIX_DEFINITIONS)
    for path in outputs.values():
        assert len(hashlib.sha256(path.read_bytes()).hexdigest()) == 64


def test_finalizer_rejects_consumer_query_digest_drift(tmp_path: Path) -> None:
    arguments = _fixture(tmp_path)
    after_path = arguments["after_path"]
    report = json.loads(after_path.read_text(encoding="utf-8"))
    report["consumer_observations"]["observations"]["History"]["query_digest"] = (
        "0" * 64
    )
    _write(after_path, report)

    with pytest.raises(
        FunctionalFinalizationError, match="consumer matrix is incomplete"
    ):
        finalize_functional_compatibility(**arguments)


def test_finalizer_fails_closed_before_writing_on_missing_scenario(
    tmp_path: Path,
) -> None:
    arguments = _fixture(tmp_path)
    path = arguments["no_reinflation_path"]
    report = json.loads(path.read_text(encoding="utf-8"))
    report["scenarios"].pop()
    _write(path, report)

    with pytest.raises(FunctionalFinalizationError, match="scenarios are incomplete"):
        finalize_functional_compatibility(**arguments)

    assert not Path(arguments["output_dir"]).exists()


def test_finalizer_rejects_gate_from_different_head(tmp_path: Path) -> None:
    arguments = _fixture(tmp_path)
    gate = arguments["gate_paths"][0]
    report = json.loads(gate.read_text(encoding="utf-8"))
    report["head_sha"] = "0" * 40
    _write(gate, report)

    with pytest.raises(FunctionalFinalizationError, match="not bound to final HEAD"):
        finalize_functional_compatibility(**arguments)


def test_finalizer_requires_site_package_interruption_recovery(tmp_path: Path) -> None:
    arguments = _fixture(tmp_path)
    package = arguments["site_package_path"]
    report = json.loads(package.read_text(encoding="utf-8"))
    report["staging_cleanup"].pop("interruption_recovery")
    _write(package, report)

    with pytest.raises(FunctionalFinalizationError, match="interruption_recovery"):
        finalize_functional_compatibility(**arguments)

    assert not Path(arguments["output_dir"]).exists()


def test_finalizer_rejects_stale_functional_generator(tmp_path: Path) -> None:
    arguments = _fixture(tmp_path)
    baseline = arguments["baseline_path"]
    report = json.loads(baseline.read_text(encoding="utf-8"))
    report["generator"]["script_sha256"] = "0" * 64
    _write(baseline, report)

    with pytest.raises(FunctionalFinalizationError, match="current generator"):
        finalize_functional_compatibility(**arguments)

    assert not Path(arguments["output_dir"]).exists()


def test_finalizer_rejects_zero_no_reinflation_measurement(tmp_path: Path) -> None:
    arguments = _fixture(tmp_path)
    no_reinflation = arguments["no_reinflation_path"]
    report = json.loads(no_reinflation.read_text(encoding="utf-8"))
    report["scenarios"][0]["storage_amplification"]["total_physical_bytes"] = 0
    _write(no_reinflation, report)

    with pytest.raises(FunctionalFinalizationError, match="non-zero byte evidence"):
        finalize_functional_compatibility(**arguments)

    assert not Path(arguments["output_dir"]).exists()
