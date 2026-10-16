"""Isolated Phase 2-B tests for AC Web action-plan reconciliation."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from netconsole.application.ac.web_application_service import (
    AcWebApplicationService,
    classify_ac_action_plan_status,
)
from netconsole.models.task_state import TaskState


TASK_TYPE = "ac_command_action_execute"
PLAN_ID = "ac-plan-00000000000000000000000000000001"
TASK_ID = "ac-web-action-fixture"


class _Repository:
    def __init__(self, snapshot=None, *, tombstoned: bool = False) -> None:
        self.snapshot = snapshot
        self.tombstoned = tombstoned

    def get(self, task_id: str):
        assert task_id == TASK_ID
        return self.snapshot

    def has_retention_tombstone(self, task_id: str) -> bool:
        assert task_id == TASK_ID
        return self.tombstoned

    def list(self, **_kwargs):
        raise AssertionError("reconciliation must not scan Task history")


class _TaskService:
    def __init__(self, snapshot=None, *, tombstoned: bool = False) -> None:
        self.repository_instance = _Repository(snapshot, tombstoned=tombstoned)

    def repository(self, site_id: str):
        assert site_id == "demo"
        return self.repository_instance


def _snapshot(
    status: TaskState,
    *,
    task_id: str = TASK_ID,
    site_name: str = "demo",
    owner: str = "web_ac",
    source: str = "local",
    task_type: str = TASK_TYPE,
    result: dict[str, object] | None = None,
):
    return SimpleNamespace(
        task_id=task_id,
        status=status,
        site_name=site_name,
        owner=owner,
        source=source,
        task_type=task_type,
        result=dict(result or {}),
    )


def _plan(status: str = "EXECUTING") -> dict[str, object]:
    return {
        "plan_id": PLAN_ID,
        "site_id": "demo",
        "target_id": "ac-1",
        "action_id": "persist_auto_ap",
        "action_label": "固化新 AP",
        "commands": [],
        "digest": "digest",
        "token": "token",
        "expires_at": 9999999999,
        "task_id": TASK_ID,
        "status": status,
    }


def _service(snapshot=None, *, tombstoned: bool = False):
    service = object.__new__(AcWebApplicationService)
    service.task_service = _TaskService(snapshot, tombstoned=tombstoned)
    service._save_plan = lambda plan: None
    return service


@pytest.mark.parametrize(
    ("task_status", "expected_status"),
    [
        (TaskState.COMPLETED, "COMPLETED"),
        (TaskState.FAILED, "FAILED"),
        (TaskState.CANCELLED, "CANCELLED"),
    ],
)
def test_terminal_task_is_effective_without_get_side_effect(task_status, expected_status) -> None:
    plan = _plan()
    result = classify_ac_action_plan_status(
        plan,
        _snapshot(task_status, result={"plan_id": PLAN_ID}),
        expected_site_id="demo",
        allowed_task_types={TASK_TYPE},
    )

    assert result.effective_status == expected_status
    assert result.reconciliation_status == "VERIFIED_TERMINAL"
    assert result.evidence_level == "DIRECT_PLAN_ID"
    assert result.can_persist_terminal is True
    assert plan["status"] == "EXECUTING"


def test_active_task_remains_executing_and_does_not_scan_or_write() -> None:
    service = _service(_snapshot(TaskState.RUNNING, result={"plan_id": PLAN_ID}))
    plan = _plan()
    saved: list[dict[str, object]] = []
    service._save_plan = lambda value: saved.append(deepcopy(value))

    result = service._refresh_plan_status("demo", plan)

    assert result.effective_status == "EXECUTING"
    assert result.reconciliation_status == "VERIFIED_ACTIVE"
    assert saved == []
    assert plan["status"] == "EXECUTING"


def test_missing_task_with_tombstone_is_unknown_not_failed() -> None:
    service = _service(None, tombstoned=True)

    result = service._refresh_plan_status("demo", _plan())

    assert result.effective_status == "UNKNOWN_OR_UNVERIFIED"
    assert result.reconciliation_reason == "TASK_HISTORY_CLEANED"
    assert result.evidence_level == "TOMBSTONE"


def test_missing_task_is_unknown_after_submission_grace() -> None:
    plan = {**_plan(), "task_submitted_at": 100.0}

    result = classify_ac_action_plan_status(
        plan,
        None,
        expected_site_id="demo",
        now=111.0,
    )

    assert result.effective_status == "UNKNOWN_OR_UNVERIFIED"
    assert result.reconciliation_reason == "TASK_NOT_FOUND"


def test_explicit_task_start_failure_is_not_rewritten_as_unknown() -> None:
    result = classify_ac_action_plan_status(
        _plan("START_FAILED"),
        None,
        expected_site_id="demo",
    )

    assert result.effective_status == "START_FAILED"
    assert result.reconciliation_status == "PLAN_ONLY"
    assert result.reconciliation_reason == "TASK_START_FAILED"


def test_task_start_race_is_executing_inside_submission_grace() -> None:
    plan = {**_plan(), "task_submitted_at": 100.0}

    result = classify_ac_action_plan_status(
        plan,
        None,
        expected_site_id="demo",
        now=105.0,
    )

    assert result.effective_status == "EXECUTING"
    assert result.reconciliation_status == "STARTING"
    assert result.evidence_level == "PLAN_SUBMISSION"


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("site_name", "other", "TASK_SITE_MISMATCH"),
        ("owner", "other", "TASK_OWNER_MISMATCH"),
        ("source", "remote", "TASK_SOURCE_MISMATCH"),
        ("task_type", "other", "TASK_TYPE_MISMATCH"),
    ],
)
def test_wrong_scope_task_proof_is_rejected(field: str, value: str, reason: str) -> None:
    snapshot = _snapshot(TaskState.COMPLETED, result={"plan_id": PLAN_ID})
    setattr(snapshot, field, value)

    result = classify_ac_action_plan_status(
        _plan(), snapshot, expected_site_id="demo", allowed_task_types={TASK_TYPE}
    )

    assert result.effective_status == "UNKNOWN_OR_UNVERIFIED"
    assert result.reconciliation_reason == reason
    assert result.can_persist_terminal is False


def test_plan_id_mismatch_is_not_terminal_proof() -> None:
    result = classify_ac_action_plan_status(
        _plan(),
        _snapshot(TaskState.COMPLETED, result={"plan_id": "ac-plan-other"}),
        expected_site_id="demo",
        allowed_task_types={TASK_TYPE},
    )

    assert result.effective_status == "UNKNOWN_OR_UNVERIFIED"
    assert result.reconciliation_reason == "PLAN_ID_MISMATCH"


def test_historical_result_without_plan_id_keeps_scope_evidence() -> None:
    result = classify_ac_action_plan_status(
        _plan(),
        _snapshot(TaskState.COMPLETED),
        expected_site_id="demo",
        allowed_task_types={TASK_TYPE},
    )

    assert result.effective_status == "COMPLETED"
    assert result.evidence_level == "TASK_ID_SCOPE"


def test_explicit_reconcile_persists_only_verified_terminal_result_once(tmp_path: Path) -> None:
    snapshot = _snapshot(TaskState.COMPLETED, result={"plan_id": PLAN_ID})
    service = _service(snapshot)
    plan_path = tmp_path / f"{PLAN_ID}.json"
    plan_path.write_text(json.dumps(_plan()), encoding="utf-8")
    saved: list[dict[str, object]] = []
    service._plan_path = lambda _plan_id: plan_path
    service._save_plan = lambda value: (
        saved.append(deepcopy(value)),
        plan_path.write_text(json.dumps(value), encoding="utf-8"),
    )[-1]
    service._site = lambda site_id: site_id

    first = service.reconcile_action_plan("demo", PLAN_ID)
    second = service.reconcile_action_plan("demo", PLAN_ID)

    stored = json.loads(plan_path.read_text(encoding="utf-8"))
    assert first.status == second.status == "COMPLETED"
    assert first.stored_status == "COMPLETED"
    assert stored["status"] == "COMPLETED"
    assert stored["status_reconciliation"]["source"] == "task_center"
    assert len(saved) == 1


def test_missing_or_unknown_reconciliation_does_not_write_plan() -> None:
    service = _service(None)
    plan = _plan()
    saved: list[dict[str, object]] = []
    service._save_plan = lambda value: saved.append(deepcopy(value))
    service._plan_data = lambda _plan_id, _site_id: plan
    service._site = lambda site_id: site_id

    result = service.reconcile_action_plan("demo", PLAN_ID)

    assert result.status == "UNKNOWN_OR_UNVERIFIED"
    assert plan["status"] == "EXECUTING"
    assert saved == []


def test_expired_plan_get_is_read_only_and_only_changes_effective_view() -> None:
    service = _service(None)
    plan = {**_plan("PREVIEW"), "task_id": "", "expires_at": 0}
    saved: list[dict[str, object]] = []
    service._save_plan = lambda value: saved.append(deepcopy(value))
    service._plan_data = lambda _plan_id, _site_id: plan
    service._site = lambda site_id: site_id

    result = service.preview_action_plan("demo", PLAN_ID)

    assert result.status == "EXPIRED"
    assert result.stored_status == "PREVIEW"
    assert plan["status"] == "PREVIEW"
    assert saved == []


def test_explicit_terminal_audit_survives_later_task_tombstone() -> None:
    plan = {
        **_plan("COMPLETED"),
        "status_reconciliation": {
            "task_id": TASK_ID,
            "to_status": "COMPLETED",
        },
    }

    result = classify_ac_action_plan_status(
        plan,
        None,
        expected_site_id="demo",
        tombstoned=True,
    )

    assert result.effective_status == "COMPLETED"
    assert result.reconciliation_status == "VERIFIED_TERMINAL_AUDIT"
    assert result.evidence_level == "PLAN_AUDIT"
