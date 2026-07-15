from __future__ import annotations

import asyncio
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from netconsole.backend.api.network_tools_router import router
from netconsole.core.feature_flags import FeatureGate
from netconsole.core.paths import PathResolver
from netconsole.models.task_state import TaskState
from netconsole.models.wireless_scan_models import TracksideBssidMatch, WirelessAdapter, WirelessNetwork, WirelessScanResult
from netconsole.services.network_tools.application_service import NetworkToolsApplicationService
from netconsole.services.network_tools.wireless_scan_service import WirelessScanRunResult
from netconsole.services.network_tools.toolbox.ping_tools import PingResult


class FakeTrafficService:
    paths = None
    site_name = "demo"

    async def start_tcp_port_test(self, config, execution_target):
        raise AssertionError("TCP Traffic adapter is not part of this test")


def _app(tmp_path: Path, service: NetworkToolsApplicationService) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state.network_tools_service = service
    app.state.feature_gate = FeatureGate(tmp_path)
    return app


def test_toolbox_api_reuses_python_calculator_and_rejects_extra_args(tmp_path: Path) -> None:
    service = NetworkToolsApplicationService(FakeTrafficService(), paths=PathResolver(tmp_path))
    with TestClient(_app(tmp_path, service)) as client:
        response = client.post("/api/network-tools/toolbox/ipv4", json={"text": "10.0.0.1/24"})
        rejected = client.post("/api/network-tools/toolbox/ipv4", json={"text": "10.0.0.1/24", "extra_args": ["--bad"]})

    assert response.status_code == 200
    assert response.json()["summary"]["network"] == "10.0.0.0"
    assert response.json()["rows"] == []
    assert response.json()["errors"] == []
    assert rejected.status_code == 422


def test_network_toolbox_routes_require_parent_feature_gate(tmp_path: Path) -> None:
    service = NetworkToolsApplicationService(FakeTrafficService(), paths=PathResolver(tmp_path))
    app = _app(tmp_path, service)
    app.state.feature_gate.features["web.network_tools_toolbox"] = {"visible": False, "enabled": False}
    requests = [
        ("post", "/api/network-tools/toolbox/ipv4", {"text": "10.0.0.1/24"}),
        ("post", "/api/network-tools/toolbox/ipv6", {"text": "2001:db8::1/64"}),
        ("post", "/api/network-tools/toolbox/vlsm", {"parent": "10.0.0.0/24", "requests": "A,10"}),
        ("post", "/api/network-tools/toolbox/subnets", {"parent": "10.0.0.0/24", "target_prefix": 25}),
        ("post", "/api/network-tools/toolbox/summarize", {"text": "10.0.0.0/24"}),
        ("post", "/api/network-tools/toolbox/wildcard", {"text": "10.0.0.0/24"}),
        ("post", "/api/network-tools/tasks", {"kind": "single_ping", "target": "host"}),
        ("get", "/api/network-tools/runs", None),
        ("get", "/api/network-tools/runs/task", None),
        ("get", "/api/network-tools/runs/task/events", None),
        ("post", "/api/network-tools/runs/task/cancel", None),
        ("post", "/api/network-tools/runs/task/export", {"format": "csv"}),
        ("get", "/api/network-tools/artifacts/not-an-id", None),
    ]
    with TestClient(app) as client:
        responses = [getattr(client, method)(path, json=body) if body is not None else getattr(client, method)(path) for method, path, body in requests]
    assert all(response.status_code == 404 for response in responses)


