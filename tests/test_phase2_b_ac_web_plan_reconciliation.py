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
from netconsole.services.job_center.runtime.task_event_hub import TaskEventHub
from netconsole.services.job_center.runtime.task_runtime import TaskRuntime
from netconsole.services.job_center.task_application_service import TaskApplicationService
from netconsole.services.job_center.task_cleanup_service import CleanupDecision, TaskCleanupService


TASK_TYPE = "ac_command_action_execute"
PLAN_ID = "ac-plan-00000000000000000000000000000001"
TASK_ID = "ac-web-action-fixture"


def _event(event_type: str, payload: dict[str, object], *, site_id: str = "") -> dict[str, object]:
    return {
        "id": f"event-{event_type}",
        "task_id": TASK_ID,
        "type": event_type,
        "time": "2026-10-16T00:00:00Z",
        "source": "task_center",
        "payload": {**payload, **({"site_id": site_id} if site_id else {})},
    }


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
        self.events = TaskEventHub()
        self.site_name = "demo"

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
        updated_time="2026-10-16T00:00:00Z",
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


@pytest.mark.parametrize(
    ("task_status", "event_type"),
    [
        (TaskState.COMPLETED, "finished"),
        (TaskState.FAILED, "error"),
        (TaskState.CANCELLED, "cancelled"),
    ],
)
def test_terminal_task_event_automatically_persists_plan_audit(
    tmp_path: Path, task_status: TaskState, event_type: str
) -> None:
    service = _service(_snapshot(task_status, result={"plan_id": PLAN_ID}))
    plan_path = tmp_path / f"{PLAN_ID}.json"
    plan_path.write_text(json.dumps(_plan()), encoding="utf-8")
    saved: list[dict[str, object]] = []
    service._plan_path = lambda _plan_id: plan_path
    service._save_plan = lambda value: (
        saved.append(deepcopy(value)),
        plan_path.write_text(json.dumps(value), encoding="utf-8"),
    )[-1]
    service._site = lambda site_id: site_id
    service.task_service.events.subscribe(service._handle_task_event)

    service.task_service.events.publish_persisted(
        _event(event_type, {"job_id": TASK_ID, "plan_id": PLAN_ID})
    )

    stored = json.loads(plan_path.read_text(encoding="utf-8"))
    assert stored["status"] == task_status.value
    assert stored["status_reconciliation"]["source"] == "task_center"
    assert len(saved) == 1


def test_duplicate_terminal_event_is_idempotent_and_scope_mismatch_is_ignored(
    tmp_path: Path,
) -> None:
    service = _service(_snapshot(TaskState.COMPLETED, result={"plan_id": PLAN_ID}))
    plan_path = tmp_path / f"{PLAN_ID}.json"
    plan_path.write_text(json.dumps(_plan()), encoding="utf-8")
    saved: list[dict[str, object]] = []
    service._plan_path = lambda _plan_id: plan_path
    service._save_plan = lambda value: (
        saved.append(deepcopy(value)),
        plan_path.write_text(json.dumps(value), encoding="utf-8"),
    )[-1]
    service._site = lambda site_id: site_id
    service.task_service.events.subscribe(service._handle_task_event)
    terminal_event = _event(
        "state",
        {
            "job_id": TASK_ID,
            "state": TaskState.COMPLETED.value,
            "plan_id": PLAN_ID,
        },
    )

    service.task_service.events.publish_persisted(terminal_event)
    service.task_service.events.publish_persisted(terminal_event)
    assert len(saved) == 1

    service.task_service.events.publish_persisted(
        _event("finished", {"job_id": TASK_ID, "plan_id": "ac-plan-ffffffffffffffffffffffffffffffff"})
    )
    assert len(saved) == 1

    foreign = _service(_snapshot(TaskState.COMPLETED, owner="other", result={"plan_id": PLAN_ID}))
    foreign._plan_path = lambda _plan_id: plan_path
    foreign._save_plan = lambda value: saved.append(deepcopy(value))
    foreign._site = lambda site_id: site_id
    foreign.task_service.events.subscribe(foreign._handle_task_event)
    foreign.task_service.events.publish_persisted(terminal_event)
    assert len(saved) == 1


