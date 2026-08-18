from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from netconsole.core.paths import PathResolver
from netconsole.models.online_mr_application import (
    OnlineMrExecutorKind,
    OnlineMrMappingState,
    OnlineMrPhase,
    OnlineMrTaskSessionMapping,
)
from netconsole.models.task_snapshot import TaskEvent, TaskSnapshot
from netconsole.models.task_state import TaskState
from netconsole.repositories.online_mr_task_session_repository import (
    OnlineMrTaskSessionRepository,
)
from netconsole.repositories.task_repository import TaskRepository
from netconsole.services.job_center.task_result_rollout import (
    TaskResultRolloutService,
)
from netconsole.services.site_storage import SiteStorageError
from netconsole.services.site_sync import _apply_task_merge, _preview_task_merge
from scripts.maintenance.task_result_maintenance import TaskResultMaintenanceService


def _terminal_task(
    path: Path,
    task_id: str,
    result: dict[str, object],
    *,
    event_id: str | None = None,
) -> TaskRepository:
    repository = TaskRepository(path)
    rollout = TaskResultRolloutService(path)
    rollout_status = rollout.status()
    if rollout_status["task_result_storage_state"] == "LEGACY_DUAL_FULL":
        rollout.enable_dual_write(
            expected_revision=int(rollout_status["revision"]),
            reason="Site Return Package task_results fixture",
            updated_by="pytest",
        )
    time = "2026-08-15T02:00:00Z"
    snapshot = TaskSnapshot(
        task_id=task_id,
        task_type="vehicle_mr_online_refresh_all",
        task_name="刷新 Online MR",
        status=TaskState.COMPLETED,
        created_time=time,
        finished_time=time,
        updated_time=time,
        progress=100,
        result=result,
        source="agent",
        site_name="demo",
    )
    event = TaskEvent(
        event_id=event_id or f"finished-{task_id}",
        task_id=task_id,
        type="finished",
        time=time,
        source="agent",
        payload={"message": "done", "result": result},
    )
    assert repository.record(snapshot, event)
    # Seed historical task_results explicitly; current runtime terminal writes
    # intentionally remain full legacy payloads regardless of rollout state.
    maintenance = TaskResultMaintenanceService(
        PathResolver(app_root=path.parent, data_root=path.parent / "data"),
        site_id="demo",
        tasks_database=path,
        development_root=path.parent,
    )
    assert maintenance.backfill(
        apply=True, allow_development_root_only=True
    )["new_result_rows"] == 1
    return repository


def _mapping(
    task_id: str,
    *,
    session_id: str,
    updated_at: str = "2026-08-15T02:00:00Z",
    agent_id: str = "agent-1",
    agent_task_id: str = "agent-task-1",
) -> OnlineMrTaskSessionMapping:
    return OnlineMrTaskSessionMapping(
        controller_task_id=task_id,
        session_id=session_id,
        site_id="demo",
        device_id="device-1",
        device_name="MR-1",
        mr_id="mr-1",
        mr_name="MR-1",
        executor_kind=OnlineMrExecutorKind.AGENT,
        agent_id=agent_id,
        agent_task_id=agent_task_id,
        phase=OnlineMrPhase.TERMINAL,
        mapping_state=OnlineMrMappingState.TERMINAL,
        created_at="2026-08-15T01:00:00Z",
        updated_at=updated_at,
        terminal_at=updated_at,
    )


