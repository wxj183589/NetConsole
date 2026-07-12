from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.services.ac.ac_models import AcOpticalRefreshRequest, AcOpticalRefreshResult, AcOpticalSnapshot
from netconsole.services.ac.ac_optical_service import AcOpticalRefreshCancelled, AcOpticalService
from netconsole.services.background_job import BackgroundJob
from netconsole.services.h3c_ac_collect_service import FitApOpticalCollectResult
from netconsole.services.job_center.handlers import ac_jobs
from netconsole.services.job_center.job_registry import registered_task_types
from netconsole.services.job_center.job_runner import run_job
from netconsole.services.offline_ap_ledger import OFFLINE_AP_STATUS_TEXT
from netconsole.ui.pages.ac_management_page import AcManagementPage


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _device(name: str = "测试 AC", device_uuid: str = "ac-001", device_type: str = "AC") -> Device:
    return Device.from_mapping(
        {
            "id": 1,
            "device_uuid": device_uuid,
            "name": name,
            "primary_address": "192.0.2.10",
            "device_vendor": "H3C",
            "device_type": device_type,
        }
    )


class _DeviceRepository:
    def __init__(self) -> None:
        self.devices = [_device(), _device("SW-01", "sw-001", "SWITCH")]

    def list(self, **kwargs):
        device_type = str(kwargs.get("device_type") or "").upper()
        if device_type:
            return [device for device in self.devices if str(device.device_type or "").upper() == device_type]
        return list(self.devices)


class _AcRepository:
    def __init__(self) -> None:
        self.summary = {"total_aps": 2, "online_aps": 1, "offline_aps": 1}
        self.resources = [
            {"ap_uuid": "ap-1", "ap_name": "AP-01", "ap_mac": "0011-2233-4455", "state": "Run", "site": "A站"},
            {"ap_uuid": "ap-2", "ap_name": "AP-02", "ap_mac": "0011-2233-4466", "state": "Offline", "site": "A站"},
        ]
        self.optical_rows = [
            {
                "ap_uuid": "ap-1",
                "ap_name": "AP-01",
                "neighbor_device_name": "SW-01",
                "neighbor_interface": "GigabitEthernet1/0/1",
                "optical_alarm_status": "normal",
                "ap_optical_status": "normal",
            },
            {
                "ap_uuid": "ap-2",
                "ap_name": "AP-02",
                "neighbor_device_name": "SW-01",
                "neighbor_interface": "GigabitEthernet1/0/2",
                "optical_alarm_status": "no_light",
                "ap_optical_status": "no_light",
            },
        ]

    def get_ac_ap_summary(self, _device_uuid: str):
        return dict(self.summary)

    def list_fit_ap_resources_with_metadata(self, _device_uuid: str):
        return [dict(row) for row in self.resources]

    def list_fit_ap_optical(self, _device_uuid: str):
        return [dict(row) for row in self.optical_rows]


class _FactRepository:
    def list_optical_modules(self, device_uuid: str):
        if device_uuid != "sw-001":
            return []
        return [
            {"interface_name": "GigabitEthernet1/0/1", "rx_power": None, "port_status": "DOWN"},
            {"interface_name": "GigabitEthernet1/0/2", "rx_power": "-15.0", "port_status": "UP"},
        ]


def _service(tmp_path: Path, collector) -> tuple[AcOpticalService, _AcRepository]:
    repository = _AcRepository()
    return (
        AcOpticalService(
            _DeviceRepository(),  # type: ignore[arg-type]
            repository,  # type: ignore[arg-type]
            _FactRepository(),  # type: ignore[arg-type]
            PathResolver(tmp_path),
            cli_collector=collector,
        ),
        repository,
    )