def test_recovered_terminal_snapshot_uses_the_same_automatic_coordination_path(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(TaskState.FAILED, result={"plan_id": PLAN_ID})
    service = _service(snapshot)
    plan_path = tmp_path / f"{PLAN_ID}.json"
    plan_path.write_text(json.dumps(_plan()), encoding="utf-8")
    service._plan_path = lambda _plan_id: plan_path
    service._save_plan = lambda value: plan_path.write_text(json.dumps(value), encoding="utf-8")
    service._site = lambda site_id: site_id
    service.task_service.events.subscribe(service._handle_task_event)

    publisher = object.__new__(TaskApplicationService)
    publisher.runtime = SimpleNamespace(events=service.task_service.events)
    TaskApplicationService._publish_recovered_terminal_tasks(publisher, [snapshot])

    stored = json.loads(plan_path.read_text(encoding="utf-8"))
    assert stored["status"] == "FAILED"
    assert stored["status_reconciliation"]["source"] == "task_center"


def test_coordination_failure_is_logged_without_rewriting_task_state() -> None:
    service = object.__new__(AcWebApplicationService)
    service.task_service = _TaskService(
        _snapshot(TaskState.FAILED, result={"plan_id": PLAN_ID})
    )
    calls: list[tuple[str, str]] = []

    def fail_reconcile(site_id: str, plan_id: str) -> None:
        calls.append((site_id, plan_id))
        raise RuntimeError("fixture failure")

    service.reconcile_action_plan = fail_reconcile
    service.task_service.events.subscribe(service._handle_task_event)
    service.task_service.events.publish_persisted(
        _event("error", {"job_id": TASK_ID, "plan_id": PLAN_ID})
    )

    assert calls == [("demo", PLAN_ID)]
    assert service.task_service.repository("demo").snapshot.status is TaskState.FAILED


def test_terminal_event_handler_rejects_non_ac_task_and_cross_site_task() -> None:
    calls: list[tuple[str, str]] = []
    service = object.__new__(AcWebApplicationService)
    service.task_service = _TaskService(
        _snapshot(TaskState.COMPLETED, result={"plan_id": PLAN_ID}, task_type="other")
    )
    service.reconcile_action_plan = lambda site_id, plan_id: calls.append((site_id, plan_id))
    service.task_service.events.subscribe(service._handle_task_event)
    service.task_service.events.publish_persisted(
        _event("finished", {"job_id": TASK_ID, "plan_id": PLAN_ID})
    )
    assert calls == []

    service.task_service = _TaskService(
        _snapshot(TaskState.COMPLETED, result={"plan_id": PLAN_ID}, site_name="other")
    )
    service.task_service.events.subscribe(service._handle_task_event)
    service.task_service.events.publish_persisted(
        _event("finished", {"job_id": TASK_ID, "plan_id": PLAN_ID}, site_id="demo")
    )
    assert calls == []


def test_task_runtime_only_adds_ac_plan_correlation_metadata() -> None:
    ac_task = SimpleNamespace(
        launch=SimpleNamespace(
            job=SimpleNamespace(task_type=TASK_TYPE, params={"plan_id": PLAN_ID})
        )
    )
    payload: dict[str, object] = {}
    TaskRuntime._attach_ac_web_plan_id(ac_task, payload)
    assert payload == {"plan_id": PLAN_ID}

    payload = {"plan_id": "ac-plan-existing"}
    TaskRuntime._attach_ac_web_plan_id(ac_task, payload)
    assert payload == {"plan_id": "ac-plan-existing"}

    other_task = SimpleNamespace(
        launch=SimpleNamespace(job=SimpleNamespace(task_type="other", params={"plan_id": PLAN_ID}))
    )
    payload = {}
    TaskRuntime._attach_ac_web_plan_id(other_task, payload)
    assert payload == {}


def test_cleanup_callback_runs_before_terminal_task_rows_are_deleted() -> None:
    order: list[tuple[str, list[str]]] = []

    class _CleanupRepository:
        def delete_task_owned_rows(self, task_ids: list[str]) -> dict[str, object]:
            order.append(("delete", list(task_ids)))
            return {
                "deleted": {"task_events": 1, "task_snapshots": 1, "task_results": 1},
                "deleted_task_ids": list(task_ids),
                "orphan_blobs_removed": 0,
                "orphan_blob_bytes_removed": 0,
                "quick_check": "ok",
                "foreign_key_check": "ok",
                "task_payload_bytes": 0,
                "task_events_payload_bytes": 0,
                "task_snapshots_payload_bytes": 0,
                "task_results_payload_bytes": 0,
            }

    cleanup = TaskCleanupService(
        _CleanupRepository(),
        before_delete=lambda task_ids: order.append(("before_delete", list(task_ids))),
    )
    cleanup._decisions = lambda task_ids: [
        CleanupDecision(task_id=task_id, can_cleanup=True, status=TaskState.COMPLETED.value)
        for task_id in task_ids
    ]

    result = cleanup.cleanup_tasks([TASK_ID])

    assert result["deleted_task_ids"] == [TASK_ID]
    assert order == [("before_delete", [TASK_ID]), ("delete", [TASK_ID])]
