from __future__ import annotations

import hashlib
import inspect
import json
import csv
import io
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from tests.support.mesh_analysis_test_support import (
    EmptyBaseQuery,
    create_mesh_analysis_fixture,
)
from tests.support.web_parity_test_support import FakeExportProcessAdapter, FakeLocalProcessAdapter
from netconsole.application.rail_transit.web_application_service import (
    RailTransitWebApplicationService,
    RailTransitWebError,
)
from netconsole.application.web_export_process_adapter import WebExportProcessAdapter
from netconsole.backend.api.main import create_app
from netconsole.backend.api.online_mr_router import mesh_analysis_import
from netconsole.backend.api.task_router import task_dto
from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.models.api.rail_transit_web import CarNetworkPointRowDTO, OnlineMrReportRequestDTO
from netconsole.models.mesh_analysis_params import MeshAnalysisParams
from netconsole.models.task_snapshot import TaskEvent, utc_now_iso
from netconsole.models.task_state import TaskState
from netconsole.services.job_center.task_application_service import (
    TaskApplicationService,
)
from netconsole.services.online_mr.query_service import OnlineMrQueryService
from netconsole.repositories.online_mr_diagnosis_repository import OnlineMrDiagnosisRepository
from netconsole.services.rail_transit.online_mr_diagnosis_parser import PARSER_VERSION
from netconsole.services.rail_transit.mesh_analysis_query_service import (
    MeshAnalysisQueryService,
)
from netconsole.services.mesh_storage_service import MeshStorageService
from netconsole.services.mesh_analysis_params_service import save_site_mesh_analysis_params
from netconsole.services.rail_transit.mesh_ap_location_service import MeshApLocationSnapshot
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


def test_mesh_five_source_delete_starts_one_job_and_projects_safe_items(
    tmp_path: Path,
) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    service, normal, _export, _tasks = _service(paths)
    profile_id = "12345678-abcd-4321-abcd-1234567890ab"
    session_ids = [f"{profile_id}:{index}" for index in range(1, 6)]

    started = service.start_mesh_sources_delete(
        "demo",
        session_ids,
        delete_raw_archive=True,
        delete_parsed_data=True,
        delete_generated_reports=True,
        explicit_confirmation=True,
    )

    assert len(normal.jobs) == 1
    job = normal.jobs[started.task_id]
    assert job.task_type == "mesh_analysis_sources_delete"
    assert job.params["session_ids"] == session_ids
    assert "mesh-import:demo" in job.params["resource_keys"]
    assert all(
        f"mesh_source:{session_id}" in job.params["resource_keys"]
        for session_id in session_ids
    )

    items = [
        {
            "session_id": session_id,
            "status": "deleted",
            "success": True,
            "message": "来源归档及分析结果已删除",
            "delete_raw_archive": True,
            "private_path": "must-not-leak",
        }
        for session_id in session_ids
    ]
    normal.complete(
        started.task_id,
        {
            "requested_count": 5,
            "success_count": 5,
            "failed_count": 0,
            "skipped_count": 0,
            "delete_raw_archive": True,
            "items": items,
        },
    )
    completed = service.get_task("demo", started.task_id)

    assert completed.result_summary == {
        "requested_count": 5,
        "success_count": 5,
        "failed_count": 0,
        "skipped_count": 0,
        "delete_raw_archive": True,
        "items_count": 5,
        "items": [
            {
                "session_id": session_id,
                "status": "deleted",
                "success": True,
                "message": "来源归档及分析结果已删除",
                "delete_raw_archive": True,
            }
            for session_id in session_ids
        ],
    }


def _mark_online_mr_parsed_ready(session_dir: Path, session_id: str) -> None:
    repository = OnlineMrDiagnosisRepository(session_dir / "parsed" / "online_diagnosis.sqlite")
    repository.initialize()
    raw_root = session_dir / "raw"
    fingerprint = json.dumps(
        [
            {
                "path": path.relative_to(raw_root).as_posix(),
                "size": path.stat().st_size,
                "mtime_ns": path.stat().st_mtime_ns,
            }
            for path in sorted(raw_root.rglob("*"))
            if path.is_file() and not path.is_symlink()
        ],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ) if raw_root.is_dir() else "[]"
    repository.replace_parse_metadata(
        (session_id, "2026-07-20 12:00:00", PARSER_VERSION, fingerprint, "{}", "OK", "")
    )


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


