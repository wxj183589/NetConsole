from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from netconsole.backend.api.main import create_app
from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.models.task_snapshot import TaskEvent, TaskSnapshot
from netconsole.models.task_state import TaskState
from netconsole.repositories.task_repository import TaskRepository
from netconsole.services.job_center.task_application_service import TaskApplicationService


def _snapshot(
    task_id: str,
    status: TaskState,
    *,
    finished_time: str = "",
    error_message: str = "",
    result: dict[str, object] | None = None,
    task_type: str = "cleanup_test",
    site_name: str = "demo",
    resource_keys: list[str] | None = None,
) -> TaskSnapshot:
    updated_time = finished_time or "2026-07-29T01:00:00Z"
    return TaskSnapshot(
        task_id=task_id,
        task_type=task_type,
        task_name=task_id,
        status=status,
        created_time="2026-07-01T00:00:00Z",
        started_time="2026-07-01T00:00:01Z",
        finished_time=finished_time,
        updated_time=updated_time,
        error_message=error_message,
        result=dict(result or {}),
        site_name=site_name,
        resource_keys=list(resource_keys or []),
    )


def _repository(tmp_path: Path) -> tuple[PathResolver, TaskRepository]:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    return paths, TaskRepository(paths.site_tasks_db_path("demo"))


def test_cleanup_soft_dismisses_only_eligible_history_and_preserves_artifacts(
    tmp_path: Path,
) -> None:
    paths, repository = _repository(tmp_path)
    artifact = tmp_path / "reports" / "keep.xlsx"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"report")
    repository.save(_snapshot("running", TaskState.RUNNING))
    repository.save(
        _snapshot(
            "success",
            TaskState.COMPLETED,
            finished_time="2026-07-28T01:00:00Z",
            result={"output_path": str(artifact)},
        )
    )
    repository.save(
        _snapshot(
            "cancelled",
            TaskState.CANCELLED,
            finished_time="2026-07-28T02:00:00Z",
        )
    )
    repository.save(
        _snapshot(
            "warning",
            TaskState.COMPLETED,
            finished_time="2026-06-01T01:00:00Z",
            result={"business_outcome": "PARTIAL_SUCCESS", "failed_count": 2},
        )
    )
    repository.save(
        _snapshot(
            "failed-unread",
            TaskState.FAILED,
            finished_time="2026-06-01T02:00:00Z",
            error_message="worker exited",
        )
    )
    repository.record(
        _snapshot(
            "failed-resolved",
            TaskState.FAILED,
            finished_time="2026-06-01T03:00:00Z",
            error_message="worker exited",
        ),
        TaskEvent(
            event_id="failed-resolved-event",
            task_id="failed-resolved",
            type="error",
            time="2026-06-01T03:00:00Z",
            payload={"error": "worker exited"},
        ),
    )
    repository.acknowledge_attention_tasks(task_ids=["failed-resolved"])
    with sqlite3.connect(paths.site_tasks_db_path("demo")) as conn:
        expirations = dict(
            conn.execute(
                "SELECT task_id, expires_at FROM task_snapshots"
            ).fetchall()
        )
    assert expirations["success"] == "2026-08-04T01:00:00.000Z"
    assert expirations["cancelled"] == "2026-08-04T02:00:00.000Z"
    assert expirations["warning"] == "2026-07-01T01:00:00.000Z"
    assert expirations["failed-unread"] == "2026-07-01T02:00:00.000Z"

    preview = repository.cleanup_history(
        "completed_and_expired",
        include_states=["RUNNING", "COMPLETED", "FAILED", "CANCELLED"],
        dismissed_by="test",
        dry_run=True,
    )

    assert preview["matched"] == 3
    assert preview["dismissed"] == 0
    assert preview["skipped_active"] == 1
    assert preview["skipped_unacknowledged"] == 2
    assert preview["counts"] == {
        "completed": 1,
        "cancelled": 1,
        "expired": 1,
        "alerts": 0,
    }
    assert {item.task_id for item in repository.list(limit=20)} == {
        "running",
        "success",
        "cancelled",
        "warning",
        "failed-unread",
        "failed-resolved",
    }

    result = repository.cleanup_history(
        "completed_and_expired",
        include_states=["RUNNING", "COMPLETED", "FAILED", "CANCELLED"],
        dismissed_by="test",
    )

    assert result["dismissed"] == 3
    assert set(result["task_ids"]) == {"success", "cancelled", "failed-resolved"}
    assert {item.task_id for item in repository.list(limit=20)} == {
        "running",
        "warning",
        "failed-unread",
    }
    assert artifact.read_bytes() == b"report"
    assert repository.get("success") is not None
    assert repository.list_events("failed-resolved")
    with sqlite3.connect(paths.site_tasks_db_path("demo")) as conn:
        row = conn.execute(
            """
            SELECT dismissed_at, dismissed_by, dismiss_reason
            FROM task_snapshots WHERE task_id = 'success'
            """
        ).fetchone()
        assert row is not None
        assert row[0]
        assert row[1:] == ("test", "completed_and_expired")


def test_failed_or_warning_task_requires_acknowledgement_before_single_dismiss(
    tmp_path: Path,
) -> None:
    _paths, repository = _repository(tmp_path)
    repository.save(
        _snapshot(
            "warning",
            TaskState.COMPLETED,
            finished_time="2026-07-28T01:00:00Z",
            result={"business_outcome": "WARNING"},
        )
    )

    blocked = repository.dismiss_task("warning", dismissed_by="test")
    assert blocked["dismissed"] == 0
    assert blocked["skipped_unacknowledged"] == 1

    acknowledged = repository.acknowledge_attention_tasks(task_ids=["warning"])
    assert acknowledged["task_ids"] == ["warning"]
    dismissed = repository.dismiss_task("warning", dismissed_by="test")
    assert dismissed["task_ids"] == ["warning"]
    assert repository.list(limit=20) == []
    assert repository.get("warning") is not None


