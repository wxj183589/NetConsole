from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path

import pytest

from netconsole.services.interface_discovery_shadow import (
    COMPARE_DIFFERENT,
    COMPARE_MATCH,
    COMPARE_SHADOW_FAILED,
    SHADOW_EMPTY,
    SHADOW_FAILED,
    SHADOW_TIMEOUT,
)
from tests.support.device_inventory_replay import replay_fixture
from tests.support.interface_discovery_rehearsal import (
    IsolatedShadowRehearsal,
    build_evidence_payload,
    rehearse_pre_switch_backup,
    repository_effect,
    secret_scan,
    write_evidence_bundle,
)

FIXTURE = Path(__file__).parent / "fixtures" / "device_cli" / "h3c_comware7_synthetic.json"


def _git_identity() -> tuple[str, str]:
    repository = Path(__file__).resolve().parents[1]
    sha = subprocess.check_output(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        text=True,
    ).strip()
    branch = subprocess.check_output(
        ["git", "-C", str(repository), "branch", "--show-current"],
        text=True,
    ).strip()
    return sha, branch


def _harness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> IsolatedShadowRehearsal:
    result = replay_fixture(FIXTURE)
    return IsolatedShadowRehearsal.create(tmp_path, monkeypatch, result)


def _different_result(result: dict[str, object]) -> dict[str, object]:
    changed = copy.deepcopy(result)
    interfaces = list(changed["interfaces"])  # type: ignore[index]
    if len(interfaces) < 2:
        raise AssertionError("the H3C rehearsal fixture must contain two interfaces")
    first = dict(interfaces[0])
    first["speed"] = "REHEARSAL-DIFFERENT-SPEED"
    interfaces = [first, *interfaces[2:], {"interface_name": "RehearsalAdded1/0/1"}]
    changed["interfaces"] = interfaces
    return changed


def _shadow_error() -> dict[str, object]:
    raise RuntimeError("controlled shadow failure password=must-not-leak")


def _shadow_timeout() -> dict[str, object]:
    raise TimeoutError("controlled shadow timeout")


def _scenario_callbacks(
    result: dict[str, object],
) -> dict[str, object]:
    return {
        "MATCH": lambda: copy.deepcopy(result),
        "DIFFERENT": lambda: _different_result(result),
        "ERROR": _shadow_error,
        "TIMEOUT": _shadow_timeout,
        "EMPTY": lambda: {"interfaces": []},
    }


def test_rehearsal_covers_f0_to_f7_and_writes_machine_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _harness(tmp_path, monkeypatch)
    harness.capture("F0")
    harness.legacy_cycle()
    harness.capture("F1")
    writes_before_scenarios = harness.write_counter.snapshot()
    scenarios: dict[str, dict[str, object]] = {}
    expected = {
        "MATCH": ("SUCCESS", COMPARE_MATCH),
        "DIFFERENT": ("SUCCESS", COMPARE_DIFFERENT),
        "ERROR": (SHADOW_FAILED, COMPARE_SHADOW_FAILED),
        "TIMEOUT": (SHADOW_TIMEOUT, COMPARE_SHADOW_FAILED),
        "EMPTY": (SHADOW_EMPTY, COMPARE_DIFFERENT),
    }

    for index, (scenario, callback) in enumerate(_scenario_callbacks(harness.result).items(), start=2):
        harness.enable_shadow()
        writes_before = harness.write_counter.snapshot()
        report = harness.shadow_cycle(scenario, callback)  # type: ignore[arg-type]
        label = f"F{index}"
        harness.capture(label)
        writes_after = harness.write_counter.snapshot()
        scenarios[scenario] = harness.scenario_record(
            scenario,
            "F1",
            label,
            writes_before=writes_before,
            writes_after=writes_after,
        )
        assert report.legacy_status == "SUCCESS"
        assert report.shadow_status == expected[scenario][0]
        assert report.compare_status == expected[scenario][1]
        assert writes_after == writes_before
        harness.disable_shadow()

    harness.disable_shadow()
    harness.legacy_cycle()
    harness.capture("F7")

    assert set(scenarios) == {"MATCH", "DIFFERENT", "ERROR", "TIMEOUT", "EMPTY"}
    assert all(item["repository_effect"] == "NONE" for item in scenarios.values())
    assert all(
        item["repository_effect_detail"]["revision_effect"] == "NONE"
        for item in scenarios.values()
    )
    assert all(item["task_status_before"] == "SUCCESS" for item in scenarios.values())
    assert all(item["task_status_after"] == "SUCCESS" for item in scenarios.values())
    assert len(scenarios["DIFFERENT"]["added"]) == 1
    assert len(scenarios["DIFFERENT"]["removed"]) == 1
    assert len(scenarios["DIFFERENT"]["changed"]) == 1
    assert harness.write_counter.snapshot() != writes_before_scenarios
    assert harness.shadow_enabled is False
    assert harness.task_states["F7"] == "SUCCESS"

    legacy_resume_effect = repository_effect(
        harness.fingerprints["F6"],
        harness.fingerprints["F7"],
    )
    assert legacy_resume_effect["repository_effect"] == "CHANGED"
    assert legacy_resume_effect["current_effect"] == "CHANGED"
    assert legacy_resume_effect["revision_effect"] == "CHANGED"

    git_sha, branch = _git_identity()
    backup = rehearse_pre_switch_backup(
        harness.database,
        harness.root,
        git_sha=git_sha,
        branch=branch,
    )
    assert backup["status"] == "PASS"
    evidence = build_evidence_payload(
        run_id="phase2d-b1-interface-shadow-rehearsal",
        git_sha=git_sha,
        branch=branch,
        test_root=harness.root,
        scenarios=scenarios,
        repository_fingerprint_before=harness.fingerprints["F1"],
        repository_fingerprint_after=harness.fingerprints["F2"],
        backup_manifest_status=str(backup["status"]),
    )
    summary_path = write_evidence_bundle(
        harness.root / "artifacts" / "engineering-hardening" / "interface-discovery-rehearsal",
        evidence,
    )
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS"
    assert payload["repository_effect"] == "NONE"
    assert payload["rollback_status"] == "PASS"
    assert payload["backup_manifest_status"] == "PASS"
    assert payload["production_touched"] is False
    assert payload["real_device_connected"] is False
    assert secret_scan(payload) == []
    evidence_text = summary_path.read_text(encoding="utf-8").casefold()
    assert "password=" not in evidence_text
    assert "must-not-leak" not in evidence_text


