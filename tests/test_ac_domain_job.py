from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.services.ac.ac_models import (
    AcFitApDetailRefreshRequest,
    AcResourceRefreshRequest,
    AcResourceRefreshResult,
    AcResourceSnapshot,
)
from netconsole.services.ac.ac_resource_service import AcResourceRefreshCancelled, AcResourceService
from netconsole.services.background_job import BackgroundJob
from netconsole.services.job_center.handlers import ac_jobs
from netconsole.services.job_center.job_runner import run_job


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _ac_device() -> Device:
    return Device.from_mapping(
        {
            "id": 1,
            "device_uuid": "ac-001",
            "name": "测试 AC",
            "primary_address": "192.0.2.10",
            "device_vendor": "H3C",
            "device_type": "AC",
            "snmp_v2c_enabled": 1,
            "snmp_port": 161,
            "snmp_ro_community": "public",
        }
    )


class _FakeDeviceRepository:
    def __init__(self, device: Device) -> None:
        self.device = device

    def list(self, **_kwargs):
        return [self.device]


class _FakeAcRepository:
    def __init__(self) -> None:
        self.summary: dict[str, object | None] = {"total_aps": 1, "online_aps": 1, "offline_aps": 0}
        self.resources: list[dict[str, object | None]] = [{"ap_name": "AP-01", "state": "Run"}]

    def get_ac_ap_summary(self, _device_uuid: str):
        return dict(self.summary)

    def list_fit_ap_resources_with_metadata(self, _device_uuid: str):
        return [dict(row) for row in self.resources]

    def upsert_ac_ap_dynamic_summary(self, _device_uuid: str, summary: dict[str, object | None]):
        self.summary = dict(summary)

    def replace_fit_ap_resources(self, _device_uuid: str, resources: list[dict[str, object | None]]) -> None:
        self.resources = [dict(row) for row in resources]


def test_ac_resource_service_auto_uses_existing_cli_collector_and_snapshot(tmp_path: Path) -> None:
    device = _ac_device()
    repository = _FakeAcRepository()
    calls: list[dict[str, object]] = []

    def cli_collector(ac_device, site_name, **kwargs):
        calls.append({"device": ac_device, "site_name": site_name, **kwargs})
        kwargs["progress"]("正在解析FIT-AP资源...")
        return SimpleNamespace(
            success=True,
            collect_run_uuid="run-001",
            raw_log_path="raw/ac.log",
            fit_ap_resources_updated=1,
            unauthenticated_rows_updated=2,
            bbssid_rows_parsed=3,
            lldp_rows_parsed=4,
            error_message=None,
        )

    progress: list[str] = []
    service = AcResourceService(
        _FakeDeviceRepository(device),  # type: ignore[arg-type]
        repository,  # type: ignore[arg-type]
        PathResolver(tmp_path),
        cli_collector=cli_collector,
    )
    result = service.refresh(
        AcResourceRefreshRequest(device_uuid="ac-001", site_name="demo"),
        progress_callback=lambda _stage, _current, _total, message: progress.append(message),
    )

    assert result.success is True
    assert result.source == "cli"
    assert result.fit_ap_resources_updated == 1
    assert result.lldp_rows_parsed == 4
    assert result.snapshot.resources[0]["ap_name"] == "AP-01"
    assert calls[0]["device"] is device
    assert calls[0]["site_name"] == "demo"
    assert any("解析FIT-AP资源" in message for message in progress)


def test_ac_resource_service_rejects_removed_snmp_source_and_supports_cancel(tmp_path: Path) -> None:
    service = AcResourceService(
        _FakeDeviceRepository(_ac_device()),  # type: ignore[arg-type]
        _FakeAcRepository(),  # type: ignore[arg-type]
        PathResolver(tmp_path),
    )

    with pytest.raises(ValueError, match="不支持的 AC 资源采集来源"):
        service.refresh(
            AcResourceRefreshRequest(
                device_uuid="ac-001",
                site_name="demo",
                source="snmp",
            )
        )
    with pytest.raises(AcResourceRefreshCancelled):
        service.refresh(
            AcResourceRefreshRequest(device_uuid="ac-001", site_name="demo"),
            should_cancel=lambda: True,
        )


