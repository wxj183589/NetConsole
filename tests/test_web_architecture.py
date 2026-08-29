from __future__ import annotations

from pathlib import Path
from threading import Event

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

import netconsole.backend.api.main as main_module
from netconsole.backend.api.health import health_response
from netconsole.backend.api.main import _unattended_run_active, create_app
from netconsole.core.database import Database
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
from netconsole.repositories.ground_unattended_repository import (
    GroundUnattendedRepository,
)
from netconsole.services.background_job import BackgroundJob
from netconsole.services.job_center.job_events import finished_event, progress_event
from netconsole.services.job_center.runtime import TaskApplicationService, TaskState
from netconsole.services.job_center.worker_protocol import encode_event
from scripts.architecture.checks import (
    architecture_boundary_findings,
    ui_business_logic_findings,
)
from scripts.architecture.guard_core import apply_exceptions, load_exceptions


def test_performance_middleware_returns_request_and_server_timings() -> None:
    app = FastAPI()
    app.add_middleware(main_module.PerformanceProfilingMiddleware)

    @app.get("/profile")
    def profile() -> dict[str, bool]:
        return {"ok": True}

    with TestClient(app) as client:
        response = client.get("/profile", headers={"X-Request-ID": "profile-request"})

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "profile-request"
    assert "app;dur=" in response.headers["server-timing"]
    assert "sql;dur=" in response.headers["server-timing"]
    assert "repository;dur=" in response.headers["server-timing"]


def test_performance_middleware_preserves_domain_request_id() -> None:
    app = FastAPI()
    app.add_middleware(main_module.PerformanceProfilingMiddleware)

    @app.get("/profile-domain-request-id")
    def profile() -> JSONResponse:
        return JSONResponse(
            {"request_id": "domain-request-id"},
            headers={"X-Request-ID": "domain-request-id"},
        )

    with TestClient(app) as client:
        response = client.get("/profile-domain-request-id")

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "domain-request-id"
    assert response.json()["request_id"] == "domain-request-id"


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
        "product_version": APP_VERSION.removeprefix("v"),
        "build_number": 0,
        "file_version": f"{APP_VERSION.removeprefix('v')}.0",
        "published": False,
        "build_id": build_id,
        "backend_commit": "unknown",
        "frontend_commit": "unknown",
        "commit_sha_short": "unknown",
        "edition": "dev",
        "packaged_dirty": True,
        "build_timestamp": "",
        "data_root": "",
        "active_site_id": "",
        "storage_schema_version": 1,
        "runtime_services_status": "ready",
        "runtime_services_ready": True,
        "runtime_services_error": "",
        "performance_mode": "standard",
        "unattended_status": "disabled",
        "unattended_ready": False,
        "unattended_error": "",
        "history_status": "idle",
        "history_pending": 0,
        "history_error": "",
        "history_oldest_pending_age_seconds": 0,
        "history_pressure": "normal",
        "history_last_drain_elapsed_ms": 0,
        "history_last_drain_written": 0,
        "history_budget_overrun": False,
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
    assert app.state.capability_policy.disk_maintenance_concurrency == 1


def test_server_unattended_mode_reports_readiness_without_hardware_recollection(
    tmp_path: Path,
) -> None:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    paths.settings_path.parent.mkdir(parents=True, exist_ok=True)
    paths.settings_path.write_text(
        '{"app/runtime_performance_mode":"server_unattended"}',
        encoding="utf-8",
    )
    app = create_app(RuntimeMode.DESKTOP, paths=paths, frontend_dist=tmp_path / "missing")

    assert app.state.performance_mode == "server_unattended"
    assert app.state.capability_policy.unattended_priority is True
    assert app.state.capability_policy.low_priority_work_enabled is False
    assert app.state.host_environment_profile is None


def test_history_maintenance_pauses_only_for_a_persisted_unattended_run(
    tmp_path: Path,
) -> None:
    repository = GroundUnattendedRepository(tmp_path / "ground.db", site_id="demo")

    assert _unattended_run_active(repository) is False
    run = repository.create_or_get_run(
        run_id="run-1",
        run_date="2026-08-13",
        scheduled_start_at="2026-08-13T07:00:00+08:00",
        scheduled_end_at="2026-08-13T23:00:00+08:00",
        state="STARTING",
    )
    assert _unattended_run_active(repository) is True

    repository.update_run(str(run["run_id"]), state="COMPLETED")
    assert _unattended_run_active(repository) is False


