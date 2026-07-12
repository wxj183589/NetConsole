from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient

from netconsole.backend.api.main import create_app
from netconsole.core.paths import PathResolver
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.models.task_snapshot import TaskSnapshot, utc_now_iso
from netconsole.models.task_state import TaskState
from netconsole.repositories.task_repository import TaskRepository
from netconsole.services.background_job import BackgroundJob
from netconsole.services.job_center.job_events import finished_event, log_event, progress_event
from netconsole.services.job_center.task_application_service import TaskApplicationService
from netconsole.services.job_center.worker_protocol import encode_event


def _service(tmp_path: Path) -> TaskApplicationService:
    return TaskApplicationService(paths=PathResolver(tmp_path), site_name="demo")


def _complete_task(service: TaskApplicationService, task_id: str = "task-complete") -> None:
    service.prepare(
        BackgroundJob(
            job_id=task_id,
            task_type="demo_task",
            params={"task_name": "演示任务", "site_name": "demo", "owner": "tester", "device_name": "设备A"},
        )
    )
    service.mark_running(task_id)
    service.feed_stdout(task_id, encode_event(progress_event(task_id, "collect", 3, 4, "采集中")).encode("utf-8"))
    service.feed_stdout(
        task_id,
        encode_event(finished_event(task_id, {"count": 3, "result_path": "outputs/result.json"})).encode("utf-8"),
    )
    service.complete(task_id, 0)


def test_task_repository_persists_snapshot_events_and_wal(tmp_path: Path) -> None:
    service = _service(tmp_path)
    _complete_task(service)

    restored = _service(tmp_path).get_task("task-complete")
    assert restored is not None
    assert restored.status is TaskState.COMPLETED
    assert restored.progress == 100
    assert restored.owner == "tester"
    assert restored.device == "设备A"
    assert restored.result_path == "outputs/result.json"
    assert {event["type"] for event in service.list_events("task-complete")} >= {"state", "progress", "finished"}
    with sqlite3.connect(service.paths.site_tasks_db_path("demo")) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_task_repository_initialization_preserves_existing_tables(tmp_path: Path) -> None:
    db_path = PathResolver(tmp_path).site_tasks_db_path("demo")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE legacy_marker (value TEXT)")
        conn.execute("INSERT INTO legacy_marker VALUES ('keep')")
        conn.commit()

    TaskRepository(db_path)

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT value FROM legacy_marker").fetchone()[0] == "keep"
        assert conn.execute("SELECT value FROM task_schema_meta WHERE key = 'schema_version'").fetchone()[0] == "1"


def test_task_repository_handles_concurrent_event_writes(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.prepare(BackgroundJob(job_id="concurrent", task_type="demo_task"))

    def publish(index: int) -> None:
        service.events.publish(log_event("concurrent", f"日志 {index}"), source="test")

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(publish, range(40)))

    logs = [event for event in service.list_events("concurrent", limit=100) if event["type"] == "log"]
    assert len(logs) == 40


def test_orphaned_local_task_is_reconciled_as_failed(tmp_path: Path) -> None:
    repository = TaskRepository(PathResolver(tmp_path).site_tasks_db_path("demo"))
    now = utc_now_iso()
    repository.save(
        TaskSnapshot(
            task_id="orphan",
            task_type="demo_task",
            task_name="遗留任务",
            status=TaskState.RUNNING,
            created_time=now,
            updated_time=now,
            source="local",
            owner_pid=999999,
        )
    )

    changed = repository.reconcile_orphaned_local_tasks(lambda _pid: False)

    assert [item.task_id for item in changed] == ["orphan"]
    restored = repository.get("orphan")
    assert restored is not None and restored.status is TaskState.FAILED
    assert "非正常中断" in restored.error_message


def test_task_restores_while_owner_process_is_alive(tmp_path: Path) -> None:
    first = _service(tmp_path)
    first.prepare(BackgroundJob(job_id="running", task_type="demo_task", params={"task_name": "运行任务"}))
    first.mark_running("running")

    restored = _service(tmp_path).get_task("running")

    assert restored is not None and restored.status is TaskState.RUNNING


def test_task_rest_api_lists_details_events_and_cancel(tmp_path: Path) -> None:
    service = _service(tmp_path)
    _complete_task(service)
    service.prepare(BackgroundJob(job_id="task-running", task_type="demo_task", params={"task_name": "运行任务"}))
    service.mark_running("task-running")
    app = create_app(RuntimeMode.SERVER, paths=service.paths, task_service=service, frontend_dist=tmp_path / "missing-dist")

    with TestClient(app) as client:
        listing = client.get("/api/tasks")
        detail = client.get("/api/tasks/task-complete")
        events = client.get("/api/tasks/task-complete/events")
        cancelled = client.post("/api/tasks/task-running/cancel")
        conflict = client.post("/api/tasks/task-complete/cancel")

    assert listing.status_code == 200
    assert {item["status"] for item in listing.json()} >= {"RUNNING", "COMPLETED"}
    assert detail.json()["name"] == "演示任务"
    assert events.status_code == 200 and events.json()
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "STOPPING"
    assert conflict.status_code == 409
    assert (service.paths.runtime_cache_dir / "background_jobs" / "task-running.cancel").exists()


def test_task_websocket_sends_snapshot_and_hub_event(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.prepare(BackgroundJob(job_id="socket-task", task_type="demo_task", params={"task_name": "Socket任务"}))
    app = create_app(RuntimeMode.SERVER, paths=service.paths, task_service=service, frontend_dist=tmp_path / "missing-dist")

    with TestClient(app) as client:
        with client.websocket_connect("/ws/tasks") as socket:
            snapshot = socket.receive_json()
            service.events.publish(log_event("socket-task", "实时日志"), source="test")
            event = socket.receive_json()

    assert snapshot["type"] == "snapshot"
    assert snapshot["payload"]["tasks"][0]["id"] == "socket-task"
    assert event["type"] == "log"
    assert event["payload"]["message"] == "实时日志"


def test_task_events_are_valid_utf8_json(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.prepare(BackgroundJob(job_id="utf8-task", task_type="demo_task", params={"task_name": "中文任务"}))
    service.events.publish(log_event("utf8-task", "中文日志"), source="test")

    payload = json.dumps(service.list_events("utf8-task"), ensure_ascii=False)
    assert "中文日志" in payload


def test_fastapi_serves_vue_spa_routes(tmp_path: Path) -> None:
    dist = tmp_path / "frontend" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text('<div id="app">NetConsole Web</div>', encoding="utf-8")
    service = _service(tmp_path)
    app = create_app(RuntimeMode.SERVER, paths=service.paths, task_service=service, frontend_dist=dist)

    with TestClient(app) as client:
        root = client.get("/")
        nested = client.get("/tasks")
        health = client.get("/api/health")

    assert root.status_code == 200 and "NetConsole Web" in root.text
    assert nested.status_code == 200 and 'id="app"' in nested.text
    assert health.status_code == 200
