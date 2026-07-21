from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from web_parity_test_support import FakeExportProcessAdapter, FakeLocalProcessAdapter
from netconsole.application.rail_transit.web_application_service import RailTransitWebApplicationService, RailTransitWebError
from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.services.job_center.job_context import JobContext
from netconsole.services.job_center.job_registry import registered_task_types
from netconsole.services.job_center.task_application_service import TaskApplicationService
from netconsole.services.rail_transit import trackside_ap_business_query_service, trackside_ap_update_job, trackside_optical_collection
from netconsole.services.trackside_ap_export_service import TracksideApBusinessLoadResult
from netconsole.repositories.ac_repository import AcRepository, TRACKSIDE_AP_PLAN_MODE
from netconsole.repositories.device_repository import DeviceRepository


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
                "ap_uuid": "ap-uuid-a",
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
                "ap_uuid": "ap-uuid-b",
                "ap_mac": "0011-2233-4456",
                "ap_name": "AP-B",
                "ap_side_has_data": False,
            },
            {
                "site": "站点C",
                "device_name": "SW-C",
                "interface_name": "XGE1/0/3",
                "switch_optical_status": "no_module",
                "ap_side_has_data": False,
            },
        ],
        device_count=3,
        query_ms=3,
        build_ms=4,
        candidate_ap_interface_count=3,
        row_count=3,
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
    assert page.items[0].ap_uuid == "ap-uuid-b"
    assert page.items[0].optical_severity == "warning"
    assert page.optical_abnormal_count == 1
    assert page.identity_shadow == {"status": "matched"}


def test_trackside_query_counts_multiple_abnormal_interfaces_once_per_ap(monkeypatch, tmp_path: Path) -> None:
    snapshot = _snapshot()
    snapshot.rows.append(
        {
            "site": "站点B",
            "device_name": "SW-B",
            "interface_name": "XGE1/0/3",
            "switch_optical_status": "critical",
            "ap_uuid": "ap-uuid-b",
            "ap_mac": "0011-2233-4456",
            "ap_name": "AP-B",
            "ap_side_has_data": False,
        }
    )
    monkeypatch.setattr(trackside_ap_business_query_service, "Database", lambda _path: object())
    monkeypatch.setattr(trackside_ap_business_query_service, "DeviceRepository", lambda _database: object())
    monkeypatch.setattr(trackside_ap_business_query_service, "load_trackside_ap_business_snapshot", lambda *_args, **_kwargs: snapshot)

    page = trackside_ap_business_query_service.TracksideApBusinessQueryService(
        PathResolver(app_root=tmp_path, data_root=tmp_path)
    ).list_rows("demo", optical_anomaly_only=True)

    assert page.total == 2
    assert page.optical_abnormal_count == 1


def test_trackside_update_job_calls_existing_collection_service(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}
    progress: list[tuple[str, int, int, str]] = []
    monkeypatch.setattr(trackside_ap_update_job, "Database", lambda _path: object())
    monkeypatch.setattr(trackside_ap_update_job, "DeviceRepository", lambda _database: object())
    monkeypatch.setattr(trackside_ap_update_job, "load_trackside_ap_business_snapshot", lambda *_args, **_kwargs: _snapshot())

    class Result:
        session_id = "session-1"
        status = "SUCCESS"
        scope = "station"
        target_label = "站点A"
        success_count = 2
        failed_count = 0
        skipped_count = 0
        target_count = 2
        concurrency = 64
        requested_concurrency = 1000
        effective_concurrency = 2
        platform_concurrency_limit = 64
        fit_ap_effective_concurrency = 2
        fit_ap_round_summaries = [{"ac_device_uuid": "ac-1", "rounds": []}]
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
    assert result["status"] == "SUCCESS"
    assert result["terminal_state"] == "COMPLETED"
    assert result["success_count"] == 2
    assert result["requested_concurrency"] == 1000
    assert result["effective_concurrency"] == 2
    assert progress[-1] == ("trackside_ap_optical_update", 1, 2, "正在更新轨旁 AP 光衰")


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("SUCCESS", "COMPLETED"),
        ("PARTIAL_SUCCESS", "COMPLETED"),
        ("NO_TARGET", "COMPLETED"),
        ("FAILED", "FAILED"),
        ("CANCELLED", "CANCELLED"),
    ],
)
def test_trackside_update_job_maps_result_status_to_task_terminal_state(
    monkeypatch,
    tmp_path: Path,
    status: str,
    expected: str,
) -> None:
    monkeypatch.setattr(trackside_ap_update_job, "Database", lambda _path: object())
    monkeypatch.setattr(trackside_ap_update_job, "DeviceRepository", lambda _database: object())
    monkeypatch.setattr(trackside_ap_update_job, "load_trackside_ap_business_snapshot", lambda *_args, **_kwargs: _snapshot())
    monkeypatch.setattr(
        trackside_ap_update_job,
        "collect_trackside_optical",
        lambda *_args, **_kwargs: SimpleNamespace(
            session_id="session-1",
            status=status,
            scope="all",
            target_label="",
            success_count=0 if status == "FAILED" else 1,
            failed_count=2 if status == "FAILED" else 0,
            skipped_count=0,
            target_count=2,
            concurrency=64,
            requested_concurrency=64,
            effective_concurrency=2,
            platform_concurrency_limit=64,
            fit_ap_effective_concurrency=2,
            fit_ap_round_summaries=[],
            fit_ap_resource_count=1,
            fit_ap_optical_success_count=0,
            fit_ap_optical_failed_count=0,
            candidate_ap_interface_count=2,
            current_lldp_port_count=2,
            preserved_lldp_port_count=0,
        ),
    )
    context = JobContext(
        "task-1",
        "trackside_ap_optical_update",
        {"site_name": "demo", "db_path": str(tmp_path / "site.sqlite")},
        lambda *_args: None,
        lambda: False,
        PathResolver(app_root=tmp_path, data_root=tmp_path),
    )

    result = trackside_ap_update_job.run_trackside_ap_optical_update(context)

    assert result["status"] == status
    assert result["terminal_state"] == expected


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


