import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from netconsole.core.paths import PathResolver
from netconsole.core.settings import SettingsStore
from netconsole.models.task_snapshot import TaskEvent, TaskSnapshot
from netconsole.models.task_state import TaskState
from netconsole.repositories.task_repository import TaskRepository
from netconsole.services.job_center.query_service import JobCenterQueryService
from netconsole.services.job_center.task_application_service import TaskApplicationService
from netconsole.services.job_center.task_event_retention_service import TaskEventRetentionService


NOW = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)


def _snapshot(task_id: str, status: TaskState, finished_time: str = "") -> TaskSnapshot:
    return TaskSnapshot(
        task_id=task_id,
        task_type="retention-test",
        task_name=task_id,
        status=status,
        created_time="2026-08-01T00:00:00Z",
        started_time="2026-08-01T00:00:01Z",
        finished_time=finished_time,
        updated_time=finished_time or "2026-08-01T00:00:01Z",
        progress=100 if status in {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED} else 10,
        message="failed summary" if status is TaskState.FAILED else "current summary",
        error_message="final failure summary" if status is TaskState.FAILED else "",
        site_name="demo",
    )


def _event(repository: TaskRepository, task: TaskSnapshot, suffix: str = "event") -> None:
    repository.record(
        task,
        TaskEvent(
            event_id=f"{task.task_id}-{suffix}",
            task_id=task.task_id,
            type="error" if task.status is TaskState.FAILED else "progress",
            time=task.finished_time or task.updated_time,
            payload={"message": task.message, "task_id": task.task_id},
        ),
    )


def _count(db_path: Path, task_id: str | None = None) -> int:
    with sqlite3.connect(db_path) as connection:
        if task_id is None:
            return int(connection.execute("SELECT COUNT(*) FROM task_events").fetchone()[0])
        return int(
            connection.execute("SELECT COUNT(*) FROM task_events WHERE task_id=?", (task_id,)).fetchone()[0]
        )


def _service(tmp_path: Path) -> tuple[PathResolver, TaskRepository, TaskEventRetentionService]:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    repository = TaskRepository(paths.site_tasks_db_path("demo"))
    service = TaskEventRetentionService(paths, repository, site_name="demo")
    return paths, repository, service


def test_terminal_events_older_than_retention_are_removed_but_recent_and_active_are_kept(tmp_path: Path) -> None:
    _paths, repository, service = _service(tmp_path)
    old = _snapshot("old", TaskState.COMPLETED, "2026-09-05T11:59:59Z")
    recent = _snapshot("recent", TaskState.COMPLETED, "2026-09-07T12:00:01Z")
    running = _snapshot("running", TaskState.RUNNING)
    for task in (old, recent, running):
        _event(repository, task)

    result = service.run_due(force=True, now=NOW)

    assert result["deleted_event_rows"] == 1
    assert _count(repository.db_path, "old") == 0
    assert _count(repository.db_path, "recent") == 1
    assert _count(repository.db_path, "running") == 1


def test_failed_summary_and_detail_survive_event_retention(tmp_path: Path) -> None:
    paths, repository, service = _service(tmp_path)
    failed = _snapshot("failed", TaskState.FAILED, "2026-09-01T12:00:00Z")
    _event(repository, failed)

    service.run_due(force=True, now=NOW)

    persisted = repository.get("failed")
    assert persisted is not None
    assert persisted.error_message == "final failure summary"
    assert _count(repository.db_path, "failed") == 0
    logs = JobCenterQueryService(paths).get_logs("demo", "failed")
    assert logs is not None
    assert logs.lines == []
    assert logs.message == "详细运行记录已按保留策略清理"


def test_online_mr_and_ground_references_protect_terminal_events(tmp_path: Path) -> None:
    paths, repository, service = _service(tmp_path)
    online = _snapshot("online", TaskState.COMPLETED, "2026-09-01T12:00:00Z")
    ground = _snapshot("ground", TaskState.COMPLETED, "2026-09-01T12:00:00Z")
    _event(repository, online)
    _event(repository, ground)
    with sqlite3.connect(repository.db_path) as connection:
        connection.execute(
            "CREATE TABLE online_mr_task_sessions (controller_task_id TEXT)"
        )
        connection.execute(
            "INSERT INTO online_mr_task_sessions(controller_task_id) VALUES (?)",
            ("online",),
        )
    ground_db = paths.ground_unattended_db_path("demo")
    ground_db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(ground_db) as connection:
        connection.execute("CREATE TABLE current_mapping (task_id TEXT)")
        connection.execute("INSERT INTO current_mapping(task_id) VALUES (?)", ("ground",))

    result = service.run_due(force=True, now=NOW)

    assert result["protected_online_task_ids"] == ["online"]
    assert result["protected_ground_task_ids"] == ["ground"]
    assert result["deleted_event_rows"] == 0
    assert _count(repository.db_path, "online") == 1
    assert _count(repository.db_path, "ground") == 1


def test_event_retention_rolls_back_the_current_batch_on_failure(tmp_path: Path) -> None:
    _paths, repository, _service_instance = _service(tmp_path)
    old = _snapshot("old", TaskState.COMPLETED, "2026-09-01T12:00:00Z")
    _event(repository, old)

    def fail(_batch: int) -> None:
        raise RuntimeError("injected retention failure")

    with pytest.raises(RuntimeError, match="injected retention failure"):
        repository.delete_task_events_for_retention(
            ["old"],
            cutoff=datetime(2026, 9, 6, 12, 0, tzinfo=UTC),
            fault_injector=fail,
        )
    assert _count(repository.db_path, "old") == 1


def test_event_retention_is_idempotent_and_due_state_survives_restart(tmp_path: Path) -> None:
    paths, repository, service = _service(tmp_path)
    old = _snapshot("old", TaskState.COMPLETED, "2026-09-01T12:00:00Z")
    _event(repository, old)

    first = service.run_due(force=True, now=NOW)
    restarted = TaskApplicationService(paths=paths, site_name="demo", reconcile_on_start=False)
    second = TaskEventRetentionService(
        paths,
        restarted.repository(),
        site_name="demo",
    ).run_due(now=NOW)

    assert first["deleted_event_rows"] == 1
    assert second["status"] == "SKIPPED_NOT_DUE"
    assert _count(repository.db_path, "old") == 0
    assert restarted.repository().get("old") is not None


def test_setting_changes_are_used_by_the_next_forced_cleanup(tmp_path: Path) -> None:
    paths, repository, service = _service(tmp_path)
    six_days = _snapshot("six-days", TaskState.COMPLETED, "2026-09-07T12:00:00Z")
    _event(repository, six_days)
    settings = SettingsStore(paths)
    settings.set_task_event_retention_days(14)

    kept = service.run_due(force=True, now=NOW)

    assert kept["deleted_event_rows"] == 0
    settings.set_task_event_retention_days(3)
    removed = service.run_due(force=True, now=NOW)
    assert removed["deleted_event_rows"] == 1


def test_log_center_file_is_outside_event_retention_boundary(tmp_path: Path) -> None:
    _paths, repository, service = _service(tmp_path)
    log_path = tmp_path / "runtime" / "logs" / "app.log"
    log_path.parent.mkdir(parents=True)
    log_path.write_text("long-term log", encoding="utf-8")
    old = _snapshot("old", TaskState.COMPLETED, "2026-09-01T12:00:00Z")
    _event(repository, old)

    service.run_due(force=True, now=NOW)

    assert log_path.read_text(encoding="utf-8") == "long-term log"
