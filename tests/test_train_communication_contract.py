from __future__ import annotations

import csv

import io

from dataclasses import asdict

from pathlib import Path

from types import SimpleNamespace

import pytest

from fastapi.testclient import TestClient

from tests.support.job_process_test_support import FakeExportProcessAdapter, FakeLocalProcessAdapter

from netconsole.application.rail_transit.web_application_service import (
    RailTransitWebApplicationService,
    RailTransitWebError,
)

from netconsole.backend.api.main import create_app

from netconsole.core.database import Database

from netconsole.core.paths import PathResolver

from netconsole.core.runtime_mode import RuntimeMode

from netconsole.models.api.rail_transit_web import CarNetworkPointRowDTO

from netconsole.services.job_center.task_application_service import (
    TaskApplicationService,
)

from netconsole.services.online_mr.query_service import OnlineMrQueryService

from netconsole.services.rail_transit.car_network_diagnostic import (
    POINT_TABLE_FIELDS,
    CarNetworkNode,
    CarNetworkPointTableStore,
)

from netconsole.repositories.ac_repository import AcRepository

RAIL_FEATURE_IDS = (
    "module.train_communication",
    "capability.online_mr.report_export",
    "capability.online_mr.parse",
    "capability.online_mr.open_location",
    "capability.online_mr.session_delete",
    "capability.desktop_native_integration",
    "online_mr.collection_notes",
    "capability.mesh.import",
    "capability.mesh.report_export",
    "capability.mesh.source_open_location",
    "capability.train_communication.diagnostic_execute",
    "capability.rail_transit.task_control",
    "capability.train_communication.point_table_write",
    "capability.train_communication.point_table_export",
    "module.trackside_ap",
    "capability.trackside_ap.update",
)

class _NoopAsyncService:
    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

def _service(paths: PathResolver, mesh_query=None):
    paths.ensure_site_dirs("demo")
    tasks = TaskApplicationService(paths=paths, site_name="demo")
    normal = FakeLocalProcessAdapter(tasks)
    export = FakeExportProcessAdapter(tasks)
    service = RailTransitWebApplicationService(
        paths,
        tasks,
        process_adapter=normal,  # type: ignore[arg-type]
        export_adapter=export,  # type: ignore[arg-type]
        query_service=OnlineMrQueryService(paths),
        mesh_query_service=mesh_query,
    )
    return service, normal, export, tasks

def _enable_features(app) -> None:
    for feature_id in RAIL_FEATURE_IDS:
        app.state.feature_gate.features[feature_id] = {
            "visible": True,
            "enabled": True,
            "client_package": True,
            "internal_only": False,
        }

