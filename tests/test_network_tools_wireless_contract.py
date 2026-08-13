from __future__ import annotations

import asyncio

from pathlib import Path

import threading

import time

from types import SimpleNamespace

from fastapi import FastAPI

from fastapi.testclient import TestClient

import pytest

from netconsole.backend.api.network_tools_router import router

from netconsole.core.feature_flags import FeatureGate

from netconsole.core.paths import PathResolver

from netconsole.models.task_snapshot import TaskSnapshot

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
    NETWORK_TASK_SOURCE,
    NETWORK_TOOL_OWNER,
    NETWORK_WIRELESS_EXPORT_TASK,
)

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

    def __init__(self, site_name: str, paths: PathResolver, *, scan_source: str = "auto") -> None:
        self.site_name = site_name
        self.paths = paths
        self.scan_source = scan_source
        self.repository = WirelessScanRepository(paths.wireless_scan_db_path(site_name))

    def list_adapters(self) -> list[WirelessAdapter]:
        return [WirelessAdapter(name="Fake Adapter", guid="fake-guid", state="connected")]

    def scan(
        self,
        adapter: WirelessAdapter | None = None,
        *,
        project_id: str = "",
        project_name: str = "",
        project_description: str = "",
    ) -> WirelessScanRunResult:
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
            project_name=project_name,
            project_description=project_description,
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


def test_wireless_scan_binds_project_recovers_and_blocking_fake_is_force_cancelled(tmp_path: Path, monkeypatch) -> None:
    paths = PathResolver(tmp_path)
    fake_wireless = FakeWirelessWorkerService("demo", paths)
    monkeypatch.setattr(job_handlers, "WirelessScanService", FakeWirelessWorkerService)
    service, adapter = _service(tmp_path, wireless_service=fake_wireless)
    project = service.create_wireless_project("Fake Project", "history snapshot")
    task = asyncio.run(service.start_wireless_scan(adapter_guid="fake-guid", project_id=str(project["project_id"]), scan_source="wlan_api"))
    completed = _wait_task(service, adapter, task.task_id, wireless=True)

    assert completed.result == {"result_id": FakeWirelessWorkerService.scan_id, "row_count": 1}
    assert adapter.jobs[-1].params["scan_source"] == "wlan_api"
    history = service.list_wireless_runs()
    assert history["total"] == 1
    assert history["items"][0]["project_id"] == project["project_id"]
    assert history["items"][0]["project_name"] == "Fake Project"
    assert history["items"][0]["project_description"] == "history snapshot"
    assert history["items"][0]["raw_file"] == f"{FakeWirelessWorkerService.scan_id}.txt"
    detail = service.get_wireless_run_detail(FakeWirelessWorkerService.scan_id)
    assert detail["raw_output"] == "fake wireless raw"
    assert service.get_network_task(task.task_id) is None
    assert service.get_wireless_task(task.task_id) is not None

    app = _app(tmp_path, service)
    app.state.feature_gate.features["capability.network_tools.wireless_scan"] = {"visible": True, "enabled": True}
    with TestClient(app) as client:
        detail_response = client.get(f"/api/network-tools/wireless-scan/runs/{FakeWirelessWorkerService.scan_id}")
        submitted = client.post(
            "/api/network-tools/wireless-scan/export",
            json={"scan_id": FakeWirelessWorkerService.scan_id, "format": "csv", "filename": "wireless.csv"},
        )
    assert detail_response.status_code == 200
    assert detail_response.json()["raw_output"] == "fake wireless raw"
    assert submitted.status_code == 202
    export_id = submitted.json()["task"]["id"]
    exported = _wait_task(service, adapter, export_id, wireless=True)
    assert exported.task_type == NETWORK_WIRELESS_EXPORT_TASK
    assert exported.result["task_type"] == NETWORK_WIRELESS_EXPORT_TASK
    assert exported.result["site_name"] == "demo"
    assert exported.result["owner"] == NETWORK_TOOL_OWNER
    assert exported.result["source"] == NETWORK_TASK_SOURCE
    wireless_artifact = service.get_wireless_export_artifact(export_id)
    _path, display_name, _metadata = service.open_wireless_artifact(str(wireless_artifact["artifact_id"]))
    assert display_name == "wireless.csv"
    service.delete_wireless_project(str(project["project_id"]))
    assert all(item["project_id"] != project["project_id"] for item in service.list_wireless_projects())
    deleted_project_history = service.list_wireless_runs()["items"][0]
    assert deleted_project_history["project_name"] == "Fake Project"
    assert deleted_project_history["project_description"] == "history snapshot"

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
    with pytest.raises(ValueError, match="进行中的无线扫描"):
        blocking_service.delete_wireless_project(str(blocking_project["project_id"]))
    blocking_app = _app(tmp_path / "blocking", blocking_service)
    blocking_app.state.feature_gate.features["capability.network_tools.wireless_scan"] = {"visible": True, "enabled": True}
    with TestClient(blocking_app) as client:
        response = client.delete(f"/api/network-tools/wireless-scan/projects/{blocking_project['project_id']}")
    assert response.status_code == 409
    cancelled = blocking_service.cancel_wireless_task(blocking_task.task_id)
    assert cancelled.status is TaskState.STOPPING
    terminal = _wait_task(blocking_service, blocking_adapter, blocking_task.task_id, wireless=True)
    assert terminal.status is TaskState.CANCELLED
    assert blocking_task.task_id in blocking_adapter.forced_jobs
    blocking_service.delete_wireless_project(str(blocking_project["project_id"]))
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
    assert {"project_id", "project_name", "project_description"} <= columns


