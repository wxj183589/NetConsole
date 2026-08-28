from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Sequence

from netconsole.services.database_footprint_maintenance import assert_development_path


TEST_DATA_ROOT = Path("D:/study/test-data/NetConsole")
REPORT_NAME = "STORAGE_NO_REINFLATION.json"


@dataclass(frozen=True)
class GrowthScenario:
    scenario_id: str
    owner: str
    pass_condition: str
    node_ids: tuple[str, ...]
    declared_input_events: int | None = None


SCENARIOS = (
    GrowthScenario(
        scenario_id="task_progress_and_result",
        owner="TaskRepository / TaskResultMaintenanceService",
        pass_condition=(
            "100/1000/10000 identical progress observations keep one operational event; "
            "terminal replay keeps one canonical full result and reference-only compatibility rows"
        ),
        node_ids=(
            "tests/test_task_repository_storage_governance.py::"
            "test_identical_progress_keeps_current_snapshot_and_samples_event_history",
            "tests/test_storage_no_reinflation.py::"
            "test_terminal_result_replay_keeps_one_result_authority_payload",
        ),
        declared_input_events=11_200,
    ),
    GrowthScenario(
        scenario_id="ground_current_state",
        owner="GroundUnattendedRepository",
        pass_condition=(
            "100/1000/10000 identical train/AP and radio-interface states keep one current row "
            "per identity without inventing event or snapshot history"
        ),
        node_ids=(
            "tests/test_storage_no_reinflation.py::"
            "test_ground_current_state_replay_is_cardinality_bounded",
        ),
        declared_input_events=22_200,
    ),
    GrowthScenario(
        scenario_id="online_mr_raw_authority",
        owner="OnlineMrCollector / OnlineMrSession",
        pass_condition=(
            "1000 repeated MESH cycles and 100 slow-collector cycles keep one raw payload authority; "
            "live_samples retain source identity, SHA-256, exact byte ranges, and parsed facts without "
            "mirroring full AP/channel/interface payloads into SQLite; Switch History current state "
            "and legacy compatibility remain bounded"
        ),
        node_ids=(
            "tests/test_storage_no_reinflation.py::"
            "test_online_mr_long_replay_keeps_one_raw_payload_authority",
            "tests/test_storage_no_reinflation.py::"
            "test_online_mr_slow_collectors_keep_raw_authority_and_bounded_current_state",
            "tests/test_storage_no_reinflation.py::"
            "test_online_mr_authority_schema_upgrade_preserves_legacy_raw_columns",
            "tests/test_storage_no_reinflation.py::"
            "test_online_mr_repeat_stream_publishes_durable_raw_range_before_database_fact",
            "tests/test_storage_no_reinflation.py::"
            "test_online_mr_offline_replay_is_source_idempotent",
        ),
        declared_input_events=1_602,
    ),
    GrowthScenario(
        scenario_id="ground_ping_syslog_raw_growth",
        owner="Ground RawStreamWriter / GroundUnattendedRepository",
        pass_condition=(
            "1000 Ping and Syslog observations remain as 1000 precise raw facts per stream; "
            "Ping summary stays one bounded row and repeated structured Syslog payload stays one "
            "row with an auditable duplicate count"
        ),
        node_ids=(
            "tests/test_storage_no_reinflation.py::"
            "test_ground_ping_syslog_growth_preserves_raw_facts_and_bounds_projections",
        ),
        declared_input_events=2_000,
    ),
    GrowthScenario(
        scenario_id="device_lldp_ap_state",
        owner="DeviceFactRepository / HistoryStore",
        pass_condition=(
            "100/1000/10000 unchanged LLDP/AP association snapshots keep one current row and one "
            "history fact; a semantic association change creates exactly one additional history fact"
        ),
        node_ids=(
            "tests/test_storage_no_reinflation.py::"
            "test_device_lldp_ap_association_replay_records_only_semantic_change",
        ),
        declared_input_events=11_103,
    ),
    GrowthScenario(
        scenario_id="mesh_source_and_reparse",
        owner="MeshImportService / MeshSourceRebuildService",
        pass_condition=(
            "ten imports of the same content fingerprint keep one raw authority and ten forced "
            "reparses replace one derived projection"
        ),
        node_ids=(
            "tests/test_storage_no_reinflation.py::"
            "test_mesh_repeat_import_and_reparse_keep_one_source_authority",
        ),
        declared_input_events=20,
    ),
    GrowthScenario(
        scenario_id="site_package_staging",
        owner="SitePackageService",
        pass_condition=(
            "successful export, publish failure, corrupt import, and replacement failure leave no "
            "unowned staging and preserve the previous authority"
        ),
        node_ids=(
            "tests/test_site_storage.py::"
            "test_site_sync_staging_uses_managed_temp_and_cleans_success_and_failure",
            "tests/test_site_storage.py::"
            "test_site_package_rejects_corrupt_sqlite3_and_cleans_import_staging",
            "tests/test_site_storage.py::"
            "test_full_migration_replace_restores_original_site_when_publish_fails",
            "tests/test_storage_no_reinflation.py::"
            "test_site_package_cancel_cleans_staging_and_preserves_source",
            "tests/test_site_storage.py::"
            "test_field_return_package_previews_and_applies_three_way_merge",
        ),
        declared_input_events=6,
    ),
    GrowthScenario(
        scenario_id="backup_same_revision",
        owner="DatabaseBackupStore",
        pass_condition=(
            "retrying an unchanged source revision reuses one verified full backup across restart; "
            "a changed revision creates exactly one new backup"
        ),
        node_ids=(
            "tests/test_backup_lifecycle.py::"
            "test_same_source_revision_reuses_verified_full_backup_and_restart",
        ),
        declared_input_events=3,
    ),
)


