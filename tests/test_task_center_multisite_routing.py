from __future__ import annotations

from pathlib import Path

import pytest

from netconsole.core.paths import PathResolver
from netconsole.models.task_state import TaskState
from netconsole.repositories.task_repository import TaskRepository, TaskRetiredError
from netconsole.services.background_job import BackgroundJob
from netconsole.services.job_center.job_events import finished_event, progress_event
from netconsole.services.job_center.query_service import JobCenterQueryService
from netconsole.services.job_center.task_application_service import TaskApplicationService
from netconsole.services.job_center.worker_protocol import encode_event


SITE_A = "hz10"
SITE_B = "nb12"


def _service(tmp_path: Path, *, site_name: str = SITE_A) -> TaskApplicationService:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    return TaskApplicationService(
        paths=paths,
        site_name=site_name,
        reconcile_on_start=False,
    )


def _prepare_local(service: TaskApplicationService, task_id: str) -> None:
    service.prepare(
        BackgroundJob(
            job_id=task_id,
            task_type="multisite_test",
            params={"site_name": SITE_A, "task_name": task_id},
        )
    )
    service.mark_running(task_id)


def _stored(service: TaskApplicationService, site_name: str, task_id: str):
    return TaskRepository(service.paths.site_tasks_db_path(site_name)).get(task_id)


