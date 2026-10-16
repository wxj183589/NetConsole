"""Phase 2-A isolated evidence for AC Web action-plan reconciliation.

These tests deliberately use in-memory fakes and temporary files.  They do
not open a production database, start a worker, or call a production API.
The assertions document the current lifecycle boundary so the follow-up fix
can be made against an explicit, reproducible baseline.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from netconsole.application.ac.web_application_service import (
    AcWebActionError,
    AcWebApplicationService,
)
from netconsole.models.task_state import TaskState


class _Repository:
    def __init__(self, snapshot=None) -> None:
        self.snapshot = snapshot

    def get(self, _task_id: str):
        return self.snapshot


class _TaskService:
    def __init__(self, snapshot=None) -> None:
        self.repository_instance = _Repository(snapshot)

    def repository(self, _site_id: str):
        return self.repository_instance


def _snapshot(
    status: TaskState,
    *,
    site_name: str = "demo",
    owner: str = "web_ac",
    source: str = "local",
    task_type: str = "ac_command_action_execute",
):
    return SimpleNamespace(
        status=status,
        site_name=site_name,
        owner=owner,
        source=source,
        task_type=task_type,
    )


def _service(snapshot=None):
    service = object.__new__(AcWebApplicationService)
    service.task_service = _TaskService(snapshot)
    saved: list[dict[str, object]] = []
    service._save_plan = lambda plan: saved.append(deepcopy(plan))
    return service, saved


def _plan(status: str = "EXECUTING") -> dict[str, object]:
    return {
        "plan_id": "ac-plan-00000000000000000000000000000001",
        "site_id": "demo",
        "task_id": "ac-web-action-fixture",
        "status": status,
    }


@pytest.mark.parametrize(
    ("task_status", "expected_plan_status"),
    [
        (TaskState.COMPLETED, "COMPLETED"),
        (TaskState.FAILED, "FAILED"),
        (TaskState.CANCELLED, "CANCELLED"),
    ],
)
def test_terminal_task_status_is_lazily_mapped_in_isolated_fixture(
    task_status: TaskState, expected_plan_status: str
) -> None:
    service, saved = _service(_snapshot(task_status))
    plan = _plan()

    snapshot = service._refresh_plan_status("demo", plan)

    assert snapshot.status is task_status
    assert plan["status"] == expected_plan_status
    assert [item["status"] for item in saved] == [expected_plan_status]


def test_running_task_remains_executing_without_a_second_write() -> None:
    service, saved = _service(_snapshot(TaskState.RUNNING))
    plan = _plan()

    snapshot = service._refresh_plan_status("demo", plan)

    assert snapshot.status is TaskState.RUNNING
    assert plan["status"] == "EXECUTING"
    assert saved == []


@pytest.mark.parametrize(
    "snapshot",
    [
        None,
        _snapshot(TaskState.COMPLETED, owner="other-owner"),
        _snapshot(TaskState.COMPLETED, task_type="other_task"),
    ],
)
def test_missing_or_unowned_task_is_currently_left_unverified(
    snapshot,
) -> None:
    """Baseline for missing/history-cleaned/wrong-scope cases.

    This is the confirmed defect: the current method does not convert the
    plan to FAILED or COMPLETED when the Task proof is absent or unauthorized.
    A follow-up repair must expose UNKNOWN_OR_UNVERIFIED without inventing a
    terminal result or starting the device command again.
    """

    service, saved = _service(snapshot)
    plan = _plan()

    assert service._refresh_plan_status("demo", plan) is None
    assert plan["status"] == "EXECUTING"
    assert saved == []


def test_current_refresh_does_not_defense_check_snapshot_site_scope() -> None:
    """Evidence for the required same-site guard in the follow-up fix."""

    service, saved = _service(_snapshot(TaskState.COMPLETED, site_name="site-b"))
    plan = _plan()
    plan["site_id"] = "site-a"

    snapshot = service._refresh_plan_status("site-a", plan)

    assert snapshot is not None
    assert plan["status"] == "COMPLETED"
    assert len(saved) == 1


def test_terminal_mapping_is_idempotent() -> None:
    service, saved = _service(_snapshot(TaskState.COMPLETED))
    plan = _plan()

    service._refresh_plan_status("demo", plan)
    service._refresh_plan_status("demo", plan)

    assert plan["status"] == "COMPLETED"
    assert len(saved) == 1


def test_malformed_and_expired_plan_reads_do_not_write_fixture(tmp_path: Path) -> None:
    service = object.__new__(AcWebApplicationService)
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{not-json", encoding="utf-8")
    service._plan_path = lambda _plan_id: malformed

    with pytest.raises(AcWebActionError) as exc_info:
        service._plan_data("ac-plan-00000000000000000000000000000001", "demo")
    assert exc_info.value.code == "PLAN_NOT_FOUND"
    assert malformed.read_text(encoding="utf-8") == "{not-json"

    expired = tmp_path / "expired.json"
    expired.write_text(
        json.dumps(
            {
                **_plan("PREVIEW"),
                "expires_at": 0,
            }
        ),
        encoding="utf-8",
    )
    service._plan_path = lambda _plan_id: expired
    loaded = service._plan_data("ac-plan-00000000000000000000000000000001", "demo")
    assert loaded["status"] == "PREVIEW"
    assert json.loads(expired.read_text(encoding="utf-8"))["status"] == "PREVIEW"


def test_multi_site_fixture_keeps_plan_files_independent() -> None:
    service_a, saved_a = _service(_snapshot(TaskState.COMPLETED))
    service_b, saved_b = _service(_snapshot(TaskState.FAILED))
    plan_a = _plan()
    plan_a["site_id"] = "site-a"
    plan_b = _plan()
    plan_b["site_id"] = "site-b"

    service_a._refresh_plan_status("site-a", plan_a)
    service_b._refresh_plan_status("site-b", plan_b)

    assert plan_a["status"] == "COMPLETED"
    assert plan_b["status"] == "FAILED"
    assert saved_a[0]["status"] == "COMPLETED"
    assert saved_b[0]["status"] == "FAILED"
