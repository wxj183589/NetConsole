from __future__ import annotations

from pathlib import Path

from web_parity_test_support import FakeExportProcessAdapter, FakeLocalProcessAdapter

from netconsole.application.rail_transit.web_application_service import RailTransitWebApplicationService
from netconsole.core.paths import PathResolver
from netconsole.services.job_center.task_application_service import TaskApplicationService
from netconsole.services.rail_transit import vehicle_mr_online_query_service
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
                    train_id="unregistered-1",
                    train_no="",
                    is_registered=False,
                    status=TRAIN_STATUS_OFFLINE,
                ),
            ]

        def list_mappings(self) -> list[VehicleMrTrainMapping]:
            return [VehicleMrTrainMapping(train_id="train-1", train_no="01", tc1_peer_name="MR-CT", tc2_peer_name="MR-TC")]

        def list_events(self, train_id: str, limit: int) -> list[dict[str, object]]:
            return [{"train_id": train_id, "limit": limit, "ap_name": "AP-CT"}]

    monkeypatch.setattr(vehicle_mr_online_query_service, "VehicleMrOnlineStore", Store)
    service = vehicle_mr_online_query_service.VehicleMrOnlineQueryService(
        PathResolver(app_root=tmp_path, data_root=tmp_path)
    )

    page = service.list_trains("demo")

    assert page.online_count == 1
    assert page.offline_count == 1
    assert page.unregistered_count == 1
    assert page.items[0].tc1.ap_name == "AP-CT"
    assert page.items[0].tc1.rssi == -55
    assert page.items[0].tc2.ap_name == "AP-TC"
    assert service.list_mappings("demo")[0].tc2_peer_name == "MR-TC"
    assert service.list_events("demo", "train-1").items[0]["ap_name"] == "AP-CT"


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
    mapping_save = service.save_vehicle_mr_mappings("demo", [{"train_id": "train-1", "train_no": "01"}])

    assert process.jobs[refresh.task_id].task_type == "vehicle_mr_online_refresh_all"
    assert process.jobs[mapping_refresh.task_id].task_type == "vehicle_mr_ap_mapping_refresh"
    assert process.jobs[mapping_refresh.task_id].params["train_id"] == "train-1"
    assert process.jobs[mapping_save.task_id].task_type == "vehicle_mr_mapping_save"
    assert process.jobs[mapping_save.task_id].params["mappings"] == [{"train_id": "train-1", "train_no": "01"}]
