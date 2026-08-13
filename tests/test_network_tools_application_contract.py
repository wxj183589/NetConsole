from __future__ import annotations

from pathlib import Path

import threading

import time

from types import SimpleNamespace

from fastapi import FastAPI

from fastapi.testclient import TestClient

from netconsole.backend.api.network_tools_router import router

from netconsole.core.feature_flags import FeatureGate

from netconsole.core.paths import PathResolver

from netconsole.services.job_center.job_events import progress_event

from netconsole.services.job_center.job_models import JobSpec

from netconsole.services.job_center.job_runner import run_job

from netconsole.services.job_center.task_application_service import TaskApplicationService

from netconsole.services.job_center.worker_protocol import encode_event

from netconsole.services.network_tools.application_service import NetworkToolsApplicationService

class FakeTrafficService:
    paths = None
    site_name = "demo"

    async def start_tcp_port_test(self, config, execution_target):
        raise AssertionError("TCP Traffic adapter is not part of this test")

class DispatchingProcessAdapter:
    """测试用正式 Registry 分发器；保留 TaskRuntime 事件和取消协议。"""

    def __init__(self, task_service: TaskApplicationService, *, force_release: threading.Event | None = None) -> None:
        self.task_service = task_service
        self.force_release = force_release
        self.jobs: list[JobSpec] = []
        self._threads: dict[str, threading.Thread] = {}
        self._cancel: dict[str, threading.Event] = {}
        self.forced_jobs: set[str] = set()
        self.shutdown_calls = 0

    def start_job(self, job: JobSpec, *, on_complete=None) -> str:
        launch = self.task_service.prepare(job)
        self.task_service.mark_running(launch.job.job_id)
        self.jobs.append(launch.job)
        cancel = threading.Event()
        self._cancel[launch.job.job_id] = cancel
        thread = threading.Thread(
            target=self._run,
            args=(launch.job, cancel, on_complete),
            daemon=True,
        )
        self._threads[launch.job.job_id] = thread
        thread.start()
        return launch.job.job_id

    def _run(self, job: JobSpec, cancel: threading.Event, on_complete) -> None:
        def progress(stage: str, current: int, total: int, message: str) -> None:
            self.task_service.feed_stdout(
                job.job_id,
                encode_event(progress_event(job.job_id, stage, current, total, message)).encode("utf-8"),
            )

        result = run_job(job, progress_callback=progress, should_cancel=cancel.is_set)
        self.task_service.feed_stdout(job.job_id, encode_event(result.to_event()).encode("utf-8"))
        exit_code = 0 if result.ok else 2 if result.cancelled else 1
        payload = self.task_service.complete(job.job_id, exit_code)
        if on_complete is not None:
            on_complete(SimpleNamespace(job_id=job.job_id, task_type=job.task_type, exit_code=exit_code, payload=payload, cancelled=result.cancelled, forced=job.job_id in self.forced_jobs))

    def is_running(self, job_id: str) -> bool:
        thread = self._threads.get(job_id)
        return bool(thread and thread.is_alive())

    def cancel_job(self, job_id: str) -> bool:
        thread = self._threads.get(job_id)
        if thread is None or not thread.is_alive():
            return False
        self.task_service.request_cancel(job_id)
        self._cancel[job_id].set()
        if self.force_release is not None:
            def force_release() -> None:
                time.sleep(0.05)
                if thread.is_alive():
                    self.forced_jobs.add(job_id)
                    self.force_release.set()

            threading.Thread(target=force_release, daemon=True).start()
        return True

    def wait(self, job_id: str, timeout: float = 5) -> bool:
        thread = self._threads.get(job_id)
        if thread is None:
            return True
        thread.join(timeout)
        return not thread.is_alive()

    def shutdown(self, timeout_seconds: float = 5) -> None:
        self.shutdown_calls += 1
        for job_id in tuple(self._threads):
            self.cancel_job(job_id)
        for thread in tuple(self._threads.values()):
            thread.join(timeout_seconds)

def _service(
    tmp_path: Path,
    *,
    force_release: threading.Event | None = None,
    wireless_service: object | None = None,
    network_manager: object | None = None,
) -> tuple[NetworkToolsApplicationService, DispatchingProcessAdapter]:
    paths = PathResolver(tmp_path)
    task_service = TaskApplicationService(paths=paths, site_name="demo")
    adapter = DispatchingProcessAdapter(task_service, force_release=force_release)
    service = NetworkToolsApplicationService(
        FakeTrafficService(),
        task_service=task_service,
        paths=paths,
        site_name="demo",
        wireless_scan_service=wireless_service,
        network_manager=network_manager,
        process_adapter=adapter,
    )
    return service, adapter

def _app(tmp_path: Path, service: NetworkToolsApplicationService) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state.network_tools_service = service
    app.state.feature_gate = FeatureGate(tmp_path)
    return app


def test_toolbox_api_reuses_python_calculator_and_rejects_extra_args(tmp_path: Path) -> None:
    service, _adapter = _service(tmp_path)
    app = _app(tmp_path, service)
    app.state.feature_gate.features["capability.network_tools.wireless_scan"] = {"visible": True, "enabled": True}
    with TestClient(app) as client:
        response = client.post("/api/network-tools/toolbox/ipv4", json={"text": "10.0.0.1/24"})
        rejected = client.post("/api/network-tools/toolbox/ipv4", json={"text": "10.0.0.1/24", "extra_args": ["--bad"]})

    assert response.status_code == 200
    assert response.json()["summary"]["network"] == "10.0.0.0"
    assert response.json()["rows"] == []
    assert rejected.status_code == 422


def test_network_toolbox_and_wireless_routes_require_exact_parent_feature_gate(tmp_path: Path) -> None:
    service, _adapter = _service(tmp_path)
    app = _app(tmp_path, service)
    app.state.feature_gate.features["capability.network_tools.toolbox"] = {"visible": False, "enabled": False}
    toolbox_paths = [
        ("post", "/api/network-tools/tasks", {"kind": "single_ping", "target": "host"}),
        ("get", "/api/network-tools/runs", None),
        ("get", "/api/network-tools/runs/task/results", None),
        ("post", "/api/network-tools/runs/task/cancel", None),
        ("post", "/api/network-tools/runs/task/export", {"format": "csv"}),
        ("get", "/api/network-tools/runs/task/artifact", None),
        ("get", "/api/network-tools/artifacts/not-an-id", None),
    ]
    with TestClient(app) as client:
        responses = [
            getattr(client, method)(path, json=body) if body is not None else getattr(client, method)(path)
            for method, path, body in toolbox_paths
        ]
    assert all(response.status_code == 404 for response in responses)


def test_network_service_reuses_traffic_worker_lifecycle_in_composed_webhost(tmp_path: Path) -> None:
    paths = PathResolver(tmp_path)
    task_service = TaskApplicationService(paths=paths, site_name="demo")
    adapter = DispatchingProcessAdapter(task_service)
    traffic = FakeTrafficService()
    traffic.paths = paths
    traffic.task_service = task_service
    traffic.local_adapter = SimpleNamespace(process_adapter=adapter)

    service = NetworkToolsApplicationService(traffic)

    assert service.process_adapter is adapter
    service.close()
    assert adapter.shutdown_calls == 0
