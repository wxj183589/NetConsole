from __future__ import annotations

from pathlib import Path
from threading import Event

import pytest
from fastapi.testclient import TestClient

from netconsole.backend.api.health import health_response
from netconsole.backend.api.main import create_app
from netconsole.core.paths import PathResolver
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.core.version import APP_VERSION
from netconsole.infrastructure.desktop import (
    LocalDesktopAdapter,
    UnavailableDesktopAdapter,
)
from netconsole.models.api import (
    AgentStatusDTO,
    ApiResponse,
    ErrorDetail,
    ErrorResponse,
    TaskDTO,
    TaskEventDTO,
)
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
    assert (
        AgentStatusDTO(
            agent_id="agent-1", name="测试 Agent", status="online"
        ).current_tasks
        == 0
    )


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

    build_id = f"{APP_VERSION}+test"
    assert health_response(build_id).model_dump() == {
        "status": "ok",
        "version": APP_VERSION.removeprefix("v"),
        "build_id": build_id,
    }
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
        "/api/features",
        "/api/device-management/devices",
        "/api/network-tools/tcp-port-test",
        "/api/config-collection/devices",
        "/api/file-management/files",
    } <= routes
    assert app.state.device_management_service is not None
    assert app.state.device_management_service.site_name is None
    assert app.state.config_collection_service is not None
    assert app.state.file_management_service is not None
    assert app.state.network_tools_service is not None
    assert app.state.online_mr_web_control_enabled is False


@pytest.mark.parametrize("runtime_mode", [RuntimeMode.DESKTOP, RuntimeMode.SERVER])
def test_api_runtime_composes_single_shared_services(
    runtime_mode: RuntimeMode, tmp_path: Path
) -> None:
    paths = PathResolver(tmp_path / runtime_mode.value)
    app = create_app(runtime_mode, paths=paths, frontend_dist=tmp_path / "missing")

    assert app.state.runtime_mode is runtime_mode
    assert app.state.paths.data_root == paths.data_root
    assert app.state.config_collection_service.task_service is app.state.task_service
    assert app.state.device_management_service.task_service is app.state.task_service
    assert (
        app.state.device_management_service.desktop_action_service
        is app.state.desktop_action_service
    )
    expected_desktop_adapter = (
        LocalDesktopAdapter
        if runtime_mode is RuntimeMode.DESKTOP
        else UnavailableDesktopAdapter
    )
    assert isinstance(
        app.state.desktop_action_service.adapter, expected_desktop_adapter
    )
    default_terminal = app.state.desktop_action_service.launch_registered_terminal(
        "terminal.securecrt", "device-1"
    )
    assert default_terminal.success is False
    assert default_terminal.code == (
        "unknown_terminal_action"
        if runtime_mode is RuntimeMode.DESKTOP
        else "server_mode_forbidden"
    )
    assert (
        app.state.config_collection_service.process_adapter
        is app.state.device_management_service.process_adapter
    )
    assert (
        app.state.file_management_service.process_adapter
        is app.state.device_management_service.process_adapter
    )
    assert (
        app.state.ac_web_application_service.process_adapter
        is app.state.device_management_service.process_adapter
    )
    assert (
        app.state.rail_transit_web_application_service.process_adapter
        is app.state.device_management_service.process_adapter
    )
    assert (
        app.state.ac_web_application_service.export_adapter
        is app.state.rail_transit_web_application_service.export_adapter
    )
    assert (
        app.state.ac_web_application_service.artifact_store
        is app.state.rail_transit_web_application_service.artifact_store
    )
    assert (
        app.state.config_collection_service.desktop_action_service
        is app.state.desktop_action_service
    )
    assert app.state.network_tools_service.traffic_service is app.state.traffic_service
    assert (
        app.state.traffic_web_application_service.traffic_service
        is app.state.traffic_service
    )
    assert (
        app.state.traffic_web_application_service.agent_service
        is app.state.agent_service
    )
    assert (
        app.state.online_mr_api_facade.query_service
        is app.state.online_mr_query_service
    )
    assert (
        app.state.online_mr_api_facade.local_control
        is app.state.online_mr_web_control_service
    )
    assert (
        app.state.online_mr_api_facade.agent_control
        is app.state.online_mr_agent_web_control_service
    )
    assert (
        app.state.rail_transit_import_preview_service.import_service
        is app.state.rail_transit_base_data_import_service
    )