def _point_table_csv(rows: list[dict[str, object]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=list(POINT_TABLE_FIELDS))
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")

def _save_complete_point_table(paths: PathResolver, train_id: str) -> None:
    CarNetworkPointTableStore(paths, "demo").save(
        [
            CarNetworkNode(
                train_id,
                node_name,
                "SERVER" if node_name.endswith("SRV") else "SW" if node_name.endswith("SW") else "MR",
                train_no=train_id,
                display_name=f"{train_id}车",
                device_id=node_name,
                primary_address=f"10.0.0.{index}",
            )
            for index, node_name in enumerate(
                ("TC1-MR", "TC1-SW", "TC1-SRV", "TC2-MR", "TC2-SW", "TC2-SRV"),
                1,
            )
        ]
    )

def _train_online_snapshot(status: str):
    endpoint_status = "ONLINE" if status == "BOTH_ONLINE" else "OFFLINE"
    data_status = "STALE" if status == "STALE" else "FRESH"

    def endpoint(name: str) -> SimpleNamespace:
        return SimpleNamespace(
            online_status=endpoint_status,
            data_status=data_status,
            mr_id=f"mr-{name}",
            mr_name=f"列车01-MR-{name}",
        )

    return SimpleNamespace(
        train_id="train:01",
        train_no="01",
        train_name="01车",
        overall_status=status,
        updated_at="2026-07-22T10:00:00+00:00",
        ct=endpoint("CT"),
        tc=endpoint("CW"),
    )


@pytest.mark.parametrize("online_status", [None, "STALE", "BOTH_OFFLINE", "BOTH_ONLINE"])
def test_car_network_diagnostic_start_treats_online_state_as_optional_context(
    tmp_path: Path,
    online_status: str | None,
) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    service, normal, _export, _tasks = _service(paths)
    _save_complete_point_table(paths, "01")
    snapshot = _train_online_snapshot(online_status) if online_status else None
    service.vehicle_mr_online_query_service = SimpleNamespace(
        get_train_by_identity=lambda _site_id, _train_id: snapshot
    )

    started = service.start_car_network_diagnostic("demo", train_id="01")
    params = normal.jobs[started.task_id].params

    assert started.action == "car_network_diagnostic"
    assert params["train_id"] == "train:01"
    assert params["online_status"] == (online_status or "UNKNOWN")
    assert params["online_snapshot_time"] == (
        "2026-07-22T10:00:00+00:00" if snapshot else ""
    )
    assert params["ct_mr_id"] == ("mr-CT" if snapshot else "")


def test_car_network_diagnostic_start_still_requires_valid_point_table(
    tmp_path: Path,
) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    service, _normal, _export, _tasks = _service(paths)
    service.vehicle_mr_online_query_service = SimpleNamespace(
        get_train_by_identity=lambda _site_id, _train_id: None
    )

    with pytest.raises(RailTransitWebError) as missing:
        service.start_car_network_diagnostic("demo", train_id="01")
    assert missing.value.code == "TRAIN_COMMUNICATION_POINT_TABLE_MISSING"

    CarNetworkPointTableStore(paths, "demo").save(
        [
            CarNetworkNode(
                "01",
                "TC1-MR",
                "MR",
                train_no="01",
                display_name="01车",
                primary_address="10.0.0.1",
            )
        ]
    )
    with pytest.raises(RailTransitWebError) as invalid:
        service.start_car_network_diagnostic("demo", train_id="01")
    assert invalid.value.code == "TRAIN_COMMUNICATION_POINT_TABLE_INVALID"


def test_point_table_preview_transform_save_and_task_window_blocker(
    tmp_path: Path,
) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    service, normal, _export, _tasks = _service(paths)
    existing = CarNetworkNode(
        train_id="LC01", train_no="1", node_name="TC1-MR", node_type="MR"
    )
    CarNetworkPointTableStore(paths, "demo").save([existing])

    preview = service.preview_car_network_point_table(
        "demo",
        file_name="point-table.csv",
        content=_point_table_csv(
            [
                {**existing.__dict__, "remark": "覆盖值"},
                {
                    **existing.__dict__,
                    "node_name": "TC2-MR",
                    "tc": "TC2",
                    "remark": "新增值",
                },
            ]
        ),
        duplicate_strategy="replace",
    )
    assert preview.can_apply is True
    assert preview.duplicate_count == 1
    assert preview.valid_count == 1
    assert {row.node_name for row in preview.result_rows} == {"TC1-MR", "TC2-MR"}

    transformed = service.transform_car_network_point_table(
        "demo",
        operation="apply_global",
        rows=[row.model_dump() for row in preview.result_rows],
        global_config={},
    )
    with pytest.raises(RailTransitWebError) as revision_conflict:
        service.start_car_network_point_table_save(
            "demo",
            rows=[row.model_dump() for row in transformed.rows],
            global_config=transformed.global_config,
            overwrite_custom=False,
            explicit_confirmation=True,
            audit={"source": "test"},
            revision="stale-revision",
        )
    assert revision_conflict.value.code == "TRAIN_COMMUNICATION_REVISION_CONFLICT"

    started = service.start_car_network_point_table_save(
        "demo",
        rows=[row.model_dump() for row in transformed.rows],
        global_config=transformed.global_config,
        overwrite_custom=False,
        explicit_confirmation=True,
        audit={"source": "test"},
    )
    assert normal.jobs[started.task_id].task_type == "car_network_save_point_table"
    assert normal.jobs[started.task_id].params["audit"] == {"source": "test"}
    with pytest.raises(RailTransitWebError) as blocked:
        service.start_car_network_point_table_export("demo", file_format="xlsx")
    assert blocked.value.code == "BLOCKED_ON_TASK_WINDOW"


def test_point_table_generate_task_returns_controlled_preview_nodes_only(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    service, normal, _export, _tasks = _service(paths)
    names = ("TC1-MR", "TC1-SW", "TC1-SRV", "TC2-MR", "TC2-SW", "TC2-SRV")
    generated_nodes = [
        asdict(
            CarNetworkNode(
                train_id="train:01",
                train_no="01",
                display_name="列车01",
                node_name=name,
                node_type="MR" if name.endswith("MR") else "3SW" if name.endswith("SW") else "SRV",
            )
        )
        for name in names
    ]
    started = service.start_car_network_point_table_generate(
        "demo",
        rows=[],
        global_config={},
        target_train={"canonical_train_id": "train:01", "display_name": "列车01"},
    )

    assert normal.jobs[started.task_id].params["save_result"] is False
    normal.complete(
        started.task_id,
        {
            "count": 6,
            "nodes": generated_nodes,
            "generated_nodes_count": 6,
            "target_train": "train:01",
            "target_train_display": "列车01",
            "preview_status": "PENDING_SAVE",
            "preview_message": "已生成点表预览，等待用户保存",
        },
    )
    completed = service.get_task("demo", started.task_id)

    assert completed.result_summary["count"] == 6
    assert completed.result_summary["nodes_count"] == 6
    assert completed.result_summary["generated_nodes_count"] == 6
    assert completed.result_summary["nodes_available"] is True
    assert len(completed.result_summary["nodes"]) == 6
    assert all(
        set(row) == set(CarNetworkPointRowDTO.model_fields)
        for row in completed.result_summary["nodes"]
    )
    normalized = service._result_summary(
        "car_network_generate_point_table",
        {"count": 6, "nodes": [{**generated_nodes[0], "unexpected_field": "must-not-leak"}]},
    )
    assert "unexpected_field" not in str(normalized)

    invalid_started = service.start_car_network_point_table_generate(
        "demo", rows=[], global_config={}, target_train={"canonical_train_id": "train:01"}
    )
    normal.complete(invalid_started.task_id, {"count": 6, "nodes": "invalid"})
    invalid_completed = service.get_task("demo", invalid_started.task_id)
    assert invalid_completed.result_summary["nodes_available"] is False
    assert "nodes" not in invalid_completed.result_summary

    _save_complete_point_table(paths, "01")
    diagnostic = service.start_car_network_diagnostic("demo", train_id="train:01")
    normal.complete(diagnostic.task_id, {"nodes": generated_nodes, "count": 6})
    other_task = service.get_car_network_diagnostic("demo", diagnostic.task_id)
    assert "nodes" not in other_task.result_summary


def test_point_table_and_trackside_plan_routes_reach_application_tasks(
    tmp_path: Path,
) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    ac_repository = AcRepository(database)
    ac_repository.replace_fit_ap_resources(
        "ac-1",
        [
            {
                "ac_device_uuid": "ac-1",
                "ap_uuid": "ap-1",
                "ap_name": "AP-A",
                "ap_mac": "0011-2233-4455",
                "ap_ip": "10.0.0.1",
                "site": "站点A",
            }
        ],
    )
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.app_config_path.write_text('{"current_site":"demo"}', encoding="utf-8")
    app = create_app(
        RuntimeMode.SERVER,
        paths=paths,
        agent_service=_NoopAsyncService(),  # type: ignore[arg-type]
        traffic_service=_NoopAsyncService(),  # type: ignore[arg-type]
        frontend_dist=tmp_path / "missing",
    )
    normal = FakeLocalProcessAdapter(app.state.task_service)
    app.state.rail_transit_web_application_service = RailTransitWebApplicationService(
        paths,
        app.state.task_service,
        process_adapter=normal,  # type: ignore[arg-type]
        export_adapter=FakeExportProcessAdapter(app.state.task_service),  # type: ignore[arg-type]
    )
    _enable_features(app)
    for feature_id in (
        "capability.trackside_ap.plan",
        "capability.trackside_ap.plan_write",
        "capability.trackside_ap.plan_export",
    ):
        app.state.feature_gate.features[feature_id] = {
            "visible": True,
            "enabled": True,
            "client_package": True,
            "internal_only": False,
        }

    with TestClient(app) as client:
        point_table = client.get("/api/rail-transit/train-communication/point-table")
        point_save = client.post(
            "/api/rail-transit/train-communication/point-table/save",
            json={"rows": [], "global_config": {}, "explicit_confirmation": True},
        )
        stale_point_save = client.post(
            "/api/rail-transit/train-communication/point-table/save",
            json={"rows": [], "global_config": {}, "explicit_confirmation": True, "revision": "stale-revision"},
        )
        plan = client.get("/api/rail-transit/trackside-ap-business/plan")
        plan_draft = {
            key: plan.json()[key]
            for key in ("planning", "groups", "assignments", "allocations")
        }
        auto_group_preview = client.post(
            "/api/rail-transit/trackside-ap-business/plan/auto-group-preview",
            json={
                "planning_mode": "line_single",
                "auto_group_station_count": 1,
                "current": plan_draft,
            },
        )
        adjustment_preview = client.post(
            "/api/rail-transit/trackside-ap-business/plan/adjustment-preview",
            json={"proposed": plan_draft},
        )
        point_table_preview = client.post(
            "/api/rail-transit/trackside-ap-business/plan/point-table-preview",
            json={"proposed": plan_draft},
        )
        plan_save = client.post(
            "/api/rail-transit/trackside-ap-business/plan/save",
            json={"rows": [], "explicit_confirmation": True},
        )
        update_all = client.post("/api/rail-transit/trackside-ap-business/update", json={})
        update_all_job = normal.jobs[update_all.json()["task_id"]]
        normal.complete(update_all.json()["task_id"], {"success_count": 1})
        update_station = client.post(
            "/api/rail-transit/trackside-ap-business/update",
            json={"station": "站点A"},
        )
        update_station_job = normal.jobs[update_station.json()["task_id"]]
        normal.complete(update_station.json()["task_id"], {"success_count": 1})
        update_ap = client.post(
            "/api/rail-transit/trackside-ap-business/update",
            json={"ap_uuid": "ap-1", "ap_mac": "0011-2233-4455", "ap_name": "AP-A"},
        )
        update_ap_job = normal.jobs[update_ap.json()["task_id"]]
        scope_conflict = client.post(
            "/api/rail-transit/trackside-ap-business/update",
            json={"station": "站点A", "ap_uuid": "ap-1"},
        )
        plan_export = client.post(
            "/api/rail-transit/trackside-ap-business/plan/export",
            json={"template": True},
        )

    assert point_table.status_code == 200
    assert point_save.status_code == 202
    assert stale_point_save.status_code == 409
    assert stale_point_save.json()["detail"]["code"] == "TRAIN_COMMUNICATION_REVISION_CONFLICT"
    assert (
        normal.jobs[point_save.json()["task_id"]].task_type
        == "car_network_save_point_table"
    )
    assert plan.status_code == 200
    assert auto_group_preview.status_code == 200
    assert adjustment_preview.status_code == 200
    assert point_table_preview.status_code == 200
    assert point_table_preview.json()["items"] == []
    assert plan_save.status_code == 202
    assert (
        normal.jobs[plan_save.json()["task_id"]].task_type == "trackside_ap_plan_save"
    )
    assert update_all.status_code == 202
    assert update_all_job.params["station"] == ""
    assert update_station.status_code == 202
    assert update_station_job.params["station"] == "站点A"
    assert update_ap.status_code == 202
    assert update_ap_job.params["ap_uuid"] == "ap-1"
    assert update_ap_job.params["ap_mac"] == "00:11:22:33:44:55"
    assert update_ap.json()["action"] == "trackside_ap_optical_update"
    assert scope_conflict.status_code == 422
    assert scope_conflict.json()["detail"]["message"] == "站点范围和 AP 身份不能同时提交"
    assert plan_export.status_code == 202