def test_wireless_runs_and_results_use_sql_pagination_beyond_old_limits(tmp_path: Path) -> None:
    fake_wireless = FakeWirelessWorkerService("demo", PathResolver(tmp_path))
    repository = fake_wireless.repository
    scan_id = "scan_20260715_120000_deadbeef"
    with repository._connect() as connection:
        connection.executemany(
            """
            INSERT INTO wireless_scan_runs (
                scan_id, site, project_id, project_name, project_description,
                adapter_name, adapter_guid, started_at, ended_at, status, network_count, raw_file
            ) VALUES (?, 'demo', '', '', '', '', '', ?, ?, 'success', ?, '')
            """,
            [
                (
                    scan_id if index == 0 else f"scan_{index:08d}",
                    f"2026-07-15 12:{index // 60:02d}:{index % 60:02d}",
                    f"2026-07-15 12:{index // 60:02d}:{index % 60:02d}",
                    2105 if index == 0 else 0,
                )
                for index in range(1006)
            ],
        )
        connection.executemany(
            "INSERT INTO wireless_scan_results (scan_id, ssid, bssid, rssi_dbm) VALUES (?, ?, ?, ?)",
            [
                (scan_id, f"ssid-{index}", f"00:00:00:{index // 65536:02x}:{index // 256 % 256:02x}:{index % 256:02x}", -50)
                for index in range(2105)
            ],
        )
        connection.execute(
            """
            UPDATE wireless_scan_results
            SET matched_trackside_ap = 1, band = '5G', matched_radio_id = 2,
                matched_ap_name = '轨旁-唯一', matched_station = '测试站'
            WHERE scan_id = ? AND ssid = 'ssid-2104'
            """,
            (scan_id,),
        )
        connection.commit()

    service, _adapter = _service(tmp_path, wireless_service=fake_wireless)
    run_page = service.list_wireless_runs(page=21, page_size=50)
    result_page = service.list_wireless_results(scan_id, page=22, page_size=100)
    filtered_page = service.list_wireless_results(
        scan_id,
        page=1,
        page_size=50,
        only_trackside=True,
        band="5G",
        radio="2",
        search="测试站",
    )

    assert run_page["total"] == 1006
    assert run_page["page"] == 21
    assert run_page["page_size"] == 50
    assert len(run_page["items"]) == 6
    assert result_page["total"] == 2105
    assert result_page["page"] == 22
    assert result_page["page_size"] == 100
    assert len(result_page["items"]) == 5
    assert filtered_page["total"] == 1
    assert filtered_page["items"][0]["display_ap_name"] == "轨旁-唯一"

    app = _app(tmp_path, service)
    app.state.feature_gate.features["capability.network_tools.wireless_scan"] = {"visible": True, "enabled": True}
    with TestClient(app) as client:
        response = client.get("/api/network-tools/wireless-scan/runs", params={"page": 21, "page_size": 50})
        results_response = client.get(
            f"/api/network-tools/wireless-scan/runs/{scan_id}/results",
            params={"page": 22, "page_size": 100},
        )
        filtered_response = client.get(
            f"/api/network-tools/wireless-scan/runs/{scan_id}/results",
            params={"page": 1, "page_size": 50, "only_trackside": True, "band": "5G", "radio": "2", "search": "测试站"},
        )
    assert response.status_code == results_response.status_code == 200
    assert response.json()["total"] == 1006
    assert len(results_response.json()["items"]) == 5
    assert filtered_response.json()["total"] == 1