def test_local_complete_and_event_queries_follow_job_site_after_current_site_change(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    task_id = "local-complete-site-a"
    _prepare_local(service, task_id)
    service.feed_stdout(
        task_id,
        encode_event(progress_event(task_id, "collect", 1, 2, "采集中")).encode("utf-8"),
    )

    service.site_name = SITE_B
    active = service.get_task(task_id)
    active_events = service.list_events(task_id)
    assert active is not None
    assert active.status is TaskState.RUNNING
    assert any(event["type"] == "progress" for event in active_events)
    service.feed_stdout(
        task_id,
        encode_event(finished_event(task_id, {"count": 1})).encode("utf-8"),
    )
    service.complete(task_id, 0)

    snapshot = _stored(service, SITE_A, task_id)
    assert snapshot is not None
    assert snapshot.status is TaskState.COMPLETED
    assert _stored(service, SITE_B, task_id) is None
    assert service.get_task(task_id, site_name=SITE_A).status is TaskState.COMPLETED
    assert {event["type"] for event in service.list_events(task_id, site_name=SITE_A)} >= {
        "progress",
        "finished",
    }


def test_local_cancel_uses_active_job_site_after_current_site_change(tmp_path: Path) -> None:
    service = _service(tmp_path)
    task_id = "local-cancel-site-a"
    _prepare_local(service, task_id)
    service.site_name = SITE_B

    assert service.cancel_task(task_id) is True
    snapshot = _stored(service, SITE_A, task_id)
    assert snapshot is not None
    assert snapshot.status is TaskState.STOPPING
    assert _stored(service, SITE_B, task_id) is None


@pytest.mark.parametrize(
    ("finalizer", "expected"),
    [
        ("fail_start", TaskState.FAILED),
        ("abandon", TaskState.CANCELLED),
    ],
)
def test_local_terminal_callbacks_keep_original_site(
    tmp_path: Path,
    finalizer: str,
    expected: TaskState,
) -> None:
    service = _service(tmp_path)
    task_id = f"local-{finalizer}-site-a"
    service.prepare(
        BackgroundJob(
            job_id=task_id,
            task_type="multisite_test",
            params={"site_name": SITE_A},
        )
    )
    service.site_name = SITE_B

    if finalizer == "fail_start":
        service.fail_start(task_id, "启动失败")
    else:
        service.abandon(task_id)

    snapshot = _stored(service, SITE_A, task_id)
    assert snapshot is not None
    assert snapshot.status is expected
    assert _stored(service, SITE_B, task_id) is None


def test_protocol_failure_keeps_job_site_until_complete_persists_terminal_event(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    task_id = "local-protocol-failure-site-a"
    _prepare_local(service, task_id)
    service.site_name = SITE_B

    assert service.feed_stdout(task_id, b"{not-valid-utf8\xff") is True
    service.complete(task_id, 1)

    snapshot = _stored(service, SITE_A, task_id)
    assert snapshot is not None
    assert snapshot.status is TaskState.FAILED
    assert snapshot.result["error_code"] == "WORKER_PROTOCOL_CORRUPTED"
    assert _stored(service, SITE_B, task_id) is None


@pytest.mark.parametrize(
    ("terminal_type", "payload", "expected"),
    [
        ("finished", {"result": {"ok": True}}, TaskState.COMPLETED),
        ("error", {"error": "agent failed"}, TaskState.FAILED),
        ("cancelled", {"message": "agent cancelled"}, TaskState.CANCELLED),
    ],
)
def test_external_events_follow_active_site_after_current_site_change(
    tmp_path: Path,
    terminal_type: str,
    payload: dict[str, object],
    expected: TaskState,
) -> None:
    service = _service(tmp_path)
    task_id = f"external-{terminal_type}-site-a"
    service.create_external_task(
        task_id=task_id,
        task_type="multisite_external_test",
        task_name=task_id,
        source="agent",
        site_name=SITE_A,
    )
    service.site_name = SITE_B

    service.record_external_event(
        task_id,
        "progress",
        {"stage": "collect", "current": 1, "total": 2},
        source="agent",
    )
    service.record_external_event(
        task_id,
        "log",
        {"message": "Agent 日志"},
        source="agent",
    )
    service.record_external_event(
        task_id,
        terminal_type,
        payload,
        source="agent",
    )

    snapshot = _stored(service, SITE_A, task_id)
    assert snapshot is not None
    assert snapshot.status is expected
    assert {event["type"] for event in service.list_events(task_id, site_name=SITE_A)} >= {
        "progress",
        "log",
        terminal_type,
    }
    assert _stored(service, SITE_B, task_id) is None


def test_explicit_site_queries_work_after_restart_without_scanning_other_sites(
    tmp_path: Path,
) -> None:
    first = _service(tmp_path)
    task_id = "history-site-a"
    first.create_external_task(
        task_id=task_id,
        task_type="multisite_history_test",
        task_name=task_id,
        source="agent",
        site_name=SITE_A,
    )
    first.record_external_event(
        task_id,
        "finished",
        {"result": {"site": SITE_A}},
        source="agent",
    )

    restarted = _service(tmp_path, site_name=SITE_B)
    assert restarted._job_sites == {}
    assert restarted.get_task(task_id) is None
    assert restarted.get_task(task_id, site_name=SITE_A).status is TaskState.COMPLETED
    assert restarted.list_events(task_id, site_name=SITE_A)

    query = JobCenterQueryService(restarted.paths)
    assert [item.site_name for item in query.list_tasks(SITE_A)] == [SITE_A]
    assert query.get_task(SITE_A, task_id) is not None
    assert query.get_task(SITE_B, task_id) is None


def test_same_task_id_is_distinguished_by_site_scoped_repository_and_query(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    task_id = "same-task-id"
    for site_name in (SITE_A, SITE_B):
        service.create_external_task(
            task_id=task_id,
            task_type="multisite_same_id_test",
            task_name=f"{site_name} task",
            source="agent",
            site_name=site_name,
        )
        service.record_external_event(
            task_id,
            "finished",
            {"result": {"site": site_name}},
            source="agent",
            site_name=site_name,
        )

    assert service.get_task(task_id, site_name=SITE_A).task_name == "hz10 task"
    assert service.get_task(task_id, site_name=SITE_B).task_name == "nb12 task"
    query = JobCenterQueryService(service.paths)
    assert query.get_task(SITE_A, task_id).site_name == SITE_A
    assert query.get_task(SITE_B, task_id).site_name == SITE_B


def test_cleanup_with_explicit_site_does_not_delete_same_id_from_other_site(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    task_id = "cleanup-same-task-id"
    for site_name in (SITE_A, SITE_B):
        service.create_external_task(
            task_id=task_id,
            task_type="multisite_cleanup_test",
            task_name=task_id,
            source="agent",
            site_name=site_name,
        )
        service.record_external_event(
            task_id,
            "finished",
            {"result": {}},
            source="agent",
            site_name=site_name,
        )

    snapshot_a = _stored(service, SITE_A, task_id)
    snapshot_b = _stored(service, SITE_B, task_id)
    assert snapshot_a is not None
    assert snapshot_b is not None
    result = service.cleanup_tasks([task_id], site_name=SITE_A)

    assert result["deleted_task_ids"] == [task_id]
    assert _stored(service, SITE_A, task_id) is None
    assert _stored(service, SITE_B, task_id) is not None
    with pytest.raises(TaskRetiredError):
        TaskRepository(service.paths.site_tasks_db_path(SITE_A)).save(snapshot_a)
    TaskRepository(service.paths.site_tasks_db_path(SITE_B)).save(snapshot_b)
