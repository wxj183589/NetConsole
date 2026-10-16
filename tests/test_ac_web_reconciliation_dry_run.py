from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from netconsole.models.task_state import TaskState
from scripts.maintenance.ac_web_reconciliation_dry_run import (
    PlanFile,
    classify_plans,
)


def _plan(tmp_path: Path, *, record_id: str, plan_id: str, task_id: str, status: str = "EXECUTING") -> PlanFile:
    path = tmp_path / f"{plan_id}.json"
    path.write_text("{}", encoding="utf-8")
    return PlanFile(
        record_id=record_id,
        path=path,
        data={
            "plan_id": plan_id,
            "site_id": "demo",
            "task_id": task_id,
            "status": status,
        },
        sha256="",
        size=2,
        modified_ns=0,
    )


def _evidence(snapshot: object | None, *, tombstoned: bool = False):
    from scripts.maintenance.ac_web_reconciliation_dry_run import TaskEvidence

    return TaskEvidence(
        snapshot=snapshot,
        db_path=None,
        tombstoned=tombstoned,
        tombstone_reason="explicit_task_cleanup" if tombstoned else "",
    )


def _snapshot(task_id: str, status: TaskState, *, plan_id: str = ""):
    return SimpleNamespace(
        task_id=task_id,
        task_type="ac_command_action_execute",
        status=status,
        owner="web_ac",
        source="local",
        site_name="demo",
        result={"plan_id": plan_id} if plan_id else {},
    )


def test_dry_run_uses_product_classifier_and_keeps_terminal_candidate(tmp_path: Path) -> None:
    plan = _plan(tmp_path, record_id="P01", plan_id="ac-plan-" + "a" * 32, task_id="task-1")
    rows = classify_plans(
        [plan],
        {"task-1": _evidence(_snapshot("task-1", TaskState.COMPLETED, plan_id=plan.data["plan_id"]))},
    )
    assert rows[0]["effective_status"] == "COMPLETED"
    assert rows[0]["evidence_level"] == "DIRECT_PLAN_ID"
    assert rows[0]["candidate"] is True


def test_dry_run_keeps_cleaned_task_unknown(tmp_path: Path) -> None:
    plan = _plan(tmp_path, record_id="P01", plan_id="ac-plan-" + "b" * 32, task_id="task-2")
    rows = classify_plans([plan], {"task-2": _evidence(None, tombstoned=True)})
    assert rows[0]["effective_status"] == "UNKNOWN_OR_UNVERIFIED"
    assert rows[0]["reason"] == "TASK_HISTORY_CLEANED"
    assert rows[0]["candidate"] is False


def test_dry_run_rejects_active_and_scope_mismatch(tmp_path: Path) -> None:
    active = _plan(tmp_path, record_id="P01", plan_id="ac-plan-" + "c" * 32, task_id="task-3")
    mismatch = _plan(tmp_path, record_id="P02", plan_id="ac-plan-" + "d" * 32, task_id="task-4")
    rows = classify_plans(
        [active, mismatch],
        {
            "task-3": _evidence(_snapshot("task-3", TaskState.RUNNING, plan_id=active.data["plan_id"])),
            "task-4": _evidence(
                SimpleNamespace(
                    task_id="task-4",
                    task_type="ac_command_action_execute",
                    status=TaskState.COMPLETED,
                    owner="web_ac",
                    source="local",
                    site_name="other-site",
                    result={"plan_id": mismatch.data["plan_id"]},
                )
            ),
        },
    )
    assert rows[0]["effective_status"] == "EXECUTING"
    assert rows[0]["candidate"] is False
    assert rows[1]["reason"] == "TASK_SITE_MISMATCH"
    assert rows[1]["candidate"] is False


def test_dry_run_rejects_ambiguous_legacy_reverse_link(tmp_path: Path) -> None:
    first = _plan(tmp_path, record_id="P01", plan_id="ac-plan-" + "e" * 32, task_id="task-5")
    second = _plan(tmp_path, record_id="P02", plan_id="ac-plan-" + "f" * 32, task_id="task-5")
    rows = classify_plans(
        [first, second],
        {"task-5": _evidence(_snapshot("task-5", TaskState.COMPLETED))},
    )
    assert [row["reason"] for row in rows] == ["TASK_IDENTITY_AMBIGUOUS", "TASK_IDENTITY_AMBIGUOUS"]
    assert not any(row["candidate"] for row in rows)