def test_site_return_tasks_merge_all_four_tables_and_is_idempotent(
    tmp_path: Path,
) -> None:
    local = tmp_path / "local.db"
    returned = tmp_path / "returned.db"
    TaskRepository(local)
    result = {"session_id": "session-1", "rows": 200}
    source = _terminal_task(returned, "controller-1", result)
    OnlineMrTaskSessionRepository(returned, site_id="demo").create(
        _mapping("controller-1", session_id="session-1")
    )

    preview = _preview_task_merge(local, returned, site_id="demo")
    assert preview["new_tasks"] == 1
    assert preview["conflicts"] == []
    merged = _apply_task_merge(local, returned, {}, site_id="demo")
    assert merged == {"new_tasks": 1, "updated_tasks": 0, "duplicate_tasks": 0}

    local_repository = TaskRepository(local)
    snapshot = local_repository.get("controller-1")
    assert snapshot is not None and snapshot.result == result
    assert local_repository.get_result(snapshot.result_id)["result"] == result
    assert (
        local_repository.list_events("controller-1")[-1]["payload"]["result"] == result
    )
    mapping = OnlineMrTaskSessionRepository(local, site_id="demo").get_by_task(
        "controller-1"
    )
    assert mapping is not None and mapping.session_id == "session-1"

    again = _apply_task_merge(local, returned, {}, site_id="demo")
    assert again == {"new_tasks": 0, "updated_tasks": 0, "duplicate_tasks": 1}
    with sqlite3.connect(local) as conn:
        assert conn.execute("SELECT COUNT(*) FROM task_results").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM task_events").fetchone()[0] == 1
        assert (
            conn.execute("SELECT COUNT(*) FROM online_mr_task_sessions").fetchone()[0]
            == 1
        )
    assert source.get("controller-1") is not None
    assert (
        TaskResultRolloutService(local).status()["task_result_storage_state"]
        == "LEGACY_DUAL_FULL"
    )


def test_site_return_ref_only_snapshot_and_event_read_through_after_merge(
    tmp_path: Path,
) -> None:
    local = tmp_path / "local.db"
    returned = tmp_path / "returned.db"
    TaskRepository(local)
    result = {"mode": "ref-only", "rows": 3}
    _terminal_task(returned, "controller-ref", result)
    with sqlite3.connect(returned) as conn:
        payload = json.loads(
            conn.execute(
                "SELECT payload_json FROM task_events WHERE task_id='controller-ref'"
            ).fetchone()[0]
        )
        payload.pop("result", None)
        conn.execute(
            "UPDATE task_snapshots SET result_json='' WHERE task_id='controller-ref'"
        )
        conn.execute(
            "UPDATE task_events SET payload_json=? WHERE task_id='controller-ref'",
            (json.dumps(payload, separators=(",", ":")),),
        )
        conn.commit()

    _apply_task_merge(local, returned, {}, site_id="demo")
    repository = TaskRepository(local)
    assert repository.get("controller-ref").result == result
    assert repository.list_events("controller-ref")[-1]["payload"]["result"] == result


def test_site_return_accepts_failed_snapshot_with_finished_result_authority(
    tmp_path: Path,
) -> None:
    local = tmp_path / "local.db"
    returned = tmp_path / "returned.db"
    TaskRepository(local)
    result = {"data_persisted": False, "worker_exit_code": 1}
    _terminal_task(returned, "legacy-failed-finished", result)
    with sqlite3.connect(returned) as conn:
        conn.execute(
            "UPDATE task_snapshots SET status='FAILED' "
            "WHERE task_id='legacy-failed-finished'"
        )
        conn.commit()

    _apply_task_merge(local, returned, {}, site_id="demo")

    snapshot = TaskRepository(local).get("legacy-failed-finished")
    assert snapshot is not None
    assert snapshot.status == TaskState.FAILED
    assert snapshot.result == result