def _online_mr_session(
    paths: PathResolver, session_id: str = "session-actions"
) -> Path:
    session = paths.online_mr_session_dir("demo", "MR-01", session_id)
    for name in ("raw", "parsed", "view", "logs", "outputs"):
        (session / name).mkdir(parents=True, exist_ok=True)
    (session / "session_meta.json").write_text(
        json.dumps(
            {
                "session_id": session_id,
                "site": "demo",
                "mr_name": "MR-01",
                "device_id": 7,
                "device_name": "列车07 MR",
                "status": "STOPPED",
                "started_at": "2026-07-17 10:00:00",
                "ended_at": "2026-07-17 10:05:00",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (session / "raw" / "mesh_link_raw.log").write_text("sample", encoding="utf-8")
    return session


def test_online_mr_note_and_parse_use_real_session_and_task(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    service, normal, _export, _tasks = _service(paths)
    session = _online_mr_session(paths)

    with pytest.raises(RailTransitWebError) as confirmation:
        service.add_online_mr_note(
            "demo", "session-actions", note="进入区间", explicit_confirmation=False
        )
    assert confirmation.value.code == "CONFIRMATION_REQUIRED"

    note = service.add_online_mr_note(
        "demo",
        "session-actions",
        note="进入区间",
        explicit_confirmation=True,
        audit={"source": "伪造来源", "action": "伪造动作", "operator": "tester"},
    )
    assert note.title == "进入区间"
    persisted = json.loads((session / "manual_notes.jsonl").read_text(encoding="utf-8"))
    assert persisted["audit"]["source"] == "electron_online_mr"
    assert persisted["audit"]["action"] == "add_note"
    assert persisted["audit"]["operator"] == "tester"
    assert service.notes("demo", "session-actions")[0].title == "进入区间"

    task = service.start_online_mr_parse("demo", "session-actions", force_reparse=True)
    assert normal.jobs[task.task_id].task_type == "online_mr_parse"
    assert normal.jobs[task.task_id].params["session_dir"] == str(session.resolve())
    assert normal.jobs[task.task_id].params["force_reparse"] is True
    assert normal.jobs[task.task_id].params["resource_keys"] == [
        "online_mr_session:demo:session-actions"
    ]


def test_online_mr_ensure_current_reuses_one_inflight_upgrade_task(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    service, _normal, _export, tasks = _service(paths)
    _online_mr_session(paths, "session-auto-upgrade")

    first = service.ensure_online_mr_parsed_database_current("demo", "session-auto-upgrade")
    second = service.ensure_online_mr_parsed_database_current("demo", "session-auto-upgrade")

    assert first.status == "UPGRADING"
    assert first.task is not None
    assert second.status == "UPGRADING"
    assert second.task is not None
    assert second.task.task_id == first.task.task_id
    active = tasks.repository("demo").list(
        statuses={TaskState.PENDING, TaskState.STARTING, TaskState.RUNNING, TaskState.STOPPING},
        limit=20,
    )
    assert [item.task_id for item in active if item.task_type == "online_mr_parse"] == [first.task.task_id]


def test_online_mr_ensure_current_is_noop_for_current_contract(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    service, normal, _export, _tasks = _service(paths)
    session = _online_mr_session(paths, "session-current")
    _mark_online_mr_parsed_ready(session, "session-current")

    result = service.ensure_online_mr_parsed_database_current("demo", "session-current")

    assert result.status == "CURRENT"
    assert result.missing_capabilities == []
    assert result.task is None
    assert normal.jobs == {}


def test_online_mr_ensure_current_persists_missing_raw_without_starting_task(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    service, normal, _export, _tasks = _service(paths)
    session = _online_mr_session(paths, "session-no-raw")
    (session / "raw" / "mesh_link_raw.log").write_text("", encoding="utf-8")

    first = service.ensure_online_mr_parsed_database_current("demo", "session-no-raw")
    second = service.ensure_online_mr_parsed_database_current("demo", "session-no-raw")

    assert first.status == "RAW_DATA_MISSING"
    assert second.status == "RAW_DATA_MISSING"
    assert second.retry_suppressed is True
    assert normal.jobs == {}


def test_online_mr_location_report_and_delete_share_session_resource(
    tmp_path: Path,
) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    service, normal, export, tasks = _service(paths)
    session = _online_mr_session(paths, "session-actions")
    _mark_online_mr_parsed_ready(session, "session-actions")
    resource_key = "online_mr_session:demo:session-actions"

    location = service.online_mr_desktop_location("demo", "session-actions")
    assert location == {
        "target_type": "file",
        "path": str((session / "raw" / "mesh_link_raw.log").resolve()),
    }
    (session / "outputs" / "session-actions.zip").write_bytes(b"package")
    package_location = service.online_mr_desktop_location("demo", "session-actions")
    assert package_location == {
        "target_type": "file",
        "path": str((session / "outputs" / "session-actions.zip").resolve()),
    }

    report = service.start_online_mr_report("demo", "session-actions", "")
    snapshot = tasks.repository("demo").get(report.task_id)
    assert snapshot is not None
    assert snapshot.resource_keys == [resource_key]
    with pytest.raises(RailTransitWebError) as report_conflict:
        service.start_online_mr_delete(
            "demo",
            "session-actions",
            expected_session_id="session-actions",
            explicit_confirmation=True,
        )
    assert report_conflict.value.code == "ONLINE_MR_SESSION_TASK_ACTIVE"

    report_path = Path(str(export.jobs[report.task_id].output_path))
    export.complete(report.task_id)
    (session / "outputs" / "session-actions.zip").unlink()
    (session / "raw" / "mesh_link_raw.log").unlink()
    fallback_location = service.online_mr_desktop_location(
        "demo", "session-actions"
    )
    assert fallback_location == {
        "target_type": "directory",
        "path": str((session / "raw").resolve()),
    }
    artifact = service.artifact_store.online_mr_session_artifacts(
        "demo",
        "session-actions",
        owner=service._OWNER,
        task_type=service._ARTIFACT_TASK_TYPES["online_mr_report"],
    )[0]
    manifest_path = Path(str(artifact["manifest_path"]))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["context"]["session_id"] = "missing-session-with-report"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    report_location = service.online_mr_desktop_location(
        "demo", "missing-session-with-report"
    )
    assert report_location == {
        "target_type": "file",
        "path": str(report_path.resolve()),
    }
    with pytest.raises(RailTransitWebError) as missing_location:
        service.online_mr_desktop_location("demo", "missing-session")
    assert missing_location.value.code == "ONLINE_MR_LOCAL_FILES_MISSING"

    manifest["context"]["session_id"] = "session-actions"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    deletion = service.start_online_mr_delete(
        "demo",
        "session-actions",
        expected_session_id="session-actions",
        explicit_confirmation=True,
    )
    job = normal.jobs[deletion.task_id]
    assert deletion.action == "online_mr_session_delete"
    assert deletion.result_summary["session_id"] == "session-actions"
    assert job.params["resource_keys"] == [resource_key]
    assert job.params["session_dir"] == str(session.resolve())
    assert all(
        Path(str(item["path"])).is_relative_to(paths.online_mr_root("demo"))
        for item in job.params["artifact_items"]
    )
    with pytest.raises(RailTransitWebError) as cancel_rejected:
        service.cancel_task("demo", deletion.task_id)
    assert cancel_rejected.value.code == "TASK_NOT_CANCELLABLE"


@pytest.mark.parametrize(
    ("field", "value", "expected_code", "expected_message"),
    [
        ("status", "RUNNING", "ONLINE_MR_SESSION_RUNNING", "采集或停止处理中"),
        ("status", "STOPPING", "ONLINE_MR_SESSION_RUNNING", "采集或停止处理中"),
        ("phase", "STOPPING_TRAFFIC", "ONLINE_MR_SESSION_RUNNING", "采集或停止处理中"),
        ("phase", "PACKAGING", "ONLINE_MR_SESSION_FINALIZING", "归档、解析或打包"),
        ("phase", "ARCHIVING", "ONLINE_MR_SESSION_FINALIZING", "归档、解析或打包"),
        ("phase", "RECOVERING", "ONLINE_MR_SESSION_FINALIZING", "归档、解析或打包"),
    ],
)
def test_online_mr_delete_rejects_active_collection_and_finalization_states(
    tmp_path: Path,
    field: str,
    value: str,
    expected_code: str,
    expected_message: str,
) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    service, _normal, _export, _tasks = _service(paths)
    session = _online_mr_session(paths, f"session-{field}")
    metadata = json.loads((session / "session_meta.json").read_text(encoding="utf-8"))
    metadata[field] = value
    (session / "session_meta.json").write_text(
        json.dumps(metadata, ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(RailTransitWebError) as raised:
        service.start_online_mr_delete(
            "demo",
            f"session-{field}",
            expected_session_id=f"session-{field}",
            explicit_confirmation=True,
        )

    assert raised.value.code == expected_code
    assert expected_message in str(raised.value)
    assert session.is_dir()


def test_online_mr_session_action_api_rejects_browser_location_and_confirms_delete(
    tmp_path: Path,
) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    paths.ensure_site_dirs("demo")
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.app_config_path.write_text('{"current_site":"demo"}', encoding="utf-8")
    Database(paths.site_db_path("demo")).initialize()
    session = _online_mr_session(paths, "session-api-delete")
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
        query_service=app.state.online_mr_query_service,
        mesh_query_service=app.state.mesh_analysis_query_service,
    )
    _enable_features(app)

    with TestClient(app, base_url="http://127.0.0.1") as client:
        browser_location = client.post(
            "/api/online-mr/sessions/session-api-delete/desktop-location"
        )
        mismatch = client.request(
            "DELETE",
            "/api/online-mr/sessions/session-api-delete",
            json={
                "expected_session_id": "other-session",
                "explicit_confirmation": True,
            },
        )
        accepted = client.request(
            "DELETE",
            "/api/online-mr/sessions/session-api-delete",
            json={
                "expected_session_id": "session-api-delete",
                "explicit_confirmation": True,
            },
        )

    assert browser_location.status_code == 403
    assert mismatch.status_code == 422
    assert mismatch.json()["detail"]["code"] == "CONFIRMATION_REQUIRED"
    assert accepted.status_code == 202
    assert accepted.json()["action"] == "online_mr_session_delete"
    assert str(session.resolve()) not in accepted.text


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


def test_mesh_upload_uses_controlled_staging_derived_profile_and_cancel_cleanup(
    tmp_path: Path,
) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    service, normal, _export, _tasks = _service(paths)
    profile = MeshStorageService("demo", paths).create_mr_profile("车载 MR-01")
    staging = service.create_mesh_staging("demo")
    staged = staging / "001-fixture.log"
    staged.write_bytes(b"fixture log")

    started = service.start_mesh_import(
        "demo",
        mr_id=profile.mr_id,
        staging_dir=staging,
        uploads=[staged],
    )

    job = normal.jobs[started.task_id]
    assert started.action == "mesh_log_import"
    assert set(started.model_dump()) == {
        "task_id",
        "status",
        "action",
        "artifact_id",
        "artifact_name",
        "available",
        "artifact_state",
        "artifact_message",
        "sha256",
        "size_bytes",
        "message",
        "error_message",
        "result_summary",
    }
    assert (
        job.params["profile"]["relative_folder_path"]
        == f"files/rail_transit/mr_raw_mesh/{profile.safe_folder_name}"
    )
    assert Path(job.params["files"][0]).is_relative_to(paths.runtime_cache_dir)

    cancelled = service.cancel_task("demo", started.task_id)
    assert cancelled.status == "CANCELLED"
    assert not staging.exists()


def test_mesh_rebuild_reuses_job_center_and_requires_confirmation(tmp_path: Path) -> None:
    paths, session_id, _detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    mesh_query = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]
    service, normal, _export, _tasks = _service(paths, mesh_query=mesh_query)

    with pytest.raises(RailTransitWebError) as confirmation:
        service.start_mesh_rebuild("demo", session_id, explicit_confirmation=False)
    assert confirmation.value.code == "CONFIRMATION_REQUIRED"

    started = service.start_mesh_rebuild("demo", session_id, explicit_confirmation=True)

    assert started.action == "mesh_source_rebuild"
    assert normal.jobs[started.task_id].task_type == "mesh_source_rebuild"
    assert normal.jobs[started.task_id].params["session_id"] == session_id
    assert normal.jobs[started.task_id].params["explicit_confirmation"] is True


def test_mesh_maintenance_is_explicit_and_keeps_identity_refresh_separate_from_reparse(
    tmp_path: Path,
) -> None:
    paths, session_id, _detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    mesh_query = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]
    service, normal, _export, _tasks = _service(paths, mesh_query=mesh_query)

    with pytest.raises(RailTransitWebError) as confirmation:
        service.start_mesh_maintenance(
            "demo",
            session_id,
            kind="identity_projection_refresh",
            explicit_confirmation=False,
        )
    assert confirmation.value.code == "CONFIRMATION_REQUIRED"

    identity = service.start_mesh_maintenance(
        "demo",
        session_id,
        kind="identity_projection_refresh",
        explicit_confirmation=True,
    )
    identity_job = normal.jobs[identity.task_id]
    normal.complete(identity.task_id)
    parser = service.start_mesh_maintenance(
        "demo",
        session_id,
        kind="parser_rebuild",
        explicit_confirmation=True,
    )

    parser_job = normal.jobs[parser.task_id]
    assert identity_job.task_type == parser_job.task_type == "mesh_analysis_maintenance"
    assert identity_job.params["maintenance_kind"] == "identity_projection_refresh"
    assert identity_job.params["force_reparse"] is False
    assert parser_job.params["maintenance_kind"] == "parser_rebuild"
    assert parser_job.params["force_reparse"] is True


def test_mesh_upload_staging_accepts_gzip_logs_and_preserves_parser_suffix(
    tmp_path: Path,
) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    service, _normal, _export, _tasks = _service(paths)

    staging, uploads = service.stage_mesh_uploads(
        "demo",
        [("MR-01-meshlog.log.gz", io.BytesIO(b"gzip fixture"))],
    )

    assert len(uploads) == 1
    assert uploads[0].name.endswith(".log.gz")
    assert service._validated_staged_files("demo", staging, uploads) == uploads
    service.discard_mesh_staging("demo", staging)


def test_mesh_upload_staging_accepts_file_between_twenty_and_twenty_five_mib(
    tmp_path: Path,
) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    service, _normal, _export, _tasks = _service(paths)
    payload = b"x" * (20 * 1024 * 1024 + 1)

    staging, uploads = service.stage_mesh_uploads(
        "demo",
        [("meshlog.log", io.BytesIO(payload))],
    )

    assert uploads[0].stat().st_size == len(payload)
    service.discard_mesh_staging("demo", staging)


def test_mesh_upload_staging_rejects_file_over_twenty_five_mib_without_leaks(
    tmp_path: Path,
) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    service, _normal, _export, _tasks = _service(paths)

    with pytest.raises(RailTransitWebError) as error:
        service.stage_mesh_uploads(
            "demo",
            [("meshlog.log", io.BytesIO(b"x" * (25 * 1024 * 1024 + 1)))],
        )

    assert error.value.code == "FILE_TOO_LARGE"
    assert str(error.value) == "单个 MESH 日志不得超过 25 MiB"
    upload_root = paths.runtime_cache_dir / "rail_web_uploads" / "demo"
    assert not upload_root.exists() or not any(upload_root.iterdir())


def test_mesh_upload_rejects_type_symlink_and_site_escape_without_leaks(
    tmp_path: Path,
) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    service, _normal, _export, _tasks = _service(paths)
    staging = service.create_mesh_staging("demo")
    csv = staging / "fixture.csv"
    csv.write_bytes(b"no")
    with pytest.raises(RailTransitWebError) as invalid_type:
        service.start_mesh_import(
            "demo",
            mr_id="MR-01",
            staging_dir=staging,
            uploads=[csv],
        )
    assert invalid_type.value.code == "FILE_TYPE_INVALID"
    assert not staging.exists()

    staging = service.create_mesh_staging("demo")
    outside = tmp_path / "outside.log"
    outside.write_bytes(b"outside")
    link = staging / "link.log"
    try:
        link.symlink_to(outside)
    except OSError:
        service.discard_mesh_staging("demo", staging)
    else:
        with pytest.raises(RailTransitWebError) as symlink_error:
            service.start_mesh_import(
                "demo",
                mr_id="MR-01",
                staging_dir=staging,
                uploads=[link],
            )
        assert symlink_error.value.code == "FILE_PATH_INVALID"

    for value in (r"..\..\escaped", r"\\server\share", r"C:\escaped"):
        with pytest.raises(RailTransitWebError) as site_error:
            service.create_mesh_staging(value)
        assert site_error.value.code == "SITE_CONTEXT_INVALID"
    assert not (paths.sites_dir.parent / "escaped").exists()


def test_online_mr_export_manifest_hash_download_cancel_and_ownership(
    tmp_path: Path,
) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    service, _normal, export, tasks = _service(paths)
    session_dir = paths.online_mr_session_dir("demo", "MR-01", "session-1")
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "session_meta.json").write_text(
        json.dumps(
            {
                "session_id": "session-1",
                "site": "demo",
                "mr_name": "MR-01",
                "status": "COMPLETED",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RailTransitWebError) as parse_required:
        service.start_online_mr_report("demo", "session-1", "blocked.xlsx")
    assert parse_required.value.code == "PARSE_REQUIRED"
    _mark_online_mr_parsed_ready(session_dir, "session-1")
    started = service.start_online_mr_report("demo", "session-1", "report.xlsx")
    content = b"fixture-xlsx"
    output = export.complete(started.task_id, content)
    completed = service.get_task("demo", started.task_id)
    opened, name = service.open_online_mr_report("demo", completed.artifact_id)

    assert output == opened
    assert name.endswith(".xlsx")
    assert completed.available is True
    assert completed.sha256 == hashlib.sha256(content).hexdigest()
    assert completed.size_bytes == len(content)
    assert "path" not in completed.model_dump()
    with pytest.raises(RailTransitWebError):
        service.open_mesh_report("demo", completed.artifact_id)

    cancelled = service.start_online_mr_report("demo", "session-1", "cancelled.xlsx")
    cancelled_output = Path(export.jobs[cancelled.task_id].output_path)
    after_cancel = service.cancel_task("demo", cancelled.task_id)
    assert after_cancel.status == "CANCELLED"
    assert not cancelled_output.exists()
    with pytest.raises(RailTransitWebError):
        service.open_online_mr_report("demo", cancelled.artifact_id)

    tasks.create_external_task(
        task_id="wrong-owner",
        task_type="car_network_refresh_all",
        task_name="wrong",
        source="local",
        site_name="demo",
        owner="other",
    )
    with pytest.raises(RailTransitWebError) as wrong_owner:
        service.get_task("demo", "wrong-owner")
    assert wrong_owner.value.code == "TASK_NOT_FOUND"


def test_artifact_download_requires_task_database_anchor(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    service, _normal, export, tasks = _service(paths)
    session_dir = paths.online_mr_session_dir("demo", "MR-01", "session-anchor")
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "session_meta.json").write_text(
        json.dumps(
            {
                "session_id": "session-anchor",
                "site": "demo",
                "mr_name": "MR-01",
                "status": "COMPLETED",
            }
        ),
        encoding="utf-8",
    )

    _mark_online_mr_parsed_ready(session_dir, "session-anchor")
    started = service.start_online_mr_report("demo", "session-anchor", "anchor.xlsx")
    output = export.complete(started.task_id, b"trusted")
    completed = service.get_task("demo", started.task_id)
    snapshot = tasks.repository("demo").get(started.task_id)
    assert snapshot is not None
    assert snapshot.result_path == ""
    assert set(snapshot.result) == {
        "artifact_id",
        "artifact_source",
        "artifact_type",
        "artifact_name",
        "sha256",
        "size_bytes",
    }
    public = task_dto(snapshot).model_dump()
    assert public["result_path"] == ""
    assert all("path" not in key for key in public["result"])

    manifest_path = (
        paths.rail_transit_root("demo")
        / "web_artifacts"
        / "manifests"
        / f"{completed.artifact_id}.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    forged = b"forged"
    output.write_bytes(forged)
    manifest["sha256"] = hashlib.sha256(forged).hexdigest()
    manifest["size_bytes"] = len(forged)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(RailTransitWebError) as exc_info:
        service.open_online_mr_report("demo", completed.artifact_id)
    assert exc_info.value.code == "ARTIFACT_INVALID"


def test_artifact_finalization_failure_marks_task_failed_and_clears_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    service, _normal, export, tasks = _service(paths)
    session_dir = paths.online_mr_session_dir("demo", "MR-01", "session-failure")
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "session_meta.json").write_text(
        json.dumps(
            {
                "session_id": "session-failure",
                "site": "demo",
                "mr_name": "MR-01",
                "status": "COMPLETED",
            }
        ),
        encoding="utf-8",
    )

    def fail_finalization(*_args, **_kwargs):
        raise ValueError("forced finalization failure")

    monkeypatch.setattr(tasks, "finalize_artifact_result", fail_finalization)
    _mark_online_mr_parsed_ready(session_dir, "session-failure")
    started = service.start_online_mr_report("demo", "session-failure", "failure.xlsx")
    output = export.complete(started.task_id, b"valid export")
    snapshot = tasks.repository("demo").get(started.task_id)

    assert snapshot is not None and snapshot.status == TaskState.FAILED
    assert snapshot.result == {}
    assert snapshot.result_path == ""
    assert not output.exists()
    assert service.get_task("demo", started.task_id).available is False


def test_completed_export_manifest_is_recovered_after_callback_loss(
    tmp_path: Path,
) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    service, _normal, export, tasks = _service(paths)
    session_dir = paths.online_mr_session_dir("demo", "MR-01", "session-recovery")
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "session_meta.json").write_text(
        json.dumps(
            {
                "session_id": "session-recovery",
                "site": "demo",
                "mr_name": "MR-01",
                "status": "COMPLETED",
            }
        ),
        encoding="utf-8",
    )

    _mark_online_mr_parsed_ready(session_dir, "session-recovery")
    started = service.start_online_mr_report(
        "demo", "session-recovery", "recovered.xlsx"
    )
    leaked_path = str(export.jobs[started.task_id].output_path)
    subscription = tasks.events.open_stream()
    export.callbacks.pop(started.task_id)
    export.complete(started.task_id, b"recovered-report")
    live_events = [subscription.get(timeout=1)]
    subscription.close()
    stored_snapshot = tasks.repository("demo").get(started.task_id)
    public_snapshot = tasks.get_task(started.task_id)
    stored_events = tasks.list_events(started.task_id, limit=100)
    serialized_public = json.dumps(
        {
            "task": task_dto(public_snapshot).model_dump(mode="json")
            if public_snapshot
            else {},
            "events": stored_events,
            "live": live_events,
        },
        ensure_ascii=False,
    )
    assert stored_snapshot is not None and stored_snapshot.result_path == ""
    assert "output_path" not in stored_snapshot.result
    assert leaked_path not in serialized_public
    assert "output_path" not in serialized_public
    assert live_events[0]["type"] == "finished"
    assert service.get_task("demo", started.task_id).available is False

    recovered = service.recover_tasks("demo")
    completed = service.get_task("demo", started.task_id)

    assert [item.task_id for item in recovered] == [started.task_id]
    assert completed.available is True
    assert completed.sha256 == hashlib.sha256(b"recovered-report").hexdigest()

    cancelled = service.start_online_mr_report(
        "demo", "session-recovery", "cancel-recovery.xlsx"
    )
    cancelled_job = export.jobs[cancelled.task_id]
    cancelled_output = Path(cancelled_job.output_path)
    cancelled_temp = cancelled_output.with_name(
        f"{cancelled_output.name}.{cancelled.task_id}.tmp"
    )
    cancelled_temp.write_bytes(b"partial")
    export.callbacks.pop(cancelled.task_id)
    service.cancel_task("demo", cancelled.task_id)
    assert cancelled_temp.is_file()

    recovered_cancel = service.recover_tasks("demo")
    assert cancelled.task_id in [item.task_id for item in recovered_cancel]
    assert not cancelled_temp.exists()
    with pytest.raises(RailTransitWebError):
        service.open_online_mr_report("demo", cancelled.artifact_id)


def test_completed_export_with_deleted_output_stays_completed_and_marks_artifact_missing(
    tmp_path: Path,
) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    service, _normal, export, tasks = _service(paths)
    session_dir = paths.online_mr_session_dir("demo", "MR-01", "session-missing-output")
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "session_meta.json").write_text(
        json.dumps(
            {
                "session_id": "session-missing-output",
                "site": "demo",
                "mr_name": "MR-01",
                "status": "COMPLETED",
            }
        ),
        encoding="utf-8",
    )
    _mark_online_mr_parsed_ready(session_dir, "session-missing-output")
    started = service.start_online_mr_report(
        "demo",
        "session-missing-output",
        "missing-output.xlsx",
    )
    output = export.complete(started.task_id, b"completed-report")
    output.unlink()

    service.recover_tasks("demo")
    stored = tasks.repository("demo").get(started.task_id)
    public = service.get_task("demo", started.task_id)

    assert stored is not None and stored.status is TaskState.COMPLETED
    assert "报告恢复校验失败" not in stored.error_message
    assert public.status == TaskState.COMPLETED.value
    assert public.available is False
    assert public.artifact_state == "MISSING"
    assert public.artifact_message == "导出文件已不存在"


def test_dismissed_failed_export_is_skipped_during_recovery(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    service, _normal, export, tasks = _service(paths)
    session_dir = paths.online_mr_session_dir("demo", "MR-01", "session-dismissed")
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "session_meta.json").write_text(
        json.dumps(
            {
                "session_id": "session-dismissed",
                "site": "demo",
                "mr_name": "MR-01",
                "status": "COMPLETED",
            }
        ),
        encoding="utf-8",
    )
    _mark_online_mr_parsed_ready(session_dir, "session-dismissed")
    started = service.start_online_mr_report(
        "demo",
        "session-dismissed",
        "dismissed.xlsx",
    )
    partial = Path(export.jobs[started.task_id].output_path).with_name(
        f"dismissed.xlsx.{started.task_id}.tmp"
    )
    partial.write_bytes(b"partial")
    export.callbacks.pop(started.task_id)
    completion = tasks.complete(started.task_id, 1)
    export._finish(started.task_id, 1, completion, False)
    repository = tasks.repository("demo")
    repository.acknowledge_attention_tasks(task_ids=[started.task_id])
    repository.dismiss_task(started.task_id, dismissed_by="tester")
    event_count = len(tasks.list_events(started.task_id, limit=100))

    recovered = service.recover_tasks("demo")
    stored = repository.get(started.task_id)

    assert started.task_id not in [item.task_id for item in recovered]
    assert stored is not None and stored.status is TaskState.FAILED
    assert stored.dismissed_at
    assert partial.is_file()
    assert len(tasks.list_events(started.task_id, limit=100)) == event_count


def test_task_public_boundary_sanitizes_legacy_web_export_paths(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    service, _normal, export, tasks = _service(paths)
    session_dir = paths.online_mr_session_dir("demo", "MR-01", "session-legacy-path")
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "session_meta.json").write_text(
        json.dumps(
            {
                "session_id": "session-legacy-path",
                "site": "demo",
                "mr_name": "MR-01",
                "status": "COMPLETED",
            }
        ),
        encoding="utf-8",
    )
    _mark_online_mr_parsed_ready(session_dir, "session-legacy-path")
    started = service.start_online_mr_report(
        "demo", "session-legacy-path", "legacy.xlsx"
    )
    leak = str(export.jobs[started.task_id].output_path)
    repository = tasks.repository("demo")
    snapshot = repository.get(started.task_id)
    assert snapshot is not None
    now = utc_now_iso()
    repository.record(
        replace(
            snapshot,
            status=TaskState.COMPLETED,
            finished_time=now,
            updated_time=now,
            result_path=leak,
            result={"output_path": leak, "row_count": 1},
            error_message=f"导出失败：{leak}",
        ),
        TaskEvent(
            event_id="legacy-web-export-path-event",
            task_id=started.task_id,
            type="finished",
            time=now,
            source="worker",
            payload={"message": f"导出完成：{leak}", "result": {"output_path": leak}},
        ),
    )

    public_task = tasks.get_task(started.task_id)
    repository_task = repository.get(started.task_id)
    public_events = tasks.list_events(started.task_id, limit=100)
    all_events = tasks.list_all_events(limit=100)
    serialized = json.dumps(
        {
            "task": task_dto(public_task).model_dump(mode="json")
            if public_task
            else {},
            "repository_task": task_dto(repository_task).model_dump(mode="json")
            if repository_task
            else {},
            "events": public_events,
            "all_events": all_events,
        },
        ensure_ascii=False,
    )
    assert leak not in serialized
    assert "output_path" not in serialized
    assert "<redacted-path>" in serialized


def test_rail_task_dto_sanitizes_legacy_web_export_paths(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    service, _normal, export, tasks = _service(paths)
    session_dir = paths.online_mr_session_dir("demo", "MR-01", "session-legacy-dto")
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "session_meta.json").write_text(
        json.dumps(
            {
                "session_id": "session-legacy-dto",
                "site": "demo",
                "mr_name": "MR-01",
                "status": "COMPLETED",
            }
        ),
        encoding="utf-8",
    )
    _mark_online_mr_parsed_ready(session_dir, "session-legacy-dto")
    started = service.start_online_mr_report(
        "demo", "session-legacy-dto", "legacy-dto.xlsx"
    )
    leak = str(export.jobs[started.task_id].output_path)
    repository = tasks.repository("demo")
    snapshot = repository.get(started.task_id)
    assert snapshot is not None
    now = utc_now_iso()
    repository.record(
        replace(
            snapshot,
            status=TaskState.COMPLETED,
            finished_time=now,
            updated_time=now,
            result_path=leak,
            result={"output_path": leak, "row_count": 1},
            message=f"导出完成：{leak}",
            error_message=f"导出失败：{leak}",
        ),
        TaskEvent(
            event_id="legacy-rail-web-export-dto-event",
            task_id=started.task_id,
            type="finished",
            time=now,
            source="worker",
            payload={},
        ),
    )

    serialized = json.dumps(
        service.get_task("demo", started.task_id).model_dump(mode="json"),
        ensure_ascii=False,
    )

    assert leak not in serialized
    assert "output_path" not in serialized
    assert "<redacted-path>" in serialized


def test_rail_task_dto_redacts_non_export_paths_and_secrets(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    service, _normal, _export, tasks = _service(paths)
    _save_complete_point_table(paths, "列车01")
    started = service.start_car_network_diagnostic("demo", train_id="列车01")
    assert _normal.jobs[started.task_id].task_type == "car_network_diagnostic"
    assert _normal.jobs[started.task_id].params["train_id"] == "train:01"
    repository = tasks.repository("demo")
    snapshot = repository.get(started.task_id)
    assert snapshot is not None
    leak = str(tmp_path / "rail-diagnostic.json")
    now = utc_now_iso()
    repository.record(
        replace(
            snapshot,
            status=TaskState.FAILED,
            finished_time=now,
            updated_time=now,
            message=f"读取失败：{leak}",
            error_message="password=rail-secret credential=credential-secret",
        ),
        TaskEvent(
            event_id="legacy-rail-local-path-event",
            task_id=started.task_id,
            type="failed",
            time=now,
            source="worker",
            payload={},
        ),
    )

    serialized = json.dumps(
        service.get_task("demo", started.task_id).model_dump(mode="json"),
        ensure_ascii=False,
    )

    assert leak not in serialized
    assert "rail-secret" not in serialized
    assert "credential-secret" not in serialized
    assert "<redacted-path>" in serialized
    assert "password=<redacted>" in serialized
    assert "credential=<redacted>" in serialized


def test_online_mr_report_runs_in_independent_export_process(tmp_path: Path) -> None:
    from test_online_mr_collection import _config
    from netconsole.services.online_mr_session_store import OnlineMrSessionStore
    from netconsole.services.rail_transit.online_mr_diagnosis_parser import (
        OnlineMrDiagnosisParser,
    )

    paths, config = _config(tmp_path)
    session = OnlineMrSessionStore(paths).create_session(config)
    OnlineMrDiagnosisParser(session.session_dir)._ensure_tables()
    _mark_online_mr_parsed_ready(session.session_dir, session.meta.session_id)
    service, _normal, _fake_export, tasks = _service(paths)
    adapter = WebExportProcessAdapter(tasks)
    service.export_adapter = adapter
    try:
        started = service.start_online_mr_report(
            "demo", session.meta.session_id, "online-report.xlsx"
        )
        assert adapter.wait(started.task_id, timeout=30)
        completed = service.get_task("demo", started.task_id)
        path, _name = service.open_online_mr_report("demo", completed.artifact_id)
    finally:
        adapter.shutdown()

    assert completed.status == "COMPLETED"
    assert completed.available is True
    assert path.is_file() and path.stat().st_size > 0


def test_mesh_report_uses_existing_context_and_artifact_manifest(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths, session_id, detail_db, _raw, _existing = create_mesh_analysis_fixture(
        tmp_path
    )
    paths.ensure_site_dirs("demo")
    save_site_mesh_analysis_params(
        paths,
        "demo",
        MeshAnalysisParams(link_time_window=4321, short_link_tolerance_ms=321),
    )
    mesh_query = MeshAnalysisQueryService(
        paths, base_query=EmptyBaseQuery()
    )
    monkeypatch.setattr(
        mesh_query,
        "ap_location_snapshot",
        lambda _site_id: MeshApLocationSnapshot.from_serializable(
            [
                {
                    "name": "AP-01",
                    "mac": "000000000010",
                    "station": "车站A",
                    "section": "区间A-B",
                    "mileage": "K12+300",
                    "line_side": "上行",
                }
            ]
        ),
    )
    service, _normal, export, _tasks = _service(paths, mesh_query)

    override = {
        "link_time_window": 3000,
        "short_link_tolerance_ms": 250,
        "pingpong_tolerance_ms": 500,
        "merge_same_physical_ap_dual_radio": True,
        "include_log_boundary_segments": False,
        "service_type": "PIS",
        "wifi_type": "WiFi6",
    }
    started = service.start_mesh_report("demo", session_id, analysis_params_override=override)
    job = export.jobs[started.task_id]
    assert job.job_type == "mesh_analysis_report"
    assert Path(job.db_path) == detail_db
    assert job.params["payload"]["source_file_ids"] == [1]
    assert job.params["payload"]["options"]["site_analysis_params"]["main_link_switch_time_ms"] == 4321
    assert job.params["payload"]["options"]["site_analysis_params"]["short_link_tolerance_ms"] == 321
    assert job.params["payload"]["options"]["analysis_params_override"]["link_time_window"] == 3000
    assert job.params["payload"]["options"]["analysis_params_override"]["main_link_switch_time_ms"] == 3000
    assert job.params["payload"]["options"]["ap_location_snapshot"] == [
        {
            "name": "AP-01",
            "point_code": "",
            "mac": "0000-0000-0010",
            "station": "车站A",
            "section": "区间A-B",
            "section_start_station": "",
            "section_end_station": "",
            "mileage": "K12+300",
            "line_side": "上行",
            "direction": "",
            "identity_status": "unresolved",
            "identity_source": "",
            "identity_reason": "",
        }
    ]

    export.complete(started.task_id, b"mesh-xlsx")
    completed = service.get_task("demo", started.task_id)
    path, _name = service.open_mesh_report("demo", completed.artifact_id)
    assert completed.available is True
    assert path.is_relative_to(paths.mesh_mr_export_dir("demo", "列车01-MR-CT"))


def test_mesh_link_detail_export_binds_selected_source_and_uses_export_process(
    tmp_path: Path,
) -> None:
    paths, session_id, detail_db, raw, existing = create_mesh_analysis_fixture(tmp_path)
    paths.ensure_site_dirs("demo")
    mesh_query = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())
    service, _normal, export, _tasks = _service(paths, mesh_query)

    override = {
        "link_time_window": 5000,
        "link_switch_threshold": 12,
        "link_hold_rssi": 30,
        "link_establish_threshold": 5,
    }
    started = service.start_mesh_link_detail_export(
        "demo",
        session_id,
        source_file_id=1,
        analysis_params_override=override,
    )
    job = export.jobs[started.task_id]

    assert started.action == "mesh_link_detail_export"
    assert job.job_type == "mesh_link_detail_export"
    assert Path(job.db_path) == detail_db
    assert job.filters == {"source_file_id": 1}
    assert job.params["analysis_params"]["link_time_window"] == 5000
    assert job.params["analysis_params"]["main_link_switch_time_ms"] == 5000
    assert job.params["ap_location_snapshot"] == []
    assert "链路明细" in Path(job.output_path).name

    saved = service.save_mesh_analysis_params("demo", override)
    assert saved.link_time_window == 5000
    assert saved.link_hold_rssi + saved.link_establish_threshold == 35
    assert service.get_mesh_analysis_params_template("demo", "PIS").main_link_switch_time_ms == 4000

    artifact = next(item for item in mesh_query.list_report_artifacts("demo", session_id) if item.deletable)
    deleted = service.delete_mesh_artifact("demo", session_id, artifact.artifact_id)
    assert deleted.deleted_files == 2
    assert existing.exists() is False
    assert raw.exists() is True

    with pytest.raises(RailTransitWebError) as mismatch:
        service.start_mesh_link_detail_export("demo", session_id, source_file_id=2)
    assert mismatch.value.code == "MESH_SOURCE_NOT_FOUND"


def test_mesh_report_worker_reuses_existing_process_pipeline(tmp_path: Path) -> None:
    from netconsole.repositories.mesh_mr_repository import MeshMrRepository
    from netconsole.services.mesh_import_service import MeshImportService
    from netconsole.services.mesh_storage_service import MeshStorageService

    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    profile = MeshStorageService("demo", paths).create_mr_profile("列车01-MR-CT")
    source = tmp_path / "mesh.log"
    source.write_text(
        "[1] 2025/12/03 10:12:33.579\n"
        "[1] Active 30f5-277a-5a2f 2025/12/03 10:12:30 0d 00h 00m 03s 1 "
        "36/43 2%/4% 45%/47% 3/1 15/27 60/72060 88/105 0/5000 2/297 314/0 0/93 0/0 0/0 0/0\n",
        encoding="utf-8",
    )
    MeshImportService("demo", paths).import_files(profile, [source])
    source_id = int(
        MeshMrRepository(
            paths.mesh_mr_db_path("demo", profile.safe_folder_name)
        ).list_source_files()[0]["id"]
    )
    session_id = f"{profile.mr_id}:{source_id}"
    mesh_query = MeshAnalysisQueryService(
        paths, base_query=EmptyBaseQuery()
    )
    service, _normal, _fake_export, tasks = _service(paths, mesh_query)
    adapter = WebExportProcessAdapter(tasks)
    service.export_adapter = adapter
    try:
        started = service.start_mesh_report("demo", session_id)
        assert adapter.wait(started.task_id, timeout=30)
        completed = service.get_task("demo", started.task_id)
        if completed.status == "COMPLETED":
            path, _name = service.open_mesh_report("demo", completed.artifact_id)
        else:
            snapshot = tasks.repository("demo").get(started.task_id)
            pytest.fail(
                snapshot.error_message
                if snapshot is not None
                else "MESH export task missing"
            )
    finally:
        adapter.shutdown()

    assert completed.available is True
    assert path.is_file() and path.stat().st_size > 0


def test_task_recovery_is_scoped_to_allowed_owner_source_and_type(
    tmp_path: Path,
) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    service, normal, _export, tasks = _service(paths)
    _save_complete_point_table(paths, "train-1")
    started = service.start_car_network_diagnostic("demo", train_id="train-1")
    snapshot = tasks.repository("demo").get(started.task_id)
    assert snapshot is not None
    normal.jobs.pop(started.task_id)
    normal.callbacks.pop(started.task_id)
    tasks.repository("demo").save(
        replace(snapshot, owner_pid=2_147_483_000, status=TaskState.RUNNING)
    )
    foreign = tasks.create_external_task(
        task_id="foreign-active",
        task_type="car_network_refresh_all",
        task_name="foreign",
        source="local",
        site_name="demo",
        owner="other-owner",
    )
    tasks.repository("demo").save(
        replace(foreign, owner_pid=2_147_482_999, status=TaskState.RUNNING)
    )

    recovered = service.recover_tasks("demo")
    assert [item.task_id for item in recovered] == [started.task_id]
    assert recovered[0].status == "FAILED"
    assert tasks.repository("demo").get("foreign-active").status == TaskState.RUNNING


def test_browser_contract_removes_site_and_relative_path_and_feature_gates_are_independent(
    tmp_path: Path,
) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    paths.ensure_site_dirs("demo")
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.app_config_path.write_text('{"current_site":"demo"}', encoding="utf-8")
    Database(paths.site_db_path("demo")).initialize()
    app = create_app(
        RuntimeMode.SERVER,
        paths=paths,
        agent_service=_NoopAsyncService(),  # type: ignore[arg-type]
        traffic_service=_NoopAsyncService(),  # type: ignore[arg-type]
        frontend_dist=tmp_path / "missing",
    )
    normal = FakeLocalProcessAdapter(app.state.task_service)
    export = FakeExportProcessAdapter(app.state.task_service)
    app.state.rail_transit_web_application_service = RailTransitWebApplicationService(
        paths,
        app.state.task_service,
        process_adapter=normal,  # type: ignore[arg-type]
        export_adapter=export,  # type: ignore[arg-type]
        query_service=app.state.online_mr_query_service,
        mesh_query_service=app.state.mesh_analysis_query_service,
    )
    profile = MeshStorageService("demo", paths).create_mr_profile("MR 1")
    _enable_features(app)

    assert "site_id" not in OnlineMrReportRequestDTO.model_fields
    assert "site_id" not in inspect.signature(mesh_analysis_import).parameters
    assert (
        "relative_folder_path" not in inspect.signature(mesh_analysis_import).parameters
    )
    upload_source = inspect.getsource(mesh_analysis_import)
    assert "asyncio.to_thread" in upload_source
    assert "target.open" not in upload_source
    assert "handle.write" not in upload_source

    with TestClient(app) as client:
        client.app.state.feature_gate.features[
            "capability.train_communication.diagnostic_execute"
        ].update(visible=False, enabled=False, client_package=False)
        blocked_car = client.post(
            "/api/rail-transit/train-communication/trains/train-1/diagnostics"
        )
        client.app.state.feature_gate.features["capability.mesh.import"].update(
            visible=False, enabled=False, client_package=False
        )
        blocked_mesh = client.post(
            "/api/online-mr/mesh-analysis/import",
            files={"files": ("fixture.log", b"mesh", "text/plain")},
            data={"mr_id": profile.mr_id},
        )
        client.app.state.feature_gate.features["capability.online_mr.report_export"].update(
            visible=False, enabled=False, client_package=False
        )
        blocked_online_report = client.post(
            "/api/online-mr/sessions/missing/report", json={}
        )
        client.app.state.feature_gate.features[
            "capability.mesh.report_export"
        ].update(visible=False, enabled=False, client_package=False)
        blocked_mesh_report = client.post(
            "/api/rail-transit/mesh-analysis/sessions/missing/report"
        )
        client.app.state.feature_gate.features["capability.trackside_ap.update"].update(
            visible=False, enabled=False, client_package=False
        )
        blocked_trackside_update = client.post(
            "/api/rail-transit/trackside-ap-business/update",
            json={},
        )
        client.app.state.feature_gate.features["capability.rail_transit.task_control"].update(
            visible=False, enabled=False, client_package=False
        )
        blocked_task_recovery = client.post("/api/online-mr/tasks/recover")
        client.app.state.feature_gate.features[
            "capability.train_communication.diagnostic_execute"
        ].update(visible=True, enabled=True, client_package=True)
        blocked_car_without_control = client.post(
            "/api/rail-transit/train-communication/trains/train-1/diagnostics"
        )
        client.app.state.feature_gate.features["capability.mesh.import"].update(
            visible=True, enabled=True, client_package=True
        )
        blocked_mesh_without_control = client.post(
            "/api/online-mr/mesh-analysis/import",
            files={"files": ("fixture.log", b"mesh", "text/plain")},
            data={"mr_id": profile.mr_id},
        )
        client.app.state.feature_gate.features["capability.online_mr.report_export"].update(
            visible=True, enabled=True, client_package=True
        )
        blocked_online_report_without_control = client.post(
            "/api/online-mr/sessions/missing/report", json={}
        )
        client.app.state.feature_gate.features[
            "capability.mesh.report_export"
        ].update(visible=True, enabled=True, client_package=True)
        blocked_mesh_report_without_control = client.post(
            "/api/rail-transit/mesh-analysis/sessions/missing/report"
        )
        client.app.state.feature_gate.features["capability.rail_transit.task_control"].update(
            visible=True, enabled=True, client_package=True
        )
        rejected_site = client.post(
            "/api/online-mr/mesh-analysis/import",
            files={"files": ("fixture.log", b"mesh", "text/plain")},
            data={
                "mr_id": profile.mr_id,
                "site_id": r"..\..\escaped",
            },
        )
        oversized = client.post(
            "/api/online-mr/mesh-analysis/import",
            files={
                "files": ("oversized.log", b"x" * (25 * 1024 * 1024 + 1), "text/plain")
            },
            data={"mr_id": profile.mr_id},
        )
        accepted = client.post(
            "/api/online-mr/mesh-analysis/import",
            files={"files": ("fixture.log", b"mesh", "text/plain")},
            data={"mr_id": profile.mr_id},
        )
        cancelled = client.post(
            f"/api/online-mr/tasks/{accepted.json()['task_id']}/cancel"
        )

    assert blocked_car.status_code == 404
    assert blocked_mesh.status_code == 404
    assert blocked_online_report.json()["detail"] == "功能未启用"
    assert blocked_mesh_report.json()["detail"] == "功能未启用"
    assert blocked_trackside_update.status_code == 404
    assert blocked_trackside_update.json()["detail"] == "功能未启用"
    assert blocked_task_recovery.json()["detail"] == "功能未启用"
    assert blocked_car_without_control.status_code == 404
    assert blocked_mesh_without_control.status_code == 404
    assert blocked_online_report_without_control.status_code == 404
    assert blocked_mesh_report_without_control.status_code == 404
    assert rejected_site.status_code == 422
    assert oversized.status_code == 422
    assert accepted.status_code == 202
    assert "artifact_path" not in accepted.json()
    assert cancelled.status_code == 200
    upload_root = paths.runtime_cache_dir / "rail_web_uploads" / "demo"
    assert not upload_root.exists() or not any(upload_root.iterdir())
