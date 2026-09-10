from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient

from netconsole.core import app_logger
from netconsole.backend.api.main import create_app
from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.core.runtime_environment import write_data_environment
from netconsole.core.runtime_mode import DataEnvironmentInfo, DataEnvironmentMode, RuntimeMode
from netconsole.models.task_snapshot import TaskEvent, TaskSnapshot
from netconsole.models.task_state import TaskState
from netconsole.models.api.job_center import JobCenterCleanupResultDTO
from netconsole.repositories.task_repository import TaskRepository
from netconsole.services.job_center.task_application_service import TaskApplicationService


def _snapshot(
    task_id: str,
    status: TaskState,
    *,
    finished_time: str = "",
    error_message: str = "",
    result: dict[str, object] | None = None,
) -> TaskSnapshot:
    updated_time = finished_time or "2026-07-29T01:00:00Z"
    return TaskSnapshot(
        task_id=task_id,
        task_type="cleanup_test",
        task_name=task_id,
        status=status,
        created_time="2026-07-01T00:00:00Z",
        started_time="2026-07-01T00:00:01Z",
        finished_time=finished_time,
        updated_time=updated_time,
        error_message=error_message,
        result=dict(result or {}),
        site_name="demo",
    )


def _repository(tmp_path: Path) -> tuple[PathResolver, TaskRepository]:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    return paths, TaskRepository(paths.site_tasks_db_path("demo"))


def test_cleanup_result_contract_exposes_dismissed_by_and_rejects_unknown_fields() -> None:
    result = JobCenterCleanupResultDTO.model_validate(
        {"task_ids": ["task-1"], "dismissed_by": "local-user"}
    )

    assert result.dismissed_by == "local-user"
    with pytest.raises(ValidationError):
        JobCenterCleanupResultDTO.model_validate(
            {
                "task_ids": ["task-1"],
                "dismissed_by": "local-user",
                "unknown_extra": True,
            }
        )


def test_task_center_cleanup_retires_operational_rows_and_preserves_artifacts(
    tmp_path: Path,
) -> None:
    paths, repository = _repository(tmp_path)
    artifact = tmp_path / "reports" / "keep.xlsx"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"report")
    repository.save(_snapshot("running", TaskState.RUNNING))
    repository.save(_snapshot("pending", TaskState.PENDING))
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
    manifest_root = paths.rail_transit_root("demo") / "web_artifacts" / "manifests"
    manifest_root.mkdir(parents=True, exist_ok=True)
    (manifest_root / "success.json").write_text(
        '{"task_id":"success","artifact_id":"keep.xlsx"}', encoding="utf-8"
    )
    app_logger.log_info(
        "SITE_IMPORT_COMPLETED",
        "task_id=success site_import 成功",
        log_path=paths.app_log_path,
    )
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

    task_service = TaskApplicationService(
        paths=paths, site_name="demo", reconcile_on_start=False
    )
    preview = task_service.cleanup_history_tasks(
        "completed_and_expired",
        site_name="demo",
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
        "pending",
        "success",
        "cancelled",
        "warning",
        "failed-unread",
        "failed-resolved",
    }

    result = task_service.cleanup_history_tasks(
        "completed_and_expired",
        site_name="demo",
        include_states=["RUNNING", "COMPLETED", "FAILED", "CANCELLED"],
        dismissed_by="test",
    )

    assert result["dismissed"] == 3
    assert set(result["task_ids"]) == {"success", "cancelled", "failed-resolved"}
    assert {item.task_id for item in repository.list(limit=20)} == {
        "running",
        "pending",
        "warning",
        "failed-unread",
    }
    assert artifact.read_bytes() == b"report"
    assert app_logger.get_logs(
        keyword="task_id=success", log_path=paths.app_log_path
    ).rows
    assert repository.get("success") is None
    assert repository.list_events("failed-resolved") == []
    with sqlite3.connect(paths.site_tasks_db_path("demo")) as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) FROM task_snapshots WHERE task_id = 'success'
            """
        ).fetchone()
        assert row == (0,)
        assert conn.execute(
            "SELECT COUNT(*) FROM task_retention_tombstones WHERE task_id='success'"
        ).fetchone() == (1,)


def test_failed_or_warning_task_requires_acknowledgement_before_single_dismiss(
    tmp_path: Path,
) -> None:
    paths, repository = _repository(tmp_path)
    repository.save(
        _snapshot(
            "warning",
            TaskState.COMPLETED,
            finished_time="2026-07-28T01:00:00Z",
            result={"business_outcome": "WARNING"},
        )
    )

    service = TaskApplicationService(paths=paths, site_name="demo", reconcile_on_start=False)
    blocked = service.dismiss_history_task("warning", site_name="demo", dismissed_by="test")
    assert blocked["dismissed"] == 0
    assert blocked["skipped_unacknowledged"] == 1

    acknowledged = repository.acknowledge_attention_tasks(task_ids=["warning"])
    assert acknowledged["task_ids"] == ["warning"]
    dismissed = service.dismiss_history_task("warning", site_name="demo", dismissed_by="test")
    assert dismissed["task_ids"] == ["warning"]
    assert dismissed["dismissed_by"] == "test"
    assert JobCenterCleanupResultDTO.model_validate(dismissed).dismissed_by == "test"
    assert repository.list(limit=20) == []
    assert repository.get("warning") is None


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
        assert cleanup.json()["dismissed_by"] == "local-user"
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


def test_single_cleanup_api_returns_dismissed_by_and_retires_task(
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

    with TestClient(app) as client:
        response = client.post("/api/job-center/tasks/success/dismiss")

        assert response.status_code == 200
        assert response.json()["task_ids"] == ["success"]
        assert response.json()["dismissed_by"] == "local-user"
        assert client.get("/api/job-center/tasks").json() == []


def test_cleanup_api_allows_eligible_terminal_tasks_in_production(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NETCONSOLE_RUNTIME_MODE", "server")
    paths, repository = _repository(tmp_path)
    write_data_environment(
        paths.data_root,
        DataEnvironmentInfo(DataEnvironmentMode.PRODUCTION, readonly_warning=True),
    )
    repository.save(
        _snapshot(
            "success",
            TaskState.COMPLETED,
            finished_time="2026-07-28T01:00:00Z",
        )
    )
    task_service = TaskApplicationService(
        paths=paths,
        site_name="demo",
        reconcile_on_start=False,
    )
    Database(paths.site_db_path("demo")).initialize()
    monkeypatch.delenv("NETCONSOLE_ALLOW_PRODUCTION_WRITE", raising=False)
    app = create_app(
        RuntimeMode.SERVER,
        paths=paths,
        task_service=task_service,
        frontend_dist=tmp_path / "missing",
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/job-center/cleanup",
            json={"cleanup_type": "completed"},
        )

    assert response.status_code == 200, response.text
    assert response.json()["task_ids"] == ["success"]
    assert repository.get("success") is None