def test_site_return_preserves_artifact_projection_result_authority(
    tmp_path: Path,
) -> None:
    local = tmp_path / "local.db"
    returned = tmp_path / "returned.db"
    TaskRepository(local)
    terminal_result = {"artifact_id": "report-1", "available": False, "rows": 12}
    source = _terminal_task(returned, "artifact-projection", terminal_result)
    terminal = source.get("artifact-projection")
    assert terminal is not None
    projection = {"artifact_id": "report-1", "available": True, "rows": 12}
    assert source.record(
        replace(
            terminal,
            result=projection,
            updated_time="2026-08-15T02:01:00Z",
        ),
        TaskEvent(
            event_id="artifact-finalized",
            task_id="artifact-projection",
            type="artifact_finalized",
            time="2026-08-15T02:01:00Z",
            source="artifact_reconciliation",
            payload={"message": "ready", "result": projection},
        ),
    )

    _apply_task_merge(local, returned, {}, site_id="demo")

    repository = TaskRepository(local)
    snapshot = repository.get("artifact-projection")
    assert snapshot is not None
    assert snapshot.result == projection
    assert snapshot.result_id == ""
    # Historical result rows are retained; the active snapshot no longer
    # points at the obsolete terminal result after the full projection update.
    assert repository.task_result_count() == 1


@pytest.mark.parametrize(
    "invalid_kind",
    [
        "wrong_task",
        "wrong_event_type",
        "wrong_full_result",
        "wrong_snapshot_full_result",
    ],
)
def test_site_return_rejects_invalid_event_result_authority(
    tmp_path: Path,
    invalid_kind: str,
) -> None:
    local = tmp_path / "local.db"
    returned = tmp_path / "returned.db"
    TaskRepository(local)
    authority_repository = _terminal_task(
        returned,
        "authority-task",
        {"rows": 1},
    )
    _terminal_task(returned, "target-task", {"rows": 2})
    authority = authority_repository.get("authority-task")
    assert authority is not None
    with sqlite3.connect(returned) as conn:
        if invalid_kind == "wrong_event_type":
            conn.execute(
                "UPDATE task_events SET event_type='error' "
                "WHERE task_id='target-task'"
            )
        elif invalid_kind == "wrong_snapshot_full_result":
            conn.execute(
                "UPDATE task_snapshots SET result_json=? WHERE task_id='target-task'",
                ('{"rows":999}',),
            )
        else:
            payload = json.loads(
                conn.execute(
                    "SELECT payload_json FROM task_events WHERE task_id='target-task'"
                ).fetchone()[0]
            )
            if invalid_kind == "wrong_task":
                payload["result_id"] = authority.result_id
                payload["result_hash"] = authority.result_hash
                payload.pop("result", None)
            else:
                payload["result"] = {"rows": 999}
            conn.execute(
                "UPDATE task_events SET payload_json=? WHERE task_id='target-task'",
                (json.dumps(payload, separators=(",", ":")),),
            )
        conn.commit()

    with pytest.raises(SiteStorageError, match="task_result|终态事件类型|完整 result"):
        _apply_task_merge(local, returned, {}, site_id="demo")
    assert TaskRepository(local).get("target-task") is None


def test_site_return_accepts_registered_directory_name_as_site_alias(
    tmp_path: Path,
) -> None:
    local = tmp_path / "local.db"
    returned = tmp_path / "returned.db"
    TaskRepository(local)
    _terminal_task(returned, "controller-alias", {"rows": 2})
    OnlineMrTaskSessionRepository(returned, site_id="Line 12").create(
        replace(
            _mapping("controller-alias", session_id="session-alias"),
            site_id="Line 12",
        )
    )

    with pytest.raises(SiteStorageError, match="局点不匹配"):
        _preview_task_merge(local, returned, site_id="legacy-line-12")
    preview = _preview_task_merge(
        local,
        returned,
        site_id="legacy-line-12",
        site_aliases={"Line 12"},
    )
    assert preview["new_tasks"] == 1
    result = _apply_task_merge(
        local,
        returned,
        {},
        site_id="legacy-line-12",
        site_aliases={"Line 12"},
    )
    assert result["new_tasks"] == 1
    assert TaskRepository(local).get("controller-alias").result == {"rows": 2}