def test_disabled_web_features_hide_state_and_block_backend_routes(
    tmp_path: Path,
) -> None:
    app = create_app(
        RuntimeMode.SERVER,
        paths=PathResolver(tmp_path),
        frontend_dist=tmp_path / "missing",
    )
    app.state.feature_gate.features["web.device_management"] = {
        "visible": False,
        "enabled": False,
    }
    app.state.feature_gate.features["web.config_collection"] = {
        "visible": False,
        "enabled": False,
    }
    app.state.feature_gate.features["web.network_tools_toolbox"] = {
        "visible": False,
        "enabled": False,
    }

    with TestClient(app) as client:
        features = client.get("/api/features")
        devices = client.get("/api/device-management/devices")
        config = client.get("/api/config-collection/devices")
        network = client.post(
            "/api/network-tools/tcp-port-test",
            json={"target": "127.0.0.1", "port": 443},
        )

    assert features.status_code == 200
    state = next(
        item
        for item in features.json()["items"]
        if item["feature_id"] == "web.device_management"
    )
    assert state["visible"] is False
    assert state["enabled"] is False
    assert devices.status_code == 404
    assert config.status_code == 404
    assert network.status_code == 404


def test_web_lifespan_stops_local_adapters_in_parallel(
    tmp_path: Path, monkeypatch
) -> None:
    traffic_stop_entered = Event()
    adapter_stop_entered = Event()

    class BlockingAdapter:
        def __init__(self, _task_service) -> None:
            pass

        def shutdown(self, timeout_seconds: float = 5.0) -> None:
            adapter_stop_entered.set()
            assert traffic_stop_entered.wait(1)

    class AsyncService:
        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            traffic_stop_entered.set()

    class PassiveService(AsyncService):
        async def stop(self) -> None:
            pass

    paths = PathResolver(tmp_path)
    tasks = TaskApplicationService(paths=paths)
    monkeypatch.setattr(
        "netconsole.backend.api.main.LocalProcessAdapter", BlockingAdapter
    )
    app = create_app(
        RuntimeMode.SERVER,
        paths=paths,
        task_service=tasks,
        agent_service=PassiveService(),  # type: ignore[arg-type]
        traffic_service=AsyncService(),  # type: ignore[arg-type]
        ac_mesh_link_refresh_service=PassiveService(),  # type: ignore[arg-type]
        frontend_dist=tmp_path / "missing",
    )

    with TestClient(app):
        pass

    assert adapter_stop_entered.is_set()
    assert traffic_stop_entered.is_set()


def test_web_lifespan_stops_file_queue_before_shared_process_adapter(
    tmp_path: Path, monkeypatch
) -> None:
    file_closed = Event()
    adapter_entered = Event()
    premature_adapter_shutdown = Event()

    class OrderedAdapter:
        def __init__(self, _task_service) -> None:
            pass

        def shutdown(self, timeout_seconds: float = 5.0) -> None:
            adapter_entered.set()
            if not file_closed.is_set():
                premature_adapter_shutdown.set()

    class PassiveService:
        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

    paths = PathResolver(tmp_path)
    monkeypatch.setattr(
        "netconsole.backend.api.main.LocalProcessAdapter", OrderedAdapter
    )
    app = create_app(
        RuntimeMode.SERVER,
        paths=paths,
        task_service=TaskApplicationService(paths=paths),
        agent_service=PassiveService(),  # type: ignore[arg-type]
        traffic_service=PassiveService(),  # type: ignore[arg-type]
        ac_mesh_link_refresh_service=PassiveService(),  # type: ignore[arg-type]
        frontend_dist=tmp_path / "missing",
    )

    def close_file_queue() -> None:
        # 并行 gather 会让 adapter 在这里等待期间提前进入；严格顺序不会。
        adapter_entered.wait(0.2)
        file_closed.set()

    monkeypatch.setattr(app.state.file_management_service, "close", close_file_queue)
    with TestClient(app):
        pass

    assert file_closed.is_set()
    assert adapter_entered.is_set()
    assert premature_adapter_shutdown.is_set() is False


