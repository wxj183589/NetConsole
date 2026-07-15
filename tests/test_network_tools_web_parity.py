from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import threading
import time
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from netconsole.backend.api.network_tools_router import router
from netconsole.core.feature_flags import FeatureGate
from netconsole.core.paths import PathResolver
from netconsole.models.task_snapshot import TaskSnapshot, utc_now_iso
from netconsole.models.task_state import TaskState
from netconsole.models.wireless_scan_models import TracksideBssidMatch, WirelessAdapter, WirelessNetwork, WirelessScanResult
from netconsole.repositories.wireless_scan_repository import WirelessScanRepository
from netconsole.services.job_center.job_events import progress_event
from netconsole.services.job_center.job_models import JobSpec
from netconsole.services.job_center.job_runner import run_job
from netconsole.services.job_center.task_application_service import TaskApplicationService
from netconsole.services.job_center.worker_protocol import encode_event
from netconsole.services.network_tools import job_handlers
from netconsole.services.network_tools.application_service import NetworkToolsApplicationService
from netconsole.services.network_tools.job_handlers import (
    NETWORK_BATCH_PING_TASK,
    NETWORK_SINGLE_PING_TASK,
    NETWORK_TASK_SOURCE,
    NETWORK_TOOLBOX_EXPORT_TASK,
    NETWORK_TOOL_OWNER,
    NETWORK_WIRELESS_EXPORT_TASK,
    NETWORK_WIRELESS_SCAN_TASK,
)
from netconsole.services.network_tools.toolbox.ping_tools import PingResult
from netconsole.services.network_tools.wireless_scan_service import WirelessScanRunResult


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


class FakeWirelessWorkerService:
    scan_id = "scan_20260715_120000_deadbeef"
    block_event: threading.Event | None = None

    def __init__(self, site_name: str, paths: PathResolver) -> None:
        self.site_name = site_name
        self.paths = paths
        self.repository = WirelessScanRepository(paths.wireless_scan_db_path(site_name))

    def list_adapters(self) -> list[WirelessAdapter]:
        return [WirelessAdapter(name="Fake Adapter", guid="fake-guid", state="connected")]

    def scan(self, adapter: WirelessAdapter | None = None, *, project_id: str = "") -> WirelessScanRunResult:
        if self.block_event is not None:
            self.block_event.wait(5)
        network = WirelessNetwork(
            ssid="Fake",
            bssid="aa:bb:cc:00:00:01",
            rssi_dbm=-50,
            quality=90,
            band="5G",
        )
        result = WirelessScanResult(
            network=network,
            match=TracksideBssidMatch(matched=False, match_status="unmatched"),
        )
        raw_file = self.paths.wireless_scan_raw_dir(self.site_name) / f"{self.scan_id}.txt"
        raw_file.parent.mkdir(parents=True, exist_ok=True)
        raw_file.write_text("fake wireless raw", encoding="utf-8")
        self.repository.save_scan(
            scan_id=self.scan_id,
            site=self.site_name,
            adapter_name=adapter.name if adapter else "",
            adapter_guid=adapter.guid if adapter else "",
            started_at="2026-07-15 12:00:00",
            ended_at="2026-07-15 12:00:01",
            status="success",
            raw_file=str(raw_file),
            results=[result],
            project_id=project_id,
        )
        return WirelessScanRunResult(
            self.scan_id,
            "2026-07-15 12:00:00",
            "2026-07-15 12:00:01",
            raw_file,
            [result],
        )