def test_deferred_runtime_failure_is_visible_and_blocks_service_writes(tmp_path: Path) -> None:
    app = create_app(
        RuntimeMode.SERVER,
        paths=PathResolver(tmp_path),
        frontend_dist=tmp_path / "missing",
    )

    with TestClient(app) as client:
        # Lifespan initializes the runtime state.  Apply the failure after it
        # has run so this verifies the write gate rather than stale setup.
        app.state.runtime_services_status = "degraded"
        app.state.runtime_services_ready = False
        app.state.runtime_services_error = "AgentControllerService"
        app.state.history_status = "degraded"
        app.state.history_pending = 18200
        app.state.history_error = "shard_write_failed"
        health = client.get("/api/health")
        blocked = client.post("/api/traffic/runs", json={})

    assert health.status_code == 200
    assert health.json()["runtime_services_status"] == "degraded"
    assert health.json()["runtime_services_ready"] is False
    assert health.json()["runtime_services_error"] == "AgentControllerService"
    assert health.json()["history_status"] == "degraded"
    assert health.json()["history_pending"] == 18200
    assert health.json()["history_error"] == "shard_write_failed"
    assert blocked.status_code == 503
    assert blocked.json()["code"] == "RUNTIME_SERVICES_DEGRADED"


def test_history_store_is_retired_from_backend_lifecycle(tmp_path: Path) -> None:
    app = create_app(
        RuntimeMode.SERVER,
        paths=PathResolver(tmp_path),
        frontend_dist=tmp_path / "missing",
    )

    assert not hasattr(app.state, "history_store")
    assert app.state.history_status == "retired"
    with TestClient(app) as client:
        app.state.runtime_services_ready = False
        app.state.runtime_services_status = "degraded"
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["history_status"] == "retired"


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
    app.state.feature_gate.features["module.devices"] = {
        "visible": False,
        "enabled": False,
    }
    app.state.feature_gate.features["module.config_collection"] = {
        "visible": False,
        "enabled": False,
    }
    app.state.feature_gate.features["capability.network_tools.toolbox"] = {
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
        if item["feature_id"] == "module.devices"
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
    Database(paths.site_db_path("demo")).initialize()
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
    Database(paths.site_db_path("demo")).initialize()
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
    paths = PathResolver(tmp_path)
    Database(paths.site_db_path("demo")).initialize()
    app = create_app(
        RuntimeMode.SERVER,
        paths=paths,
        task_service=TaskApplicationService(paths=paths),
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
    paths = PathResolver(tmp_path)
    Database(paths.site_db_path("demo")).initialize()
    app = create_app(
        RuntimeMode.SERVER,
        paths=paths,
        task_service=TaskApplicationService(paths=paths),
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


def test_task_runtime_shutdown_closes_admission_and_reports_active_counts(tmp_path: Path) -> None:
    service = TaskApplicationService(paths=PathResolver(tmp_path), reconcile_on_start=False)
    launch = service.prepare(BackgroundJob(job_id="drain-6", task_type="demo_task"))
    before = service.active_task_snapshot()
    assert before["active_tasks"] == 1
    assert before["active_workers"] == 1

    stopping = service.begin_shutdown()
    assert stopping["active_tasks"] == 1
    assert stopping["stopping_tasks"] == 1
    with pytest.raises(RuntimeError, match="shutting down"):
        service.prepare(BackgroundJob(job_id="rejected", task_type="demo_task"))

    service.complete(launch.job.job_id, 1)
    assert service.active_task_snapshot()["active_tasks"] == 0


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


def test_web_and_electron_ast_guards_have_no_unwaived_findings() -> None:
    exceptions = load_exceptions()
    findings = [
        item
        for item in architecture_boundary_findings()
        if item.rule_id.startswith("TS_") or item.rule_id == "LEGACY_NAV_FIELD_SCOPE"
    ]
    active, _ = apply_exceptions(findings + ui_business_logic_findings(), exceptions)
    assert active == ()
