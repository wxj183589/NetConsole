from __future__ import annotations

from pathlib import Path

from netconsole.backend.api.health import health
from netconsole.backend.api.main import create_app
from netconsole.core.paths import PathResolver
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.models.api import AgentStatusDTO, ApiResponse, ErrorDetail, ErrorResponse, TaskDTO, TaskEventDTO
from netconsole.services.background_job import BackgroundJob
from netconsole.services.job_center.job_events import finished_event, progress_event
from netconsole.services.job_center.runtime import TaskApplicationService, TaskState
from netconsole.services.job_center.worker_protocol import encode_event


def test_runtime_mode_and_api_dtos_are_stable() -> None:
    assert RuntimeMode.DESKTOP.value == "desktop"
    assert RuntimeMode.SERVER.value == "server"
    task = TaskDTO(
        id="job-1",
        type="demo",
        name="演示任务",
        status=TaskState.PENDING,
        created_time="2026-01-01T00:00:00Z",
        updated_time="2026-01-01T00:00:00Z",
    )
    event = TaskEventDTO(
        id="event-1",
        task_id="job-1",
        type="state",
        time="2026-01-01T00:00:00Z",
        payload={"state": "STARTING"},
    )
    assert task.model_dump(mode="json")["status"] == "PENDING"
    assert event.payload["state"] == "STARTING"
    assert ApiResponse(data={"ok": True}).ok is True
    assert ErrorResponse(error=ErrorDetail(message="失败")).ok is False
    assert AgentStatusDTO(agent_id="agent-1", name="测试 Agent", status="online").current_tasks == 0


def test_fastapi_app_exposes_registered_web_modules() -> None:
    app = create_app(RuntimeMode.SERVER)
    routes = set(app.openapi()["paths"])
    pending = list(app.routes)
    while pending:
        route = pending.pop()
        path = getattr(route, "path", None)
        if path:
            routes.add(path)
        original_router = getattr(route, "original_router", None)
        if original_router is not None:
            pending.extend(original_router.routes)

    assert health().model_dump() == {"status": "ok", "version": "1.3.8"}
    assert app.state.runtime_mode is RuntimeMode.SERVER
    assert {
        "/api/health",
        "/docs",
        "/api/tasks",
        "/ws/tasks",
        "/api/ac-management/summary",
        "/api/agents",
        "/api/online-mr/sessions/current",
        "/api/rail-transit/base-data/summary",
        "/api/traffic/runs",
    } <= routes
    assert app.state.online_mr_web_control_enabled is False


def test_task_runtime_tracks_states_and_reuses_worker_protocol(tmp_path: Path) -> None:
    service = TaskApplicationService(paths=PathResolver(tmp_path))
    events: list[dict[str, object]] = []
    service.events.subscribe(events.append)
    launch = service.prepare(BackgroundJob(job_id="runtime-job", task_type="demo_task"))

    assert launch.job_path.exists()
    assert service.is_running("runtime-job")
    service.mark_running("runtime-job")
    service.feed_stdout("runtime-job", encode_event(progress_event("runtime-job", "work", 1, 2, "处理中")).encode("utf-8"))
    service.feed_stdout("runtime-job", encode_event(finished_event("runtime-job", {"count": 1})).encode("utf-8"))
    result = service.complete("runtime-job", 0)

    assert result is not None and result["type"] == "finished"
    assert [dict(event.get("payload") or {}).get("state") for event in events if event.get("type") == "state"] == [
        "PENDING",
        "STARTING",
        "RUNNING",
        "COMPLETED",
    ]
    assert any(event.get("type") == "progress" for event in events)
    assert not service.is_running("runtime-job")
    assert not launch.job_path.exists()
    assert not launch.cancel_path.exists()


def test_task_runtime_package_has_no_qt_dependency() -> None:
    runtime_root = Path(__file__).resolve().parents[1] / "src" / "netconsole" / "services" / "job_center" / "runtime"
    source = "\n".join(path.read_text(encoding="utf-8") for path in runtime_root.glob("*.py"))

    assert "PySide6" not in source
    assert "QProcess" not in source
    assert "QObject" not in source


def test_task_event_bus_isolates_host_consumer_failures(tmp_path: Path) -> None:
    service = TaskApplicationService(paths=PathResolver(tmp_path))
    received: list[str] = []

    def broken_consumer(_event: dict[str, object]) -> None:
        raise RuntimeError("宿主消费失败")

    service.events.subscribe(broken_consumer)
    service.events.subscribe(lambda event: received.append(str(event.get("type") or "")))
    service.prepare(BackgroundJob(job_id="isolated-job", task_type="demo_task"))
    service.abandon("isolated-job")

    assert received == ["state", "state", "state"]