def test_fake_ping_task_persists_result_and_export_hash(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "netconsole.services.network_tools.application_service.run_single_ping",
        lambda *_args, **_kwargs: PingResult(target="fake-host", status="online", latency_ms=1.2, received=1, sent=1),
    )
    service = NetworkToolsApplicationService(FakeTrafficService(), paths=PathResolver(tmp_path))

    async def exercise() -> None:
        task = await service.start_network_task(kind="single_ping", target="fake-host")
        for _ in range(50):
            await asyncio.sleep(0.01)
            task = service.get_network_task(task.task_id)
            if task and task.status.value == "COMPLETED":
                break
        assert task is not None
        assert task.status.value == "COMPLETED"
        assert task.result["row_count"] == 1
        assert "result_file" not in task.result
        artifact = await service.export_network_task(task.task_id, "csv")
        assert len(str(artifact["sha256"])) == 64
        first_path = service.resolve_artifact(str(artifact["artifact_id"]))
        assert first_path is not None
        assert first_path.name != artifact["filename"]
        assert service.artifact_display_name(str(artifact["artifact_id"])) == artifact["filename"]
        second = await service.export_network_task(task.task_id, "csv", filename="same-name.csv")
        assert second["artifact_id"] != artifact["artifact_id"]
        assert second["filename"] == "same-name.csv"
        assert service.resolve_artifact(str(second["artifact_id"])) is not None
        assert service.resolve_artifact(str(Path("..") / "same-name.csv")) is None
        assert service.resolve_artifact(str(artifact["artifact_id"])) is not None
        restored = NetworkToolsApplicationService(FakeTrafficService(), paths=PathResolver(tmp_path))
        assert restored.resolve_artifact(str(artifact["artifact_id"])) is not None
        try:
            await service.export_network_task(task.task_id, "csv", filename="../escape.csv")
        except ValueError:
            pass
        else:
            raise AssertionError("路径形式的导出文件名必须拒绝")

    asyncio.run(exercise())