def test_web_lifespan_rolls_back_when_traffic_start_fails(tmp_path: Path) -> None:
    class AgentService:
        stopped = False

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            self.stopped = True

    class TrafficService(AgentService):
        async def start(self) -> None:
            raise RuntimeError("traffic start failed")

    class AcService(AgentService):
        pass

    agent = AgentService()
    traffic = TrafficService()
    ac = AcService()
    app = create_app(
        RuntimeMode.SERVER,
        paths=PathResolver(tmp_path),
        task_service=TaskApplicationService(paths=PathResolver(tmp_path)),
        agent_service=agent,  # type: ignore[arg-type]
        traffic_service=traffic,  # type: ignore[arg-type]
        ac_mesh_link_refresh_service=ac,  # type: ignore[arg-type]
        frontend_dist=tmp_path / "missing",
    )

    with pytest.raises(RuntimeError, match="traffic start failed"), TestClient(app):
        pass

    assert agent.stopped is True
    assert traffic.stopped is True
    assert ac.stopped is True


def test_web_lifespan_cleanup_failure_does_not_skip_agent_stop(tmp_path: Path) -> None:
    class AgentService:
        stopped = False

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            self.stopped = True

    class FailingTrafficService(AgentService):
        async def stop(self) -> None:
            self.stopped = True
            raise RuntimeError("traffic stop failed")

    agent = AgentService()
    traffic = FailingTrafficService()
    app = create_app(
        RuntimeMode.SERVER,
        paths=PathResolver(tmp_path),
        task_service=TaskApplicationService(paths=PathResolver(tmp_path)),
        agent_service=agent,  # type: ignore[arg-type]
        traffic_service=traffic,  # type: ignore[arg-type]
        ac_mesh_link_refresh_service=AgentService(),  # type: ignore[arg-type]
        frontend_dist=tmp_path / "missing",
    )

    with TestClient(app):
        pass

    assert traffic.stopped is True
    assert agent.stopped is True


def test_task_runtime_tracks_states_and_reuses_worker_protocol(tmp_path: Path) -> None:
    service = TaskApplicationService(paths=PathResolver(tmp_path))
    events: list[dict[str, object]] = []
    service.events.subscribe(events.append)
    launch = service.prepare(BackgroundJob(job_id="runtime-job", task_type="demo_task"))

    assert launch.job_path.exists()
    assert service.is_running("runtime-job")
    service.mark_running("runtime-job")
    service.feed_stdout(
        "runtime-job",
        encode_event(progress_event("runtime-job", "work", 1, 2, "处理中")).encode(
            "utf-8"
        ),
    )
    service.feed_stdout(
        "runtime-job",
        encode_event(finished_event("runtime-job", {"count": 1})).encode("utf-8"),
    )
    result = service.complete("runtime-job", 0)

    assert result is not None and result["type"] == "finished"
    assert [
        dict(event.get("payload") or {}).get("state")
        for event in events
        if event.get("type") == "state"
    ] == [
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
    runtime_root = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "netconsole"
        / "services"
        / "job_center"
        / "runtime"
    )
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in runtime_root.glob("*.py")
    )

    assert "PySide6" not in source
    assert "QProcess" not in source
    assert "QObject" not in source


def test_task_event_bus_isolates_host_consumer_failures(tmp_path: Path) -> None:
    service = TaskApplicationService(paths=PathResolver(tmp_path))
    received: list[str] = []

    def broken_consumer(_event: dict[str, object]) -> None:
        raise RuntimeError("宿主消费失败")

    service.events.subscribe(broken_consumer)
    service.events.subscribe(
        lambda event: received.append(str(event.get("type") or ""))
    )
    service.prepare(BackgroundJob(job_id="isolated-job", task_type="demo_task"))
    service.abandon("isolated-job")

    assert received == ["state", "state", "state"]
