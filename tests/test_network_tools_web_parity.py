from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from netconsole.backend.api.network_tools_router import router
from netconsole.core.feature_flags import FeatureGate
from netconsole.core.paths import PathResolver
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
        artifact = await service.export_network_task(task.task_id, "csv")
        assert len(str(artifact["sha256"])) == 64
        assert service.resolve_artifact(str(artifact["artifact_id"])) is not None

    asyncio.run(exercise())


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

    asyncio.run(exercise())
