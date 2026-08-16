from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from scripts.maintenance.validate_storage_no_reinflation import (
    REPORT_NAME,
    SCENARIOS,
    validate_no_reinflation,
)


def test_validator_runs_registered_scenarios_and_writes_machine_readable_report(
    tmp_path: Path,
) -> None:
    commands: list[list[str]] = []

    def successful_runner(command: list[str], **_kwargs: object):
        commands.append(command)
        basetemp = Path(command[command.index("--basetemp") + 1])
        basetemp.mkdir(parents=True)
        (basetemp / "evidence.db").write_bytes(b"SQLite format 3\x00" + b"x" * 4096)
        return subprocess.CompletedProcess(
            command,
            returncode=0,
            stdout="1 passed in 0.01s\n",
            stderr="",
        )

    run_root = tmp_path / "no-reinflation"
    report = validate_no_reinflation(
        run_root,
        python_executable="python-for-test",
        runner=successful_runner,
    )

    assert report["status"] == "PASS"
    assert report["production_data_access"] == "FORBIDDEN"
    assert report["summary"] == {
        "scenario_count": len(SCENARIOS),
        "passed": len(SCENARIOS),
        "failed": 0,
    }
    assert len(commands) == len(SCENARIOS)
    assert all(command[:3] == ["python-for-test", "-m", "pytest"] for command in commands)
    assert all("--basetemp" in command for command in commands)
    assert all(
        Path(command[command.index("--basetemp") + 1]).parent.is_dir()
        for command in commands
    )
    persisted = json.loads((run_root / REPORT_NAME).read_text(encoding="utf-8"))
    assert persisted["status"] == "PASS"
    script = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "maintenance"
        / "validate_storage_no_reinflation.py"
    )
    assert persisted["git_head"] == persisted["generator"]["git_head"]
    assert persisted["generator"]["script_path"] == (
        "scripts/maintenance/validate_storage_no_reinflation.py"
    )
    assert persisted["generator"]["script_sha256"] == hashlib.sha256(
        script.read_bytes()
    ).hexdigest()
    assert persisted["storage_amplification_factor"] == {
        "basis": (
            "aggregate post-test physical bytes / declared logical input events"
        ),
        "artifact_or_raw_bytes": 0,
        "bytes_per_input_event": pytest.approx(
            (4112 * len(SCENARIOS))
            / sum(int(scenario.declared_input_events or 0) for scenario in SCENARIOS)
        ),
        "declared_input_events": sum(
            int(scenario.declared_input_events or 0) for scenario in SCENARIOS
        ),
        "file_count": len(SCENARIOS),
        "metric": "STORAGE AMPLIFICATION FACTOR",
        "sqlite_bytes": 4112 * len(SCENARIOS),
        "total_physical_bytes": 4112 * len(SCENARIOS),
        "wal_shm_journal_bytes": 0,
    }
    assert all(
        item["storage_amplification"]["metric"]
        == "STORAGE AMPLIFICATION FACTOR"
        for item in persisted["scenarios"]
    )
    assert all(
        item["storage_amplification"]["file_measurements"]
        and item["storage_amplification"]["file_measurements"][0]["sha256"]
        for item in persisted["scenarios"]
    )
    assert {item["scenario_id"] for item in persisted["scenarios"]} == {
        scenario.scenario_id for scenario in SCENARIOS
    }
    assert all(item["cleanup"]["status"] == "PASS" for item in persisted["scenarios"])
    assert all(not Path(item["cleanup"]["path"]).exists() for item in persisted["scenarios"])


def test_validator_records_failure_and_continues_remaining_scenarios(
    tmp_path: Path,
) -> None:
    calls = 0

    def one_failure(command: list[str], **_kwargs: object):
        nonlocal calls
        calls += 1
        basetemp = Path(command[command.index("--basetemp") + 1])
        basetemp.mkdir(parents=True)
        (basetemp / "evidence.db").write_bytes(b"SQLite format 3\x00" + b"x" * 4096)
        return subprocess.CompletedProcess(
            command,
            returncode=1 if calls == 2 else 0,
            stdout="failed\n" if calls == 2 else "passed\n",
            stderr="",
        )

    report = validate_no_reinflation(
        tmp_path / "failed-run",
        runner=one_failure,
    )

    assert calls == len(SCENARIOS)
    assert report["status"] == "FAIL"
    assert report["summary"] == {
        "scenario_count": len(SCENARIOS),
        "passed": len(SCENARIOS) - 1,
        "failed": 1,
    }
    assert report["failed_scenarios"] == [SCENARIOS[1].scenario_id]


def test_validator_fails_closed_when_pytest_leaves_no_measurable_storage(
    tmp_path: Path,
) -> None:
    def empty_runner(command: list[str], **_kwargs: object):
        return subprocess.CompletedProcess(command, returncode=0, stdout="passed\n", stderr="")

    report = validate_no_reinflation(
        tmp_path / "empty-storage-run",
        runner=empty_runner,
    )

    assert report["status"] == "FAIL"
    assert report["failed_scenarios"] == [
        scenario.scenario_id for scenario in SCENARIOS
    ]
    assert all(
        item["storage_amplification"]["measurement_status"] == "FAIL"
        for item in report["scenarios"]
    )


def test_validator_refuses_production_and_existing_roots(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="under"):
        validate_no_reinflation(Path("D:/NetConsoleData/no-reinflation"))

    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(FileExistsError, match="already exists"):
        validate_no_reinflation(existing)
