from __future__ import annotations

from pathlib import Path

import pytest

from tests.support.job_process_test_support import FakeExportProcessAdapter, FakeLocalProcessAdapter

from netconsole.application.rail_transit import web_application_service
from netconsole.application.rail_transit.web_application_service import RailTransitWebApplicationService, RailTransitWebError
from netconsole.core.paths import PathResolver
from netconsole.models.api.ac_mesh_link import AcMeshMrPageDTO, AcMeshMrStatusDTO
from netconsole.models.api.vehicle_mr_online import VehicleMrEndStateDTO
from netconsole.models.device import Device
from netconsole.services.job_center.job_context import JobContext
from netconsole.services.job_center.task_application_service import TaskApplicationService
from netconsole.services.rail_transit import vehicle_mr_online_collection_job, vehicle_mr_online_query_service
from netconsole.services.vehicle_mr_online import (
    TRAIN_STATUS_DUAL_ONLINE,
    TRAIN_STATUS_OFFLINE,
    VehicleMrEndState,
    VehicleMrTrainMapping,
    VehicleMrTrainState,
)


def test_vehicle_mr_query_maps_persisted_ct_tc_state(monkeypatch, tmp_path: Path) -> None:
    class Store:
        def __init__(self, _paths: PathResolver, _site_id: str) -> None:
            pass

        def list_current_states(self) -> list[VehicleMrTrainState]:
            return [
                VehicleMrTrainState(
                    train_id="train-1",
                    train_no="01",
                    is_registered=True,
                    status=TRAIN_STATUS_DUAL_ONLINE,
                    current_station="站点A",
                    tc1=VehicleMrEndState(seen=True, station="站点A", ap_name="AP-CT", rssi=-55),
                    tc2=VehicleMrEndState(seen=True, station="站点A", ap_name="AP-TC", rssi=-60),
                ),
                VehicleMrTrainState(
                    train_id="train-2",
                    train_no="02",
                    is_registered=True,
                    status=TRAIN_STATUS_OFFLINE,
                ),
            ]

        def list_mappings(self) -> list[VehicleMrTrainMapping]:
            return [VehicleMrTrainMapping(train_id="train-1", train_no="01", tc1_peer_name="MR-CT", tc2_peer_name="MR-TC")]

        def list_events(self, train_id: str, limit: int) -> list[dict[str, object]]:
            return [{"train_id": train_id, "limit": limit, "ap_name": "AP-CT"}]

    monkeypatch.setattr(vehicle_mr_online_query_service, "VehicleMrOnlineStore", Store)

    class MeshQuery:
        def list_mrs(self, _site_id: str, *, page: int, page_size: int) -> AcMeshMrPageDTO:
            assert page == 1
            assert page_size == 200
            return AcMeshMrPageDTO(
                items=[
                    AcMeshMrStatusDTO(
                        mr_id="mr-01-ct", train_no="01", car_end="CT", mr_name="列车01-MR-CT",
                        online_status="online", peer_ap_name="AP-CT", peer_ap_mac="aa:bb:cc:dd:ee:01",
                        mesh_radio="Radio 1", rssi=-55, station="站点A", section="区间A",
                        mileage="K1+000", line_side="上行", ap_rx_power="-10 dBm",
                        switch_rx_power="-12 dBm", last_seen_at="2026-07-19 12:00:00",
                        match_method="mac_exact", data_status="fresh",
                    ),
                    AcMeshMrStatusDTO(
                        mr_id="mr-01-tc", train_no="01", car_end="CW", mr_name="列车01-MR-TC",
                        online_status="online", peer_ap_name="AP-TC", peer_ap_mac="aa:bb:cc:dd:ee:02",
                        mesh_radio="Radio 2", rssi=-60, station="站点A", section="区间A",
                        mileage="K1+010", line_side="上行", last_seen_at="2026-07-19 12:00:01",
                        match_method="unmatched", data_status="fresh",
                    ),
                    AcMeshMrStatusDTO(mr_id="mr-02-ct", train_no="02", car_end="CT", online_status="offline", data_status="fresh"),
                    AcMeshMrStatusDTO(mr_id="mr-02-tc", train_no="02", car_end="CW", online_status="offline", data_status="fresh"),
                ],
                total=4,
                page=1,
                page_size=200,
            )

    service = vehicle_mr_online_query_service.VehicleMrOnlineQueryService(
        PathResolver(app_root=tmp_path, data_root=tmp_path),
        mesh_query=MeshQuery(),  # type: ignore[arg-type]
    )

    page = service.list_trains("demo")

    assert page.mr_total == 4
    assert page.both_online_count == 1
    assert page.both_offline_count == 1
    assert page.active_mesh_link_count == 2
    assert page.unmatched_ap_count == 1
    assert page.items[0].overall_status == "BOTH_ONLINE"
    assert page.items[0].ct.current_ap_name == "AP-CT"
    assert page.items[0].ct.current_ap_mac == "aa:bb:cc:dd:ee:01"
    assert page.items[0].ct.match_status == "MAC_MATCHED"
    assert page.items[0].ct.outdoor_optical_power == "-10 dBm"
    assert page.items[0].tc.current_ap_name == "AP-TC"
    assert page.items[0].tc.match_status == "UNMATCHED"
    assert service.get_train("demo", "train-1") == page.items[0]
    assert service.list_trains("demo", unmatched_only=True).items == [page.items[0]]
    assert service.list_mappings("demo")[0].tc2_peer_name == "MR-TC"
    assert service.list_events("demo", "train-1").items[0]["ap_name"] == "AP-CT"


