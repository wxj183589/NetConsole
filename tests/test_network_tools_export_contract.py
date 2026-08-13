from __future__ import annotations

import asyncio

import hashlib

import json

from pathlib import Path

import threading

import time

from types import SimpleNamespace

from fastapi import FastAPI

from fastapi.testclient import TestClient

from netconsole.backend.api.network_tools_router import router

from netconsole.core.feature_flags import FeatureGate

from netconsole.core.paths import PathResolver

from netconsole.models.task_snapshot import TaskSnapshot

from netconsole.models.task_state import TaskState

from netconsole.services.job_center.job_events import progress_event

from netconsole.services.job_center.job_models import JobSpec

from netconsole.services.job_center.job_runner import run_job

from netconsole.services.job_center.task_application_service import TaskApplicationService

from netconsole.services.job_center.worker_protocol import encode_event

from netconsole.services.network_tools import job_handlers

from netconsole.services.network_tools.application_service import NetworkToolsApplicationService

from netconsole.services.network_tools.toolbox.ping_tools import PingResult

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

def _wait_task(service: NetworkToolsApplicationService, adapter: DispatchingProcessAdapter, task_id: str, *, wireless: bool = False) -> TaskSnapshot:
    assert adapter.wait(task_id, 10)
    task = service.get_wireless_task(task_id) if wireless else service.get_network_task(task_id)
    assert task is not None
    return task


def test_export_manifest_tamper_and_foreign_scope_are_rejected(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(job_handlers, "run_single_ping", lambda *_args, **_kwargs: PingResult(target="fake", status="online", received=1, sent=1))
    service, adapter = _service(tmp_path)
    probe = asyncio.run(service.start_network_task(kind="single_ping", target="fake"))
    _wait_task(service, adapter, probe.task_id)
    export = asyncio.run(service.export_network_task(probe.task_id, "csv"))
    _wait_task(service, adapter, export.task_id)
    artifact = service.get_network_export_artifact(export.task_id)
    path, _filename, _metadata = service.open_network_artifact(str(artifact["artifact_id"]))
    path.write_bytes(path.read_bytes() + b"tampered")
    manifest_path = path.with_suffix(".json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest["size"] = path.stat().st_size
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    with TestClient(_app(tmp_path, service)) as client:
        assert client.get(f"/api/network-tools/artifacts/{artifact['artifact_id']}").status_code == 409
        assert client.get(f"/api/network-tools/wireless-scan/artifacts/{artifact['artifact_id']}").status_code == 404
        assert client.get(f"/api/network-tools/runs/{export.task_id}/artifact").status_code == 409


def test_export_failure_cleans_output_and_records_failed_task(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(job_handlers, "run_single_ping", lambda *_args, **_kwargs: PingResult(target="fake", status="online", received=1, sent=1))
    service, adapter = _service(tmp_path)
    probe = asyncio.run(service.start_network_task(kind="single_ping", target="fake"))
    _wait_task(service, adapter, probe.task_id)
    monkeypatch.setattr(job_handlers, "_export_worker_command", lambda _path: [str(tmp_path / "missing-export-worker.exe")])
    export = asyncio.run(service.export_network_task(probe.task_id, "csv"))
    failed = _wait_task(service, adapter, export.task_id)

    assert failed.status is TaskState.FAILED
    artifact_id = str(adapter.jobs[-1].params["artifact_id"])
    root = service.paths.toolbox_outputs_dir("demo")
    assert not (root / f"{artifact_id}.csv").exists()
    assert not (root / f"{artifact_id}.json").exists()