def test_ac_resource_service_runs_info_and_single_ap_collectors(tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []

    def info_collector(_device, _site_name, **_kwargs):
        calls.append(("info", ""))
        return SimpleNamespace(
            success=True, collect_run_uuid="info-1", raw_log_path="", error_message=None,
            command_results=[], summary_updated=True, https_port=10443, https_port_persisted=True,
        )

    def detail_collector(_device, _site_name, **kwargs):
        calls.append(("detail", kwargs["target_ap_uuid"]))
        return SimpleNamespace(
            success=True, collect_run_uuid="detail-1", raw_log_path="", error_message=None,
            command_results=[], fit_ap_resources_updated=1, bbssid_rows_parsed=1, lldp_rows_parsed=1,
        )

    service = AcResourceService(
        _FakeDeviceRepository(_ac_device()),  # type: ignore[arg-type]
        _FakeAcRepository(),  # type: ignore[arg-type]
        PathResolver(tmp_path),
        info_collector=info_collector,
        detail_cli_collector=detail_collector,
    )
    info = service.refresh_ac_info(AcResourceRefreshRequest("ac-001", "demo"))
    detail = service.refresh_ap_detail(AcFitApDetailRefreshRequest("ac-001", "ap-1", "demo"))

    assert info.https_port == 10443
    assert info.summary_updated is True
    assert detail.target_ap_uuid == "ap-1"
    assert detail.bbssid_rows_parsed == 1
    assert calls == [("info", ""), ("detail", "ap-1")]


def test_ac_fit_ap_resource_job_finished_failed_and_cancelled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    snapshot = AcResourceSnapshot("ac-001", {"total_aps": 1}, [{"ap_name": "AP-01"}])
    state = {"mode": "success"}

    class FakeAcService:
        def __init__(self, _resource_service) -> None:
            pass

        def refresh_ap_resources(self, _request, *, progress_callback=None, should_cancel=None):
            del should_cancel
            if progress_callback is not None:
                progress_callback("ac_fit_ap_collect", 1, 1, "采集完成")
            if state["mode"] == "cancel":
                raise AcResourceRefreshCancelled("用户已取消更新")
            if state["mode"] == "failed":
                return AcResourceRefreshResult(False, "cli", snapshot, error_message="SSH连接失败")
            return AcResourceRefreshResult(True, "cli", snapshot, fit_ap_resources_updated=1)

    monkeypatch.setattr(ac_jobs, "AcService", FakeAcService)
    job = BackgroundJob(
        job_id="ac-resource-job",
        task_type="ac_fit_ap_resources_refresh",
        params={
            "mode": "collect",
            "device_uuid": "ac-001",
            "site_name": "demo",
            "db_path": str(tmp_path / "devices.db"),
            "data_root": str(tmp_path),
        },
    )
    progress: list[str] = []

    finished = run_job(job, progress_callback=lambda stage, *_args: progress.append(stage))
    assert finished.ok is True
    assert finished.result["collection"]["source"] == "cli"
    assert finished.result["resources"][0]["ap_name"] == "AP-01"
    assert progress == ["ac_fit_ap_collect"]

    state["mode"] = "failed"
    failed = run_job(job)
    assert failed.ok is False
    assert failed.error == "SSH连接失败"

    state["mode"] = "cancel"
    cancelled = run_job(job)
    assert cancelled.cancelled is True
    assert cancelled.error == "用户已取消更新"


def test_ac_fit_ap_resource_job_keeps_legacy_load_mode(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    snapshot = AcResourceSnapshot("ac-001", {"total_aps": 2}, [{"ap_name": "AP-01"}, {"ap_name": "AP-02"}])

    class FakeResourceService:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def load_snapshot(self, ac_uuid: str) -> AcResourceSnapshot:
            assert ac_uuid == "ac-001"
            return snapshot

    monkeypatch.setattr(ac_jobs, "AcResourceService", FakeResourceService)
    result = run_job(
        BackgroundJob(
            job_id="ac-resource-load",
            task_type="ac_fit_ap_resources_refresh",
            params={"ac_uuid": "ac-001", "db_path": str(tmp_path / "devices.db"), "data_root": str(tmp_path)},
        )
    )

    assert result.ok is True
    assert result.result["summary"]["total_aps"] == 2
    assert len(result.result["resources"]) == 2


def test_ac_info_and_fit_ap_detail_jobs_deliver_collection_results(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    snapshot = AcResourceSnapshot("ac-001", {"cpu_usage": "16%"}, [{"ap_uuid": "ap-1", "ap_name": "AP-01"}])

    class FakeAcService:
        def __init__(self, _resource_service) -> None:
            pass

        def refresh_ac_info(self, request, **_kwargs):
            assert request.device_uuid == "ac-001"
            return AcResourceRefreshResult(
                True, "cli", snapshot, summary_updated=True, https_port=10443, https_port_persisted=True
            )

        def refresh_ap_detail(self, request, **_kwargs):
            assert request.ap_uuid == "ap-1"
            return AcResourceRefreshResult(
                True, "cli", snapshot, fit_ap_resources_updated=1, bbssid_rows_parsed=1, target_ap_uuid="ap-1"
            )

    monkeypatch.setattr(ac_jobs, "AcService", FakeAcService)
    common = {
        "device_uuid": "ac-001",
        "site_name": "demo",
        "db_path": str(tmp_path / "devices.db"),
        "data_root": str(tmp_path),
    }
    info = run_job(BackgroundJob(job_id="ac-info-job", task_type="ac_info_refresh", params=common))
    detail = run_job(
        BackgroundJob(
            job_id="ap-detail-job",
            task_type="ac_fit_ap_detail_refresh",
            params={**common, "ap_uuid": "ap-1"},
        )
    )

    assert info.ok is True
    assert info.result["collection"]["https_port"] == 10443
    assert detail.ok is True
    assert detail.result["collection"]["target_ap_uuid"] == "ap-1"