@pytest.mark.parametrize(
    ("ct_status", "tc_status", "expected"),
    [
        ("ONLINE", "OFFLINE", "ONE_SIDE_ONLINE"),
        ("STALE", "OFFLINE", "STALE"),
        ("UNKNOWN", "UNKNOWN", "UNKNOWN"),
    ],
)
def test_vehicle_mr_overall_status_is_decided_by_query_service(
    ct_status: str,
    tc_status: str,
    expected: str,
) -> None:
    ct = VehicleMrEndStateDTO(endpoint="CT", online_status=ct_status)  # type: ignore[arg-type]
    tc = VehicleMrEndStateDTO(endpoint="TC", online_status=tc_status)  # type: ignore[arg-type]

    assert vehicle_mr_online_query_service.VehicleMrOnlineQueryService._overall_status(ct, tc) == expected


def test_vehicle_mr_application_starts_registered_refresh_and_mapping_jobs(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    paths.ensure_site_dirs("demo")
    tasks = TaskApplicationService(paths=paths, site_name="demo")
    process = FakeLocalProcessAdapter(tasks)
    service = RailTransitWebApplicationService(
        paths,
        tasks,
        process_adapter=process,  # type: ignore[arg-type]
        export_adapter=FakeExportProcessAdapter(tasks),  # type: ignore[arg-type]
    )

    refresh = service.start_vehicle_mr_online_refresh("demo")
    mapping_refresh = service.start_vehicle_mr_ap_mapping_refresh("demo", train_id="train-1")
    mapping_save = service.save_vehicle_mr_mappings(
        "demo",
        [{"train_id": "train-1", "train_no": "01"}],
        explicit_confirmation=True,
    )

    assert process.jobs[refresh.task_id].task_type == "vehicle_mr_online_refresh_all"
    assert process.jobs[mapping_refresh.task_id].task_type == "vehicle_mr_ap_mapping_refresh"
    assert process.jobs[mapping_refresh.task_id].params["train_id"] == "train-1"
    assert process.jobs[mapping_save.task_id].task_type == "vehicle_mr_mapping_save"
    assert process.jobs[mapping_save.task_id].params["mappings"] == [{"train_id": "train-1", "train_no": "01"}]


def test_vehicle_mr_collection_domain_job_reuses_existing_collector(monkeypatch, tmp_path: Path) -> None:
    ac = Device(
        id=7,
        name="AC-1",
        device_type="AC",
        primary_address="10.0.0.1",
        ssh_enabled=1,
        ssh_username="admin",
        ssh_password="secret",
    )
    captured: dict[str, object] = {}

    class Repository:
        def __init__(self, _database) -> None:
            pass

        def get(self, device_id: int) -> Device:
            assert device_id == 7
            return ac

        def list(self) -> list[Device]:
            return [ac]

    class Store:
        def __init__(self, _paths, _site_id) -> None:
            pass

        def list_mappings(self) -> list[object]:
            return []

    class Collector:
        session_id = "session-1"
        sample_index = 3

        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

        def run_forever(self, callback, should_cancel) -> None:
            assert should_cancel() is False
            callback(type("Snapshot", (), {"status": "采集中", "ac_time": "12:00:00", "error_message": ""})())

    monkeypatch.setattr(vehicle_mr_online_collection_job, "Database", lambda _path: object())
    monkeypatch.setattr(vehicle_mr_online_collection_job, "DeviceRepository", Repository)
    monkeypatch.setattr(vehicle_mr_online_collection_job, "VehicleMrOnlineStore", Store)
    monkeypatch.setattr(vehicle_mr_online_collection_job, "VehicleMrOnlineCollector", Collector)
    monkeypatch.setattr(vehicle_mr_online_collection_job, "load_group_names", lambda *_args: {})
    monkeypatch.setattr(vehicle_mr_online_collection_job, "build_registered_trains", lambda *_args: {})
    monkeypatch.setattr(vehicle_mr_online_collection_job, "build_mapping_trains", lambda *_args: {})
    monkeypatch.setattr(vehicle_mr_online_collection_job, "build_mapping_lookup", lambda *_args: {})
    monkeypatch.setattr(vehicle_mr_online_collection_job, "load_trackside_ap_lookup", lambda *_args: {})
    monkeypatch.setattr(vehicle_mr_online_collection_job, "connection_targets", lambda _device: [])
    progress = []
    context = JobContext(
        "task-1",
        "vehicle_mr_online_collection_start",
        {"site_name": "demo", "ac_device_id": 7, "interval_seconds": 5},
        lambda stage, current, total, message: progress.append((stage, message)),
        lambda: False,
        PathResolver(app_root=tmp_path, data_root=tmp_path),
    )

    result = vehicle_mr_online_collection_job.run_vehicle_mr_online_collection(context)

    assert result == {"session_id": "session-1", "sample_count": 3, "status": "已停止", "ac_device_id": 7, "interval_seconds": 5}
    assert captured["ac"] is ac
    assert captured["connection_config"].password == "secret"
    assert "secret" not in str(result)
    assert progress[-1] == ("vehicle_mr_online_collection", "采集中；已采集 3 次；AC 时间 12:00:00")


def test_vehicle_mr_collection_start_and_history_export_report_shared_blockers(monkeypatch, tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    paths.ensure_site_dirs("demo")
    tasks = TaskApplicationService(paths=paths, site_name="demo")
    process = FakeLocalProcessAdapter(tasks)
    service = RailTransitWebApplicationService(
        paths,
        tasks,
        process_adapter=process,  # type: ignore[arg-type]
        export_adapter=FakeExportProcessAdapter(tasks),  # type: ignore[arg-type]
    )

    monkeypatch.setattr(web_application_service, "registered_task_types", lambda: ())
    with pytest.raises(RailTransitWebError) as collection_blocked:
        service.start_vehicle_mr_online_collection("demo", ac_device_id=7, interval_seconds=10)
    assert collection_blocked.value.code == "BLOCKED_ON_TASK_WINDOW"

    monkeypatch.setattr(web_application_service, "registered_task_types", lambda: ("vehicle_mr_online_collection_start",))
    started = service.start_vehicle_mr_online_collection("demo", ac_device_id=7, interval_seconds=10)
    assert process.jobs[started.task_id].task_type == "vehicle_mr_online_collection_start"
    assert process.jobs[started.task_id].params["ac_device_id"] == 7
    with pytest.raises(RailTransitWebError) as history_blocked:
        service.start_vehicle_mr_history_export("demo", train_id="train-1", filters={})
    assert history_blocked.value.code == "BLOCKED_ON_TASK_WINDOW"


def test_vehicle_mr_mapping_preview_confirmation_and_template_blocker(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    paths.ensure_site_dirs("demo")
    tasks = TaskApplicationService(paths=paths, site_name="demo")
    process = FakeLocalProcessAdapter(tasks)
    service = RailTransitWebApplicationService(
        paths,
        tasks,
        process_adapter=process,  # type: ignore[arg-type]
        export_adapter=FakeExportProcessAdapter(tasks),  # type: ignore[arg-type]
    )
    content = (
        "车次,TC1,TC2,在线策略,备注\r\n"
        "1车,0101,0106,双端在线,首行\r\n"
        "1车,0101A,0106A,单端在线-尾端在线,覆盖行\r\n"
    ).encode("utf-8-sig")

    preview = service.preview_vehicle_mr_mappings(
        "demo",
        file_name="mapping.csv",
        content=content,
        duplicate_strategy="replace",
    )

    assert preview.can_apply is True
    assert preview.valid_count == 1
    assert preview.duplicate_count == 1
    assert preview.result_rows[0].tc1_peer_name == "0101A"
    with pytest.raises(RailTransitWebError) as confirmation:
        service.save_vehicle_mr_mappings("demo", [preview.result_rows[0].model_dump()])
    assert confirmation.value.code == "CONFIRMATION_REQUIRED"
    saved = service.save_vehicle_mr_mappings(
        "demo",
        [preview.result_rows[0].model_dump()],
        explicit_confirmation=True,
        audit={"source": "test"},
    )
    assert process.jobs[saved.task_id].params["audit"] == {"source": "test"}
    with pytest.raises(RailTransitWebError) as template_blocked:
        service.start_vehicle_mr_mapping_template_export("demo")
    assert template_blocked.value.code == "BLOCKED_ON_TASK_WINDOW"
