from __future__ import annotations

from pathlib import Path

import pytest

from web_parity_test_support import FakeExportProcessAdapter, FakeLocalProcessAdapter
from netconsole.application.rail_transit.web_application_service import RailTransitWebApplicationService, RailTransitWebError
from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.services.job_center.job_context import JobContext
from netconsole.services.job_center.task_application_service import TaskApplicationService
from netconsole.services.rail_transit import trackside_ap_business_query_service, trackside_ap_update_job
from netconsole.services.trackside_ap_export_service import TracksideApBusinessLoadResult
from netconsole.repositories.ac_repository import AcRepository, TRACKSIDE_AP_PLAN_MODE


def _snapshot() -> TracksideApBusinessLoadResult:
    return TracksideApBusinessLoadResult(
        generation=0,
        site_name="demo",
        rows=[
            {
                "site": "站点A",
                "device_name": "SW-A",
                "interface_name": "XGE1/0/1",
                "link_status": "UP",
                "switch_rx_power": -10.5,
                "switch_optical_status": "normal",
                "ap_mac": "0011-2233-4455",
                "ap_name": "AP-A",
                "ap_rx_power": -11.2,
                "ap_optical_status": "normal",
                "ap_side_has_data": True,
            },
            {
                "site": "站点B",
                "device_name": "SW-B",
                "interface_name": "XGE1/0/2",
                "switch_optical_status": "warning",
                "ap_side_has_data": False,
            },
        ],
        device_count=2,
        query_ms=3,
        build_ms=4,
        candidate_ap_interface_count=2,
        row_count=2,
        fit_ap_resource_count=1,
        identity_shadow={"status": "matched"},
    )


def test_trackside_query_reuses_snapshot_filter_and_optical_status(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(trackside_ap_business_query_service, "Database", lambda _path: object())
    monkeypatch.setattr(trackside_ap_business_query_service, "DeviceRepository", lambda _database: object())
    monkeypatch.setattr(trackside_ap_business_query_service, "load_trackside_ap_business_snapshot", lambda *_args, **_kwargs: _snapshot())
    service = trackside_ap_business_query_service.TracksideApBusinessQueryService(
        PathResolver(app_root=tmp_path, data_root=tmp_path)
    )

    page = service.list_rows("demo", optical_anomaly_only=True)

    assert page.total == 1
    assert page.items[0].device_name == "SW-B"
    assert page.items[0].optical_severity == "warning"
    assert page.optical_abnormal_count == 1
    assert page.identity_shadow == {"status": "matched"}


def test_trackside_update_job_calls_existing_collection_service(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}
    progress: list[tuple[str, int, int, str]] = []
    monkeypatch.setattr(trackside_ap_update_job, "Database", lambda _path: object())
    monkeypatch.setattr(trackside_ap_update_job, "DeviceRepository", lambda _database: object())
    monkeypatch.setattr(trackside_ap_update_job, "load_trackside_ap_business_snapshot", lambda *_args, **_kwargs: _snapshot())

    class Result:
        session_id = "session-1"
        status = "DONE"
        scope = "station"
        target_label = "站点A"
        success_count = 2
        failed_count = 0
        skipped_count = 0
        target_count = 2
        fit_ap_resource_count = 1
        fit_ap_optical_success_count = 1
        fit_ap_optical_failed_count = 0
        candidate_ap_interface_count = 2
        current_lldp_port_count = 2
        preserved_lldp_port_count = 0

    def collect(repository, site_id, paths, rows, **kwargs):
        captured.update(repository=repository, site_id=site_id, paths=paths, rows=rows, **kwargs)
        kwargs["progress_callback"](1, 2)
        return Result()

    monkeypatch.setattr(trackside_ap_update_job, "collect_trackside_optical", collect)
    context = JobContext(
        "task-1",
        "trackside_ap_optical_update",
        {"site_name": "demo", "db_path": str(tmp_path / "site.sqlite"), "station": "站点A"},
        lambda stage, current, total, message: progress.append((stage, current, total, message)),
        lambda: False,
        PathResolver(app_root=tmp_path, data_root=tmp_path),
    )

    result = trackside_ap_update_job.run_trackside_ap_optical_update(context)

    assert captured["site_id"] == "demo"
    assert captured["target_station"] == "站点A"
    assert captured["rows"] == _snapshot().rows
    assert result["session_id"] == "session-1"
    assert result["success_count"] == 2
    assert progress[-1] == ("trackside_ap_optical_update", 1, 2, "正在更新轨旁 AP 光衰")


def test_trackside_application_starts_scoped_update(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    paths.ensure_site_dirs("demo")
    tasks = TaskApplicationService(paths=paths, site_name="demo")
    process = FakeLocalProcessAdapter(tasks)
    export = FakeExportProcessAdapter(tasks)
    service = RailTransitWebApplicationService(
        paths,
        tasks,
        process_adapter=process,  # type: ignore[arg-type]
        export_adapter=export,  # type: ignore[arg-type]
    )

    update = service.start_trackside_ap_update("demo", station="站点A")
    update_job = process.jobs[update.task_id]
    assert update_job.task_type == "trackside_ap_optical_update"
    assert update_job.params["station"] == "站点A"


def test_trackside_plan_preview_save_and_task_window_blocker(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    paths.ensure_site_dirs("demo")
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    repository = AcRepository(database)
    repository.replace_trackside_ap_plan_rows(
        TRACKSIDE_AP_PLAN_MODE,
        [{"station_name": "站点A", "ap_count": 20, "ap_start_address": "10.1.1.1", "mask_length": 24, "ap_gateway": "10.1.1.254", "ap_management_vlans": "921", "remark": "原值"}],
    )
    tasks = TaskApplicationService(paths=paths, site_name="demo")
    process = FakeLocalProcessAdapter(tasks)
    service = RailTransitWebApplicationService(
        paths,
        tasks,
        process_adapter=process,  # type: ignore[arg-type]
        export_adapter=FakeExportProcessAdapter(tasks),  # type: ignore[arg-type]
    )
    content = (
        "车站名称,AP数量,AP起始地址,掩码,AP网关,AP管理VLAN,备注\r\n"
        "站点A,30,10.1.1.1,255.255.255.0,10.1.1.254,921,覆盖值\r\n"
        "站点B,10,10.2.1.X,24,10.2.1.254,922,新增值\r\n"
    ).encode("utf-8-sig")

    preview = service.preview_trackside_ap_plan(
        "demo", file_name="trackside.csv", content=content, duplicate_strategy="replace"
    )
    assert preview.can_apply is True
    assert preview.duplicate_count == 1
    assert preview.valid_count == 1
    assert {row.station_name for row in preview.result_rows} == {"站点A", "站点B"}
    assert next(row for row in preview.result_rows if row.station_name == "站点A").ap_count == 30

    started = service.start_trackside_ap_plan_save(
        "demo",
        rows=[row.model_dump() for row in preview.result_rows],
        explicit_confirmation=True,
        audit={"source": "test"},
    )
    assert process.jobs[started.task_id].task_type == "trackside_ap_plan_save"
    assert process.jobs[started.task_id].params["audit"] == {"source": "test"}
    with pytest.raises(RailTransitWebError) as blocked:
        service.start_trackside_ap_plan_export("demo", template=False)
    assert blocked.value.code == "BLOCKED_ON_TASK_WINDOW"