def test_cleanup_api_publishes_incremental_event_and_rejects_file_deletion(
    tmp_path: Path,
) -> None:
    paths, repository = _repository(tmp_path)
    repository.save(
        _snapshot(
            "success",
            TaskState.COMPLETED,
            finished_time="2026-07-28T01:00:00Z",
        )
    )
    repository.save(_snapshot("running", TaskState.RUNNING))
    task_service = TaskApplicationService(
        paths=paths,
        site_name="demo",
        reconcile_on_start=False,
    )
    Database(paths.site_db_path("demo")).initialize()
    app = create_app(
        RuntimeMode.TEST,
        paths=paths,
        task_service=task_service,
        frontend_dist=tmp_path / "missing",
    )
    subscription = task_service.events.open_stream()

    with TestClient(app) as client:
        preview = client.post(
            "/api/job-center/cleanup",
            json={
                "cleanup_type": "completed",
                "include_states": ["COMPLETED", "RUNNING"],
                "delete_artifacts": False,
                "dry_run": True,
            },
        )
        assert preview.status_code == 200
        assert preview.json()["matched"] == 1
        assert preview.json()["skipped_active"] == 1
        assert client.get("/api/job-center/tasks").json()

        cleanup = client.post(
            "/api/job-center/cleanup",
            json={
                "cleanup_type": "completed",
                "delete_artifacts": False,
            },
        )
        assert cleanup.status_code == 200
        assert cleanup.json()["task_ids"] == ["success"]
        assert [item["id"] for item in client.get("/api/job-center/tasks").json()] == [
            "running"
        ]

        forbidden = client.post(
            "/api/job-center/cleanup",
            json={
                "cleanup_type": "all_history",
                "delete_artifacts": True,
            },
        )
        assert forbidden.status_code == 409
        mismatch = client.post(
            "/api/job-center/cleanup",
            json={"cleanup_type": "completed", "site_id": "another-site"},
        )
        assert mismatch.status_code == 409

    event = subscription.get(timeout=1)
    subscription.close()
    assert event["type"] == "tasks.dismissed"
    assert event["event_type"] == "tasks.dismissed"
    assert event["payload"]["task_ids"] == ["success"]
    assert event["payload"]["summary"] == {
        "running": 1,
        "queued": 0,
        "failed": 0,
        "warning": 0,
    }


def test_bounded_retention_keeps_recent_scope_and_protected_domain_tasks(
    tmp_path: Path,
) -> None:
    _paths, repository = _repository(tmp_path)
    for index in range(12):
        repository.save(
            _snapshot(
                f"ordinary-{index}",
                TaskState.COMPLETED,
                finished_time=f"2026-07-{index + 1:02d}T00:00:00Z",
            )
        )
    repository.save(
        _snapshot(
            "other-scope",
            TaskState.COMPLETED,
            finished_time="2026-08-01T00:00:00Z",
            task_type="other_task",
        )
    )
    repository.save(
        _snapshot(
            "mesh-import",
            TaskState.COMPLETED,
            finished_time="2020-01-01T00:00:00Z",
            task_type="mesh_log_import",
            resource_keys=["mesh_source:source-1"],
        )
    )
    repository.save(_snapshot("active", TaskState.RUNNING))
    repository.record(
        _snapshot(
            "ordinary-1",
            TaskState.COMPLETED,
            finished_time="2026-07-02T00:00:00Z",
        ),
        TaskEvent(
            event_id="ordinary-1-event",
            task_id="ordinary-1",
            type="finished",
            time="2026-07-02T00:00:00Z",
            payload={"result": {"old": True}},
        ),
    )
    with sqlite3.connect(repository.db_path) as conn:
        conn.execute(
            "CREATE TABLE online_mr_task_sessions (controller_task_id TEXT PRIMARY KEY)"
        )
        conn.execute(
            "INSERT INTO online_mr_task_sessions(controller_task_id) VALUES (?)",
            ("mapped",),
        )
        conn.commit()
    repository.save(
        _snapshot(
            "mapped",
            TaskState.COMPLETED,
            finished_time="2020-01-01T00:00:00Z",
            task_type="ordinary_task",
        )
    )

    preview = repository.retain_recent_terminal_tasks(dry_run=True)
    assert preview["matched"] == 2
    assert preview["protected"] == 2
    assert preview["skipped_active"] == 1

    result = repository.retain_recent_terminal_tasks()
    assert result["deleted"] == 2
    assert repository.get("ordinary-0") is None
    assert repository.get("ordinary-1") is None
    assert repository.get("ordinary-2") is not None
    assert repository.get("mesh-import") is not None
    assert repository.get("mapped") is not None
    assert repository.get("active") is not None
    with sqlite3.connect(repository.db_path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM task_events WHERE task_id='ordinary-0'"
        ).fetchone()[0] == 0


def test_job_center_owner_exposes_bounded_retention_without_soft_dismiss_event(
    tmp_path: Path,
) -> None:
    paths, repository = _repository(tmp_path)
    for index in range(11):
        repository.save(
            _snapshot(
                f"owner-{index}",
                TaskState.COMPLETED,
                finished_time=f"2026-07-{index + 1:02d}T00:00:00Z",
            )
        )
    service = TaskApplicationService(paths=paths, site_name="demo", reconcile_on_start=False)
    stream = service.events.open_stream()
    result = service.cleanup_history_tasks("bounded_retention", site_name="demo")
    assert result["deleted"] == 1
    assert result["dismissed"] == 0
    event = stream.get(timeout=1)
    stream.close()
    assert event["type"] == "tasks.retention_applied"