def test_invalid_shadow_result_is_isolated_from_legacy_and_repository(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _harness(tmp_path, monkeypatch)
    harness.capture("F0")
    harness.legacy_cycle()
    harness.capture("F1")
    harness.enable_shadow()
    writes_before = harness.write_counter.snapshot()
    report = harness.shadow_cycle("INVALID", lambda: {"unexpected": True})
    harness.capture("F2")
    effect = repository_effect(harness.fingerprints["F1"], harness.fingerprints["F2"])

    assert report.legacy_status == "SUCCESS"
    assert report.shadow_status == SHADOW_FAILED
    assert report.compare_status == COMPARE_SHADOW_FAILED
    assert effect["repository_effect"] == "NONE"
    assert harness.write_counter.snapshot() == writes_before
    assert harness.task_states["F2"] == "SUCCESS"
    harness.disable_shadow()
    assert harness.shadow_enabled is False


@pytest.mark.parametrize("rollback_scenario", ["MATCH", "ERROR", "TIMEOUT"])
def test_controlled_stop_resume_needs_no_repair_restart_or_history_rebuild(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    rollback_scenario: str,
) -> None:
    harness = _harness(tmp_path, monkeypatch)
    harness.capture("F0")
    harness.legacy_cycle()
    harness.capture("F1")
    harness.enable_shadow()
    callbacks = _scenario_callbacks(harness.result)
    report = harness.shadow_cycle(rollback_scenario, callbacks[rollback_scenario])  # type: ignore[arg-type]
    harness.capture("F2")
    harness.disable_shadow()
    writes_before_resume = harness.write_counter.snapshot()
    harness.legacy_cycle()
    harness.capture("F7")

    assert harness.shadow_enabled is False
    assert report.legacy_status == "SUCCESS"
    assert harness.task_states["F7"] == "SUCCESS"
    assert harness.write_counter.snapshot() != writes_before_resume
    assert repository_effect(harness.fingerprints["F1"], harness.fingerprints["F2"])[
        "repository_effect"
    ] == "NONE"
    assert "database repair" not in json.dumps(report.to_dict()).casefold()
    assert "restart" not in json.dumps(report.to_dict()).casefold()


def test_pre_switch_backup_manifest_rehearsal_is_verified_without_source_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _harness(tmp_path, monkeypatch)
    git_sha, branch = _git_identity()
    rehearsal = rehearse_pre_switch_backup(
        harness.database,
        harness.root,
        git_sha=git_sha,
        branch=branch,
    )
    manifest = rehearsal["manifest"]
    validation = rehearsal["validation"]

    assert rehearsal["status"] == "PASS"
    assert rehearsal["source_mutated"] is False
    assert rehearsal["production_backup_executed"] is False
    assert rehearsal["sha256_verified"] is True
    assert manifest["result_status"] == "VALID_BACKUP"
    assert manifest["authority_status"] == "VERIFIED"
    assert manifest["data_root_identity"] == "isolated-test-root"
    assert manifest["source_git_sha"] == git_sha
    assert manifest["source_branch"] == branch
    assert manifest["source_file_list"][0]["sha256"] == rehearsal["source_before"]["sha256"]
    assert manifest["source_file_list"][0]["size"] == rehearsal["source_before"]["size"]
    assert manifest["source_file_list"][0]["mtime_ns"] == rehearsal["source_before"]["mtime_ns"]
    assert manifest["schema_version_metadata"]
    assert manifest["restore_notes"]
    assert validation["restorable"] is True
    assert validation["sha256_matches"] is True
    assert secret_scan(manifest) == []