Runner = Callable[..., subprocess.CompletedProcess[str]]


def validate_no_reinflation(
    run_root: Path,
    *,
    python_executable: str | Path = sys.executable,
    runner: Runner = subprocess.run,
    scenarios: Sequence[GrowthScenario] = SCENARIOS,
) -> dict[str, object]:
    controlled_root = _create_controlled_run_root(run_root)
    repository_root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment.update(
        {
            "NETCONSOLE_RUNTIME_MODE": "test",
            "NETCONSOLE_STORAGE_MODE": "persistent",
            "NETCONSOLE_DATA_ROOT": str(controlled_root / "session"),
            "NETCONSOLE_PRESERVE_TEST_BASETEMP": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUTF8": "1",
        }
    )
    results: list[dict[str, object]] = []
    for scenario in scenarios:
        basetemp = controlled_root / "pytest" / scenario.scenario_id
        basetemp.parent.mkdir(parents=True, exist_ok=True)
        command = [
            str(python_executable),
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--basetemp",
            str(basetemp),
            *scenario.node_ids,
        ]
        started = time.monotonic()
        completed = runner(
            command,
            cwd=repository_root,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        duration = round(time.monotonic() - started, 3)
        output = "\n".join(
            line.rstrip()
            for line in f"{completed.stdout}\n{completed.stderr}".splitlines()[-80:]
        ).strip()
        amplification = _storage_amplification(
            basetemp,
            declared_input_events=scenario.declared_input_events,
        )
        cleanup = _cleanup_measured_basetemp(basetemp, controlled_root=controlled_root)
        measurement_passed = (
            int(amplification["file_count"]) > 0
            and int(amplification["total_physical_bytes"]) > 0
        )
        passed = completed.returncode == 0 and measurement_passed and cleanup["status"] == "PASS"
        results.append(
            {
                "scenario_id": scenario.scenario_id,
                "owner": scenario.owner,
                "pass_condition": scenario.pass_condition,
                "node_ids": list(scenario.node_ids),
                "status": "PASS" if passed else "FAIL",
                "exit_code": int(completed.returncode),
                "duration_seconds": duration,
                "storage_amplification": {
                    **amplification,
                    "measurement_phase": "BEFORE_SCENARIO_CLEANUP",
                    "measurement_status": "PASS" if measurement_passed else "FAIL",
                },
                "cleanup": cleanup,
                "pytest_output_tail": output,
            }
        )

    failed = [str(item["scenario_id"]) for item in results if item["status"] != "PASS"]
    generator = _evidence_binding(
        Path(__file__).resolve(), repository_root=repository_root
    )
    report: dict[str, object] = {
        "format": "netconsole-storage-no-reinflation",
        "version": 1,
        "git_head": generator["git_head"],
        "generator": generator,
        "generated_at": datetime.now(UTC).isoformat(),
        "run_root": str(controlled_root),
        "production_data_access": "FORBIDDEN",
        "production_data_root": "D:/NetConsoleData",
        "status": "PASS" if not failed else "FAIL",
        "failed_scenarios": failed,
        "summary": {
            "scenario_count": len(results),
            "passed": len(results) - len(failed),
            "failed": len(failed),
        },
        "storage_amplification_factor": _aggregate_storage_amplification(results),
        "scenarios": results,
    }
    report_path = controlled_root / REPORT_NAME
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def _storage_amplification(
    root: Path,
    *,
    declared_input_events: int | None,
) -> dict[str, object]:
    files = (
        sorted(
            path
            for path in Path(root).rglob("*")
            if path.is_file() and not path.is_symlink()
        )
        if Path(root).is_dir()
        else []
    )
    sqlite_bytes = 0
    sidecar_bytes = 0
    artifact_bytes = 0
    file_measurements: list[dict[str, object]] = []
    for path in files:
        size = int(path.stat().st_size)
        lowered = path.name.casefold()
        if lowered.endswith(("-wal", "-shm", "-journal")):
            storage_type = "SQLITE_SIDECAR"
            sidecar_bytes += size
        elif path.suffix.casefold() in {".db", ".sqlite", ".sqlite3"}:
            storage_type = "SQLITE"
            sqlite_bytes += size
        else:
            storage_type = "ARTIFACT_OR_RAW"
            artifact_bytes += size
        file_measurements.append(
            {
                "relative_path": path.relative_to(root).as_posix(),
                "storage_type": storage_type,
                "bytes": size,
                "sha256": _sha256_file(path),
            }
        )
    total_bytes = sqlite_bytes + sidecar_bytes + artifact_bytes
    bytes_per_event = (
        round(total_bytes / declared_input_events, 6)
        if declared_input_events
        else None
    )
    return {
        "metric": "STORAGE AMPLIFICATION FACTOR",
        "basis": "post-test physical bytes / declared logical input events",
        "declared_input_events": declared_input_events,
        "file_count": len(files),
        "sqlite_bytes": sqlite_bytes,
        "wal_shm_journal_bytes": sidecar_bytes,
        "artifact_or_raw_bytes": artifact_bytes,
        "total_physical_bytes": total_bytes,
        "bytes_per_input_event": bytes_per_event,
        "file_measurements": file_measurements,
    }


def _aggregate_storage_amplification(
    results: Sequence[dict[str, object]],
) -> dict[str, object]:
    metrics = [
        item["storage_amplification"]
        for item in results
        if isinstance(item.get("storage_amplification"), dict)
    ]
    input_events = sum(
        int(item.get("declared_input_events") or 0) for item in metrics
    )
    total_bytes = sum(
        int(item.get("total_physical_bytes") or 0) for item in metrics
    )
    return {
        "metric": "STORAGE AMPLIFICATION FACTOR",
        "basis": "aggregate post-test physical bytes / declared logical input events",
        "declared_input_events": input_events,
        "file_count": sum(int(item.get("file_count") or 0) for item in metrics),
        "sqlite_bytes": sum(int(item.get("sqlite_bytes") or 0) for item in metrics),
        "wal_shm_journal_bytes": sum(
            int(item.get("wal_shm_journal_bytes") or 0) for item in metrics
        ),
        "artifact_or_raw_bytes": sum(
            int(item.get("artifact_or_raw_bytes") or 0) for item in metrics
        ),
        "total_physical_bytes": total_bytes,
        "bytes_per_input_event": (
            round(total_bytes / input_events, 6) if input_events else None
        ),
    }


def _cleanup_measured_basetemp(
    basetemp: Path,
    *,
    controlled_root: Path,
) -> dict[str, object]:
    target = Path(basetemp).resolve()
    pytest_root = (controlled_root / "pytest").resolve()
    if target.parent != pytest_root or target == pytest_root:
        return {
            "status": "FAIL",
            "reason": "scenario basetemp escaped the controlled pytest root",
            "path": str(target),
            "exists_after_cleanup": target.exists(),
        }
    if target.exists() and (target.is_symlink() or not target.is_dir()):
        return {
            "status": "FAIL",
            "reason": "scenario basetemp is not an owned directory",
            "path": str(target),
            "exists_after_cleanup": True,
        }
    if target.is_dir():
        shutil.rmtree(target)
    return {
        "status": "PASS" if not target.exists() else "FAIL",
        "reason": "measured before controlled cleanup",
        "path": str(target),
        "exists_after_cleanup": target.exists(),
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _evidence_binding(script: Path, *, repository_root: Path) -> dict[str, str]:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return {
        "git_head": completed.stdout.strip().casefold(),
        "script_path": script.relative_to(repository_root).as_posix(),
        "script_sha256": _sha256_file(script),
    }


def _create_controlled_run_root(run_root: Path) -> Path:
    target = assert_development_path(run_root)
    test_data_root = TEST_DATA_ROOT.resolve()
    if target == test_data_root or not target.is_relative_to(test_data_root):
        raise ValueError(
            f"No-Reinflation run root must be below {test_data_root}"
        )
    if target.exists():
        raise FileExistsError(f"No-Reinflation run root already exists: {target}")
    target.mkdir(parents=True, exist_ok=False)
    return target


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run NetConsole storage No-Reinflation growth gates"
    )
    parser.add_argument(
        "--run-root",
        required=True,
        type=Path,
        help="New isolated directory below D:/study/test-data/NetConsole",
    )
    parser.add_argument(
        "--python",
        type=Path,
        default=Path(sys.executable),
        help="Python executable containing pytest and project dependencies",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = validate_no_reinflation(
        args.run_root,
        python_executable=args.python,
    )
    print(json.dumps(report["summary"], ensure_ascii=False, sort_keys=True))
    print(str(Path(str(report["run_root"])) / REPORT_NAME))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