def test_ac_optical_service_refreshes_batch_and_single_without_changing_collector_rules(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []

    def collector(device, site_name, **kwargs):
        calls.append({"device": device, "site_name": site_name, **kwargs})
        kwargs["progress"]("正在采集 AP 侧光衰")
        return FitApOpticalCollectResult(True, False, "ac-001", "run-001", 2, 0, None)

    service, _repository = _service(tmp_path, collector)
    progress: list[str] = []
    batch = service.refresh_fit_ap_optical(
        AcOpticalRefreshRequest("ac-001", "demo", max_workers=50),
        progress_callback=lambda _stage, _current, _total, message: progress.append(message),
    )
    single = service.refresh_single_ap_optical(
        AcOpticalRefreshRequest(
            "ac-001",
            "demo",
            refresh_scope="single",
            target_ap_uuids=["ap-1"],
            target_ap_macs=["0011-2233-4455"],
            target_ap_names=["AP-01"],
        )
    )

    assert batch.success is True
    assert batch.snapshot.optical_rows[0]["ap_name"] == "AP-01"
    assert calls[0]["max_workers"] == 50
    assert calls[0]["target_ap_uuids"] is None
    assert calls[1]["target_ap_uuids"] == ["ap-1"]
    assert single.refresh_scope == "single"
    assert any("采集 AP 侧光衰" in message for message in progress)


def test_ac_optical_service_preserves_offline_association_and_does_not_map_switch_no_light_to_ap_alarm(tmp_path: Path) -> None:
    service, _repository = _service(
        tmp_path,
        lambda *_args, **_kwargs: FitApOpticalCollectResult(True, False, "ac-001", "run-001", 2, 0, None),
    )

    snapshot = service.load_optical_snapshot("ac-001")
    rows = {str(row["ap_name"]): row for row in snapshot.optical_rows}

    assert rows["AP-01"]["switch_optical_status"] == "no_light"
    assert rows["AP-01"]["is_ap_offline"] is False
    assert rows["AP-01"]["optical_alarm_status"] == "normal"
    assert rows["AP-02"]["is_ap_offline"] is True
    assert rows["AP-02"]["optical_alarm_status"] == OFFLINE_AP_STATUS_TEXT
    assert rows["AP-02"]["data_source"] == "historical"


def test_ac_optical_service_returns_structured_failure_and_checks_cancel(tmp_path: Path) -> None:
    service, _repository = _service(
        tmp_path,
        lambda *_args, **_kwargs: FitApOpticalCollectResult(False, False, "ac-001", "run-failed", 0, 2, "AP Telnet失败"),
    )

    failed = service.refresh_fit_ap_optical(AcOpticalRefreshRequest("ac-001", "demo"))

    assert failed.success is False
    assert failed.failed_aps == 2
    assert failed.error_message == "AP Telnet失败"
    assert failed.to_payload()["collection"]["error_message"] == "AP Telnet失败"
    with pytest.raises(AcOpticalRefreshCancelled, match="用户已取消更新"):
        service.refresh_fit_ap_optical(
            AcOpticalRefreshRequest("ac-001", "demo"),
            should_cancel=lambda: True,
        )


def test_ac_optical_job_success_partial_single_failed_cancelled_and_clean_stdout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    snapshot = AcOpticalSnapshot("ac-001", {"total_aps": 1}, [{"ap_name": "AP-01"}], [{"ap_name": "AP-01"}])
    state = {"mode": "success", "method": ""}

    class FakeOpticalService:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def refresh_fit_ap_optical(self, request, *, progress_callback=None, should_cancel=None):
            del should_cancel
            state["method"] = "batch"
            if progress_callback is not None:
                progress_callback("ac_fit_ap_optical_collect", 1, 1, "光衰采集完成")
            return self._result(request)

        def refresh_single_ap_optical(self, request, *, progress_callback=None, should_cancel=None):
            del progress_callback, should_cancel
            state["method"] = "single"
            assert request.target_ap_names == ["AP-01"]
            return self._result(request)

        def _result(self, request):
            if state["mode"] == "cancel":
                raise AcOpticalRefreshCancelled("用户已取消更新")
            if state["mode"] == "failed":
                return AcOpticalRefreshResult(False, False, "cli", request.refresh_scope, snapshot, error_message="SSH连接失败")
            partial = state["mode"] == "partial"
            return AcOpticalRefreshResult(True, partial, "cli", request.refresh_scope, snapshot, optical_rows_updated=1, failed_aps=1 if partial else 0)

    monkeypatch.setattr(ac_jobs, "AcOpticalService", FakeOpticalService)
    base_params = {
        "mode": "collect",
        "device_uuid": "ac-001",
        "site_name": "demo",
        "db_path": str(tmp_path / "devices.db"),
        "data_root": str(tmp_path),
    }
    job = BackgroundJob(job_id="optical-job", task_type="ac_fit_ap_optical_refresh", params=base_params)
    progress: list[str] = []

    success = run_job(job, progress_callback=lambda stage, *_args: progress.append(stage))
    assert success.ok is True
    assert success.result["collection"]["optical_rows_updated"] == 1
    assert progress == ["ac_fit_ap_optical_collect"]
    assert capsys.readouterr().out == ""

    state["mode"] = "partial"
    partial = run_job(job)
    assert partial.ok is True
    assert partial.result["collection"]["partial_success"] is True

    state["mode"] = "success"
    single = run_job(
        BackgroundJob(
            job_id="single-optical-job",
            task_type="ac_fit_ap_optical_refresh",
            params={**base_params, "refresh_scope": "single", "ap_name": "AP-01"},
        )
    )
    assert single.ok is True
    assert state["method"] == "single"

    state["mode"] = "failed"
    failed = run_job(job)
    assert failed.ok is False
    assert failed.error == "SSH连接失败"

    state["mode"] = "cancel"
    cancelled = run_job(job)
    assert cancelled.cancelled is True
    assert cancelled.error == "用户已取消更新"


def test_ac_page_optical_refreshes_submit_jobs_and_terminal_events_restore_state(monkeypatch: pytest.MonkeyPatch) -> None:
    submitted: list[tuple[str, dict[str, object], str]] = []
    running: list[bool] = []
    status = SimpleNamespace(text_value="", setText=lambda value: setattr(status, "text_value", value))
    device = _device()
    page = SimpleNamespace(
        feature_gate=SimpleNamespace(assert_enabled=lambda _feature: None),
        current_device=lambda: device,
        current_device_uuid=lambda: "ac-001",
        current_resource_page_rows=lambda: [{"ap_uuid": "ap-1", "ap_name": "AP-01", "ap_mac": "0011-2233-4455"}],
        site_name="demo",
        repository=SimpleNamespace(database=SimpleNamespace(path=Path("devices.db"))),
        optical_concurrency_combo=SimpleNamespace(currentData=lambda: 50),
        i18n=SimpleNamespace(t=lambda key, **kwargs: kwargs.get("ap", key)),
        _set_update_running=lambda value, _message="": running.append(value),
        _start_background_job=lambda task_type, params, title: submitted.append((task_type, params, title)) or f"job-{len(submitted)}",
        optical_job_id=None,
        _background_jobs={},
        _set_summary=lambda _summary: None,
        _apply_resource_rows=lambda _rows: None,
        _apply_optical_rows=lambda _rows: None,
        status_label=status,
    )

    AcManagementPage.refresh_fit_ap_optical(page)  # type: ignore[arg-type]
    assert page.optical_job_id == "job-1"
    assert submitted[0][0] == "ac_fit_ap_optical_refresh"
    assert submitted[0][1]["refresh_scope"] == "all"

    page.optical_job_id = None
    AcManagementPage.refresh_resource_ap_optical(page, 0)  # type: ignore[arg-type]
    assert page.optical_job_id == "job-2"
    assert submitted[1][1]["refresh_scope"] == "single"
    assert submitted[1][1]["ap_name"] == "AP-01"

    page._background_jobs = {
        "job-2": {"task_type": "ac_fit_ap_optical_refresh", "mode": "collect", "title": "FIT-AP光衰"}
    }
    AcManagementPage._background_finished(  # type: ignore[arg-type]
        page,
        {
            "job_id": "job-2",
            "result": {
                "ac_uuid": "ac-001",
                "summary": {},
                "resources": [],
                "optical_rows": [{"ap_name": "AP-01"}],
                "collection": {"optical_rows_updated": 1, "failed_aps": 0},
            },
        },
    )
    assert page.optical_job_id is None
    assert running[-1] is False
    assert "更新 1 条" in status.text_value

    warnings: list[str] = []
    monkeypatch.setattr("netconsole.ui.pages.ac_management_page.MessageBox.warning", lambda _parent, _title, message: warnings.append(message))
    page._background_jobs = {
        "failed-job": {"task_type": "ac_fit_ap_optical_refresh", "mode": "collect", "title": "FIT-AP光衰"}
    }
    page.optical_job_id = "failed-job"
    AcManagementPage._background_failed(page, {"job_id": "failed-job", "error": "连接失败"})  # type: ignore[arg-type]
    assert page.optical_job_id is None
    assert warnings == ["连接失败"]

    page._background_jobs = {
        "cancel-job": {"task_type": "ac_fit_ap_optical_refresh", "mode": "collect", "title": "FIT-AP光衰"}
    }
    page.optical_job_id = "cancel-job"
    AcManagementPage._background_cancelled(page, {"job_id": "cancel-job"})  # type: ignore[arg-type]
    assert page.optical_job_id is None
    assert status.text_value == "ac.update_cancelled"


def test_ac_optical_task_registration_and_static_boundaries() -> None:
    assert "ac_fit_ap_optical_refresh" in registered_task_types()
    page_source = (PROJECT_ROOT / "src" / "netconsole" / "ui" / "pages" / "ac_management_page.py").read_text(encoding="utf-8")
    domain_source = (PROJECT_ROOT / "src" / "netconsole" / "services" / "ac" / "ac_optical_service.py").read_text(encoding="utf-8")
    worker_source = (PROJECT_ROOT / "src" / "netconsole" / "background_worker.py").read_text(encoding="utf-8")

    assert "FitApOpticalCollectThread" not in page_source
    assert "collect_h3c_fit_ap_optical" not in page_source
    assert "netconsole.ui.pages" not in domain_source
    assert "netconsole.ui.pages" not in worker_source


def test_ac_optical_background_worker_stdout_is_utf8_jsonl(tmp_path: Path) -> None:
    database_path = tmp_path / "devices.db"
    Database(database_path).initialize()
    job_path = tmp_path / "ac-optical-load.json"
    job_path.write_text(
        json.dumps(
            BackgroundJob(
                job_id="ac-optical-load",
                task_type="ac_fit_ap_optical_refresh",
                params={
                    "mode": "load",
                    "ac_uuid": "ac-001",
                    "site_name": "demo",
                    "db_path": str(database_path),
                    "data_root": str(tmp_path),
                },
            ).to_dict(),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [sys.executable, "-m", "netconsole.background_worker", "--job", str(job_path)],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
    )

    events = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
    terminal = [event for event in events if event["type"] in {"finished", "error", "cancelled"}]
    assert completed.returncode == 0
    assert terminal == [events[-1]]
    assert events[-1]["type"] == "finished"
    assert events[-1]["result"]["ac_uuid"] == "ac-001"