def test_site_return_result_conflict_fails_closed_without_partial_tasks_merge(
    tmp_path: Path,
) -> None:
    local = tmp_path / "local.db"
    returned = tmp_path / "returned.db"
    source = _terminal_task(returned, "controller-conflict", {"rows": 7})
    snapshot = source.get("controller-conflict")
    assert snapshot is not None
    TaskRepository(local)
    with sqlite3.connect(local) as conn:
        authority = source.get_result(snapshot.result_id)
        conn.execute(
            """
            INSERT INTO task_results VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot.result_id,
                "controller-conflict",
                "finished",
                '{"rows":8}',
                authority["sha256"],
                authority["byte_size"],
                authority["schema_version"],
                authority["created_time"],
            ),
        )
        conn.commit()

    with pytest.raises(SiteStorageError, match="不可覆盖冲突"):
        _apply_task_merge(local, returned, {}, site_id="demo")
    with sqlite3.connect(local) as conn:
        assert conn.execute("SELECT COUNT(*) FROM task_snapshots").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM task_events").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM task_results").fetchone()[0] == 1


def test_site_return_event_identity_conflict_fails_closed(tmp_path: Path) -> None:
    local = tmp_path / "local.db"
    returned = tmp_path / "returned.db"
    _terminal_task(local, "controller-event", {"rows": 1}, event_id="same-event")
    _terminal_task(returned, "controller-event", {"rows": 2}, event_id="same-event")

    with pytest.raises(SiteStorageError, match="不可覆盖冲突"):
        _apply_task_merge(local, returned, {}, site_id="demo")
    assert TaskRepository(local).get("controller-event").result == {"rows": 1}


def test_site_return_online_mr_identity_conflict_never_uses_newer_wins(
    tmp_path: Path,
) -> None:
    local = tmp_path / "local.db"
    returned = tmp_path / "returned.db"
    _terminal_task(local, "controller-local", {"rows": 1})
    OnlineMrTaskSessionRepository(local, site_id="demo").create(
        _mapping("controller-local", session_id="session-shared")
    )
    _terminal_task(returned, "controller-returned", {"rows": 2})
    OnlineMrTaskSessionRepository(returned, site_id="demo").create(
        _mapping(
            "controller-returned",
            session_id="session-shared",
            updated_at="2026-08-15T03:00:00Z",
            agent_task_id="agent-task-2",
        )
    )

    with pytest.raises(SiteStorageError, match="不可覆盖冲突"):
        _apply_task_merge(local, returned, {}, site_id="demo")
    assert TaskRepository(local).get("controller-returned") is None
    assert (
        OnlineMrTaskSessionRepository(local, site_id="demo")
        .get_by_session("session-shared")
        .controller_task_id
        == "controller-local"
    )


@pytest.mark.parametrize(
    "invalid_kind",
    ["missing_controller_task", "incomplete_agent_reference", "wrong_site"],
)
def test_site_return_online_mr_invalid_references_are_rejected(
    tmp_path: Path,
    invalid_kind: str,
) -> None:
    local = tmp_path / "local.db"
    returned = tmp_path / "returned.db"
    TaskRepository(local)
    TaskRepository(returned)
    controller_task_id = "controller-invalid"
    if invalid_kind != "missing_controller_task":
        _terminal_task(returned, controller_task_id, {"rows": 1})
    mapping = _mapping(controller_task_id, session_id="session-invalid")
    if invalid_kind == "incomplete_agent_reference":
        mapping = OnlineMrTaskSessionMapping(
            **{
                **mapping.__dict__,
                "agent_task_id": "",
            }
        )
    if invalid_kind == "wrong_site":
        mapping = OnlineMrTaskSessionMapping(
            **{
                **mapping.__dict__,
                "site_id": "other-site",
            }
        )
    OnlineMrTaskSessionRepository(returned, site_id=mapping.site_id).create(mapping)

    with pytest.raises(SiteStorageError, match="引用|局点"):
        _apply_task_merge(local, returned, {}, site_id="demo")
    with sqlite3.connect(local) as conn:
        assert conn.execute("SELECT COUNT(*) FROM task_snapshots").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM task_events").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM task_results").fetchone()[0] == 0