def test_trackside_application_validates_update_scope_and_ap_identity(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    paths.ensure_site_dirs("demo")
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    ac_uuid_1 = "00000000-0000-4000-8000-000000000001"
    ac_uuid_2 = "00000000-0000-4000-8000-000000000002"
    device_repository = DeviceRepository(database)
    device_repository.create(
        Device(
            device_uuid=ac_uuid_1,
            name="AC-1",
            device_vendor="H3C",
            device_type="AC",
            primary_address="10.0.0.1",
        )
    )
    device_repository.create(
        Device(
            device_uuid=ac_uuid_2,
            name="AC-2",
            device_vendor="H3C",
            device_type="AC",
            primary_address="10.0.0.2",
        )
    )
    repository = AcRepository(database)
    repository.replace_fit_ap_resources(
        ac_uuid_1,
        [
            {
                "ac_device_uuid": ac_uuid_1,
                "ap_uuid": "ap-1",
                "ap_name": "AP-A",
                "ap_mac": "00:11:22:33:44:55",
                "ap_ip": "10.0.0.1",
                "site": "站点A",
            }
        ],
    )
    tasks = TaskApplicationService(paths=paths, site_name="demo")
    process = FakeLocalProcessAdapter(tasks)
    service = RailTransitWebApplicationService(
        paths,
        tasks,
        process_adapter=process,  # type: ignore[arg-type]
        export_adapter=FakeExportProcessAdapter(tasks),  # type: ignore[arg-type]
    )

    assert "trackside_ap_optical_update" in registered_task_types()

    all_update = service.start_trackside_ap_update("demo")
    all_job = process.jobs[all_update.task_id]
    process.complete(all_update.task_id, {"success_count": 1})
    station_update = service.start_trackside_ap_update("demo", station="站点A")
    station_job = process.jobs[station_update.task_id]
    process.complete(station_update.task_id, {"success_count": 1})
    ap_update = service.start_trackside_ap_update("demo", ap_uuid="ap-1", ap_mac="00:11:22:33:44:55", ap_name="AP-A")
    ap_job = process.jobs[ap_update.task_id]

    assert all_job.params["station"] == ""
    assert all_job.params["ap_uuid"] == ""
    assert all_job.params["resource_keys"] == [
        f"site:demo|ac:{ac_uuid_1}|fit_ap_optical",
        f"site:demo|ac:{ac_uuid_2}|fit_ap_optical",
    ]
    assert station_job.params["station"] == "站点A"
    assert station_job.params["ap_uuid"] == ""
    assert station_job.params["resource_keys"] == [
        f"site:demo|ac:{ac_uuid_1}|fit_ap_optical"
    ]
    assert ap_job.params["station"] == ""
    assert ap_job.params["ap_uuid"] == "ap-1"
    assert ap_job.params["ap_mac"] == "00:11:22:33:44:55"
    assert ap_job.params["ap_name"] == "AP-A"
    assert ap_job.params["resource_keys"] == [
        f"site:demo|ac:{ac_uuid_1}|fit_ap_optical"
    ]

    with pytest.raises(RailTransitWebError) as scope_conflict:
        service.start_trackside_ap_update("demo", station="站点A", ap_uuid="ap-1")
    assert scope_conflict.value.code == "TRACKSIDE_UPDATE_SCOPE_CONFLICT"

    with pytest.raises(RailTransitWebError) as ap_conflict:
        service.start_trackside_ap_update("demo", ap_uuid="ap-1", ap_mac="00:11:22:33:44:66", ap_name="AP-A")
    assert ap_conflict.value.code == "TRACKSIDE_UPDATE_AP_CONFLICT"


def test_trackside_collection_no_target_does_not_fake_success(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    paths.ensure_site_dirs("demo")
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    repository = DeviceRepository(database)

    result = trackside_ap_update_job.collect_trackside_optical(
        repository,
        "demo",
        paths,
        [],
        target_ap_uuid="ap-1",
        target_ap_mac="00:11:22:33:44:55",
        target_ap_name="AP-A",
    )

    assert result.status == "NO_TARGET"
    assert result.target_count == 0
    assert result.success_count == 0
    assert result.failed_count == 0


@pytest.mark.parametrize(
    ("success_count", "failed_count", "skipped_count", "target_count", "cancelled", "expected"),
    [
        (2, 0, 0, 2, False, "SUCCESS"),
        (1, 1, 0, 2, False, "PARTIAL_SUCCESS"),
        (0, 38, 0, 38, False, "FAILED"),
        (0, 0, 3, 3, False, "FAILED"),
        (0, 0, 0, 0, False, "NO_TARGET"),
        (1, 1, 0, 2, True, "CANCELLED"),
    ],
)
def test_trackside_collection_status_classification(
    success_count: int,
    failed_count: int,
    skipped_count: int,
    target_count: int,
    cancelled: bool,
    expected: str,
) -> None:
    assert (
        trackside_optical_collection._trackside_update_status(
            success_count=success_count,
            failed_count=failed_count,
            skipped_count=skipped_count,
            target_count=target_count,
            cancelled=cancelled,
        )
        == expected
    )


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