def _service(
    tmp_path: Path,
    *,
    force_release: threading.Event | None = None,
    wireless_service: object | None = None,
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


def test_toolbox_api_reuses_python_calculator_and_rejects_extra_args(tmp_path: Path) -> None:
    service, _adapter = _service(tmp_path)
    app = _app(tmp_path, service)
    app.state.feature_gate.features["web.network_tools_wireless_scan"] = {"visible": True, "enabled": True}
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
    app.state.feature_gate.features["web.network_tools_toolbox"] = {"visible": False, "enabled": False}
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


def test_registered_fake_probe_uses_worker_task_minimal_snapshot_paging_and_export(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        job_handlers,
        "run_single_ping",
        lambda *_args, **_kwargs: PingResult(
            target="fake-host",
            status="online",
            latency_ms=1.2,
            received=1,
            sent=1,
            raw_output="secret raw output",
        ),
    )
    service, adapter = _service(tmp_path)

    task = asyncio.run(service.start_network_task(kind="single_ping", target="fake-host"))
    completed = _wait_task(service, adapter, task.task_id)

    assert completed.task_type == NETWORK_SINGLE_PING_TASK
    assert completed.owner == NETWORK_TOOL_OWNER
    assert completed.source == NETWORK_TASK_SOURCE
    assert completed.result == {"result_id": task.task_id, "row_count": 1}
    page = service.list_network_task_results(task.task_id, offset=0, limit=1)
    assert page["total"] == 1
    assert page["items"][0]["target"] == "fake-host"
    assert "raw_output" not in page["items"][0]
    assert NETWORK_SINGLE_PING_TASK in job_handlers.HANDLERS

    with TestClient(_app(tmp_path, service)) as client:
        submitted = client.post(
            f"/api/network-tools/runs/{task.task_id}/export",
            json={"format": "csv", "filename": "probe.csv"},
        )
    assert submitted.status_code == 202
    export_id = submitted.json()["task"]["id"]
    exported = _wait_task(service, adapter, export_id)
    assert exported.task_type == NETWORK_TOOLBOX_EXPORT_TASK
    assert set(exported.result) == {"result_id", "row_count"}
    artifact = service.get_network_export_artifact(export_id)
    path, filename, opened = service.open_network_artifact(str(artifact["artifact_id"]))
    assert filename == "probe.csv"
    assert opened == artifact
    assert hashlib.sha256(path.read_bytes()).hexdigest() == artifact["sha256"]
    manifest = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    assert manifest["task_id"] == export_id
    assert manifest["parent_id"] == task.task_id
    assert manifest["site_name"] == "demo"
    assert manifest["owner"] == NETWORK_TOOL_OWNER
    assert manifest["source"] == NETWORK_TASK_SOURCE
    assert manifest["task_type"] == NETWORK_TOOLBOX_EXPORT_TASK

    restored_adapter = DispatchingProcessAdapter(service.task_service)
    restored = NetworkToolsApplicationService(
        FakeTrafficService(),
        task_service=service.task_service,
        paths=service.paths,
        process_adapter=restored_adapter,
    )
    assert restored.get_network_export_artifact(export_id)["sha256"] == artifact["sha256"]


def test_batch_probe_dispatches_registered_handler_and_never_embeds_rows(tmp_path: Path, monkeypatch) -> None:
    def fake_batch(targets, *, progress=None, **_kwargs):
        rows = [PingResult(target=target, status="online", received=1, sent=1, raw_output="raw") for target in targets]
        for row in rows:
            if progress:
                progress(row)
        return rows

    monkeypatch.setattr(job_handlers, "run_batch_ping", fake_batch)
    service, adapter = _service(tmp_path)
    targets = [f"fake-{index}" for index in range(30)]
    task = asyncio.run(service.start_network_task(kind="batch_ping", targets=targets))
    completed = _wait_task(service, adapter, task.task_id)

    assert completed.task_type == NETWORK_BATCH_PING_TASK
    assert completed.result == {"result_id": task.task_id, "row_count": len(targets)}
    first = service.list_network_task_results(task.task_id, offset=0, limit=7)
    second = service.list_network_task_results(task.task_id, offset=7, limit=7)
    assert len(first["items"]) == len(second["items"]) == 7
    assert first["items"][0]["target"] == "fake-0"
    assert second["items"][0]["target"] == "fake-7"
    assert all("raw_output" not in row for row in first["items"])


def test_toolbox_and_wireless_task_scope_rejects_site_owner_source_and_exact_type_mismatches(tmp_path: Path) -> None:
    service, adapter = _service(tmp_path)
    repository = service.task_service.repository("demo")
    now = utc_now_iso()
    cases = (
        ("wrong-site", "other", NETWORK_TOOL_OWNER, "local", NETWORK_SINGLE_PING_TASK),
        ("wrong-owner", "demo", "other", "local", NETWORK_SINGLE_PING_TASK),
        ("wrong-source", "demo", NETWORK_TOOL_OWNER, "agent", NETWORK_SINGLE_PING_TASK),
        ("wrong-type", "demo", NETWORK_TOOL_OWNER, "local", "network_tools.single_ping_extra"),
    )
    for task_id, site, owner, source, task_type in cases:
        repository.save(TaskSnapshot(
            task_id=task_id,
            task_type=task_type,
            task_name="foreign",
            status=TaskState.RUNNING,
            created_time=now,
            updated_time=now,
            owner=owner,
            source=source,
            site_name=site,
            owner_pid=os.getpid(),
        ))
    repository.save(TaskSnapshot(
        task_id="wireless-only",
        task_type=NETWORK_WIRELESS_SCAN_TASK,
        task_name="wireless",
        status=TaskState.COMPLETED,
        created_time=now,
        updated_time=now,
        owner=NETWORK_TOOL_OWNER,
        source="local",
        site_name="demo",
    ))

    app = _app(tmp_path, service)
    app.state.feature_gate.features["web.network_tools_wireless_scan"] = {"visible": True, "enabled": True}
    with TestClient(app) as client:
        for task_id, *_rest in cases:
            assert client.get(f"/api/network-tools/runs/{task_id}").status_code == 404
            assert client.post(f"/api/network-tools/runs/{task_id}/cancel").status_code == 404
        assert client.get("/api/network-tools/runs/wireless-only").status_code == 404
        assert client.get("/api/network-tools/wireless-scan/tasks/wireless-only").status_code == 200
        assert client.get("/api/network-tools/wireless-scan/tasks/wireless-only/events").status_code == 200
        assert client.post("/api/network-tools/wireless-scan/tasks/wrong-owner/cancel").status_code == 404
    assert not adapter.jobs


def test_active_network_task_is_reconciled_when_its_worker_is_missing(tmp_path: Path) -> None:
    paths = PathResolver(tmp_path)
    task_service = TaskApplicationService(paths=paths, site_name="demo")
    now = utc_now_iso()
    task_service.repository("demo").save(TaskSnapshot(
        task_id="orphan-network-task",
        task_type=NETWORK_SINGLE_PING_TASK,
        task_name="orphan",
        status=TaskState.RUNNING,
        created_time=now,
        updated_time=now,
        owner=NETWORK_TOOL_OWNER,
        source=NETWORK_TASK_SOURCE,
        site_name="demo",
        owner_pid=os.getpid(),
    ))
    adapter = DispatchingProcessAdapter(task_service)
    service = NetworkToolsApplicationService(
        FakeTrafficService(),
        task_service=task_service,
        paths=paths,
        process_adapter=adapter,
    )

    recovered = task_service.repository("demo").get("orphan-network-task")
    assert recovered is not None and recovered.status is TaskState.FAILED
    assert "Worker" in recovered.error_message
    assert service.get_network_task("orphan-network-task") is not None


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


def test_wireless_scan_binds_project_recovers_and_blocking_fake_is_force_cancelled(tmp_path: Path, monkeypatch) -> None:
    paths = PathResolver(tmp_path)
    fake_wireless = FakeWirelessWorkerService("demo", paths)
    monkeypatch.setattr(job_handlers, "WirelessScanService", FakeWirelessWorkerService)
    service, adapter = _service(tmp_path, wireless_service=fake_wireless)
    project = service.create_wireless_project("Fake Project")
    task = asyncio.run(service.start_wireless_scan(adapter_guid="fake-guid", project_id=str(project["project_id"])))
    completed = _wait_task(service, adapter, task.task_id, wireless=True)

    assert completed.result == {"result_id": FakeWirelessWorkerService.scan_id, "row_count": 1}
    history = service.list_wireless_runs()
    assert history[0]["project_id"] == project["project_id"]
    assert history[0]["raw_file"] == f"{FakeWirelessWorkerService.scan_id}.txt"
    assert service.get_network_task(task.task_id) is None
    assert service.get_wireless_task(task.task_id) is not None

    app = _app(tmp_path, service)
    app.state.feature_gate.features["web.network_tools_wireless_scan"] = {"visible": True, "enabled": True}
    with TestClient(app) as client:
        submitted = client.post(
            "/api/network-tools/wireless-scan/export",
            json={"scan_id": FakeWirelessWorkerService.scan_id, "format": "csv", "filename": "wireless.csv"},
        )
    assert submitted.status_code == 202
    export_id = submitted.json()["task"]["id"]
    exported = _wait_task(service, adapter, export_id, wireless=True)
    assert exported.task_type == NETWORK_WIRELESS_EXPORT_TASK
    wireless_artifact = service.get_wireless_export_artifact(export_id)
    _path, display_name, _metadata = service.open_wireless_artifact(str(wireless_artifact["artifact_id"]))
    assert display_name == "wireless.csv"

    release = threading.Event()
    FakeWirelessWorkerService.block_event = release
    blocking_service, blocking_adapter = _service(
        tmp_path / "blocking",
        force_release=release,
        wireless_service=FakeWirelessWorkerService("demo", PathResolver(tmp_path / "blocking")),
    )
    blocking_project = blocking_service.create_wireless_project("Blocking")
    blocking_task = asyncio.run(blocking_service.start_wireless_scan(project_id=str(blocking_project["project_id"])))
    time.sleep(0.05)
    cancelled = blocking_service.cancel_wireless_task(blocking_task.task_id)
    assert cancelled.status is TaskState.STOPPING
    terminal = _wait_task(blocking_service, blocking_adapter, blocking_task.task_id, wireless=True)
    assert terminal.status is TaskState.CANCELLED
    assert blocking_task.task_id in blocking_adapter.forced_jobs
    FakeWirelessWorkerService.block_event = None


def test_wireless_project_storage_is_locked_atomic_and_history_schema_migrates(tmp_path: Path) -> None:
    paths = PathResolver(tmp_path)
    first, _first_adapter = _service(tmp_path)
    second, _second_adapter = _service(tmp_path)
    created: list[str] = []

    def create(service: NetworkToolsApplicationService, index: int) -> None:
        created.append(str(service.create_wireless_project(f"Project {index}")["project_id"]))

    threads = [threading.Thread(target=create, args=(first if index % 2 else second, index)) for index in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    projects = first.list_wireless_projects()
    assert len(created) == len(projects) == 20
    assert len({item["project_id"] for item in projects}) == 20
    assert not list(paths.wireless_scan_projects_dir("demo").glob("*.tmp"))

    db_path = paths.wireless_scan_db_path("legacy")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    import sqlite3

    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE TABLE wireless_scan_runs (scan_id TEXT PRIMARY KEY, site TEXT NOT NULL, adapter_name TEXT DEFAULT '', adapter_guid TEXT DEFAULT '', started_at TEXT NOT NULL, ended_at TEXT NOT NULL, status TEXT NOT NULL, network_count INTEGER DEFAULT 0, raw_file TEXT DEFAULT '')")
    repository = WirelessScanRepository(db_path)
    with repository._connect() as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(wireless_scan_runs)").fetchall()}
    assert "project_id" in columns


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


def test_network_task_target_items_have_length_limit(tmp_path: Path) -> None:
    service, _adapter = _service(tmp_path)
    with TestClient(_app(tmp_path, service)) as client:
        response = client.post(
            "/api/network-tools/tasks",
            json={"kind": "batch_ping", "targets": ["x" * 256]},
        )
    assert response.status_code == 422