def test_task_result_paths_are_not_exposed_or_read_from_persisted_result(tmp_path: Path) -> None:
    service = NetworkToolsApplicationService(FakeTrafficService(), paths=PathResolver(tmp_path))
    task_service = service._ensure_task_service()
    task_id = uuid.uuid4().hex
    task_service.create_external_task(
        task_id=task_id,
        task_type="network_tools.single_ping",
        task_name="单个 Ping",
        source="network_tools_web",
        site_name="demo",
    )
    outside = tmp_path / "outside.jsonl"
    outside.write_text('{"target":"outside"}\n', encoding="utf-8")
    task_service.record_external_event(
        task_id,
        "finished",
        {"result": {"rows": [{"target": "inline"}], "result_file": str(outside), "raw_file": str(outside)}},
        site_name="demo",
    )
    forged = SimpleNamespace(task_id=task_id, result={"rows": [{"target": "inline"}], "result_file": str(outside)})
    assert service._task_rows(forged) == [{"target": "inline"}]

    with TestClient(_app(tmp_path, service)) as client:
        response = client.get(f"/api/network-tools/runs/{task_id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["result_path"] == ""
    assert "result_file" not in payload["result"]
    assert "raw_file" not in payload["result"]
    assert str(outside) not in response.text

    with TestClient(_app(tmp_path, service)) as client:
        events = client.get(f"/api/network-tools/runs/{task_id}/events")
    assert events.status_code == 200
    assert str(outside) not in events.text


def test_continuous_fake_ping_can_be_cancelled(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "netconsole.services.network_tools.application_service.run_single_ping",
        lambda *_args, **_kwargs: PingResult(target="fake-host", status="online", latency_ms=1.0, received=1, sent=1),
    )
    service = NetworkToolsApplicationService(FakeTrafficService(), paths=PathResolver(tmp_path))

    async def exercise() -> None:
        task = await service.start_network_task(kind="continuous_ping", target="fake-host", interval_ms=1)
        await asyncio.sleep(0.02)
        cancelled = service.cancel_network_task(task.task_id)
        assert cancelled.status.value == "STOPPING"
        for _ in range(50):
            await asyncio.sleep(0.01)
            current = service.get_network_task(task.task_id)
            if current and current.status.value == "CANCELLED":
                break
        assert current is not None
        assert current.status.value == "CANCELLED"

    asyncio.run(exercise())


def test_batch_ping_reports_each_result_and_cancels_fake_runner(tmp_path: Path, monkeypatch) -> None:
    progress_seen = threading.Event()

    def fake_batch(targets, *, progress=None, should_stop=None, **_kwargs):
        results = []
        for target in targets:
            if should_stop and should_stop():
                break
            result = PingResult(target=target, status="online", latency_ms=1.0, received=1, sent=1)
            results.append(result)
            if progress:
                progress(result)
                progress_seen.set()
        while not should_stop():
            time.sleep(0.005)
        return results

    monkeypatch.setattr("netconsole.services.network_tools.application_service.run_batch_ping", fake_batch)
    service = NetworkToolsApplicationService(FakeTrafficService(), paths=PathResolver(tmp_path))

    async def exercise() -> None:
        task = await service.start_network_task(kind="batch_ping", targets=["fake-a", "fake-b"])
        assert await asyncio.to_thread(progress_seen.wait, 1)
        current = service.cancel_network_task(task.task_id)
        assert current.status is TaskState.STOPPING
        for _ in range(100):
            await asyncio.sleep(0.01)
            current = service.get_network_task(task.task_id)
            if current and current.status is TaskState.CANCELLED:
                break
        assert current is not None
        assert current.status is TaskState.CANCELLED
        events = service.list_network_task_events(task.task_id)
        progress = [event for event in events if event["type"] == "progress"]
        assert progress
        assert progress[0]["payload"]["current"] == 1
        assert progress[0]["payload"]["total"] == 2

    asyncio.run(exercise())


class FakeWirelessRepository:
    def __init__(self) -> None:
        self.runs: list[dict[str, object]] = []

    def list_runs(self, limit: int = 200) -> list[dict[str, object]]:
        return self.runs[:limit]

    def list_results(self, _scan_id: str) -> list[dict[str, object]]:
        return []


class FakeWirelessService:
    def __init__(self) -> None:
        self.repository = FakeWirelessRepository()

    def list_adapters(self) -> list[WirelessAdapter]:
        return [WirelessAdapter(name="Fake Adapter", guid="fake-guid", state="connected")]

    def scan(self, adapter: WirelessAdapter | None = None) -> WirelessScanRunResult:
        network = WirelessNetwork(ssid="Fake", bssid="aa:bb:cc:00:00:01", rssi_dbm=-50, quality=90, band="5G")
        result = WirelessScanResult(network=network, match=TracksideBssidMatch(matched=False, match_status="unmatched"))
        return WirelessScanRunResult("scan-fake", "start", "end", Path("raw.txt"), [result])


def test_fake_wireless_adapter_project_and_scan_task(tmp_path: Path) -> None:
    service = NetworkToolsApplicationService(
        FakeTrafficService(),
        paths=PathResolver(tmp_path),
        wireless_scan_service=FakeWirelessService(),
    )
    assert service.list_wireless_adapters()[0]["guid"] == "fake-guid"
    project = service.create_wireless_project("Fake Project")
    assert project["name"] == "Fake Project"

    async def reject_missing_project() -> None:
        try:
            await service.start_wireless_scan(adapter_guid="fake-guid", project_id="missing-project")
        except ValueError as exc:
            assert str(exc) == "无线扫描项目不存在"
        else:
            raise AssertionError("无线扫描必须拒绝不存在的项目")

    asyncio.run(reject_missing_project())

    async def exercise() -> None:
        task = await service.start_wireless_scan(adapter_guid="fake-guid", project_id=str(project["project_id"]))
        for _ in range(50):
            await asyncio.sleep(0.01)
            task = service.get_network_task(task.task_id)
            if task and task.status.value == "COMPLETED":
                break
        assert task is not None
        assert task.status.value == "COMPLETED"
        assert task.result["scan_id"] == "scan-fake"
        assert "raw_file" not in task.result

    asyncio.run(exercise())


def test_network_task_target_items_have_length_limit(tmp_path: Path) -> None:
    service = NetworkToolsApplicationService(FakeTrafficService(), paths=PathResolver(tmp_path))
    with TestClient(_app(tmp_path, service)) as client:
        response = client.post(
            "/api/network-tools/tasks",
            json={"kind": "batch_ping", "targets": ["x" * 256]},
        )
    assert response.status_code == 422
