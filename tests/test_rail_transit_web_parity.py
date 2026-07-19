from __future__ import annotations

import hashlib
import inspect
import json
import csv
import io
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mesh_analysis_test_support import (
    EmptyBaseQuery,
    EmptyOnlineQuery,
    create_mesh_analysis_fixture,
)
from web_parity_test_support import FakeExportProcessAdapter, FakeLocalProcessAdapter
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
from netconsole.models.api.rail_transit_web import OnlineMrReportRequestDTO
from netconsole.models.task_snapshot import TaskEvent, utc_now_iso
from netconsole.models.task_state import TaskState
from netconsole.services.job_center.task_application_service import (
    TaskApplicationService,
)
from netconsole.services.online_mr.query_service import OnlineMrQueryService
from netconsole.services.rail_transit.mesh_analysis_query_service import (
    MeshAnalysisQueryService,
)
from netconsole.services.mesh_storage_service import MeshStorageService
from netconsole.services.rail_transit.car_network_diagnostic import (
    POINT_TABLE_FIELDS,
    CarNetworkNode,
    CarNetworkPointTableStore,
)


RAIL_FEATURE_IDS = (
    "web.rail_car_network_diagnostic",
    "web.train_communication_monitoring",
    "web.online_mr_report_export",
    "web.online_mr_parse",
    "online_mr.collection_notes",
    "web.mesh_analysis_import",
    "web.mesh_analysis_report_export",
    "web.rail_car_network_diagnostic_execute",
    "web.rail_task_control",
    "web.rail_car_network_point_table_write",
    "web.rail_car_network_point_table_export",
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


def test_point_table_and_trackside_plan_routes_reach_application_tasks(
    tmp_path: Path,
) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    Database(paths.site_db_path("demo")).initialize()
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
        "web.rail_trackside_ap_plan",
        "web.rail_trackside_ap_plan_write",
        "web.rail_trackside_ap_plan_export",
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
        plan_save = client.post(
            "/api/rail-transit/trackside-ap-business/plan/save",
            json={"rows": [], "explicit_confirmation": True},
        )
        blocked_export = client.post(
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
    assert plan_save.status_code == 202
    assert (
        normal.jobs[plan_save.json()["task_id"]].task_type == "trackside_ap_plan_save"
    )
    assert blocked_export.status_code == 503
    assert blocked_export.json()["detail"]["code"] == "BLOCKED_ON_TASK_WINDOW"


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
        "available",
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
    assert _normal.jobs[started.task_id].params["train_id"] == "列车01"
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
) -> None:
    paths, session_id, detail_db, _raw, _existing = create_mesh_analysis_fixture(
        tmp_path
    )
    paths.ensure_site_dirs("demo")
    mesh_query = MeshAnalysisQueryService(
        paths, base_query=EmptyBaseQuery(), online_mr_query=EmptyOnlineQuery()
    )
    service, _normal, export, _tasks = _service(paths, mesh_query)

    started = service.start_mesh_report("demo", session_id)
    job = export.jobs[started.task_id]
    assert job.job_type == "mesh_analysis_report"
    assert Path(job.db_path) == detail_db
    assert job.params["payload"]["source_file_ids"] == [1]

    export.complete(started.task_id, b"mesh-xlsx")
    completed = service.get_task("demo", started.task_id)
    path, _name = service.open_mesh_report("demo", completed.artifact_id)
    assert completed.available is True
    assert path.is_relative_to(paths.mesh_mr_export_dir("demo", "列车01-MR-CT"))


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
        paths, base_query=EmptyBaseQuery(), online_mr_query=EmptyOnlineQuery()
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
            "web.rail_car_network_diagnostic_execute"
        ].update(visible=False, enabled=False, client_package=False)
        blocked_car = client.post(
            "/api/rail-transit/train-communication/trains/train-1/diagnostics"
        )
        client.app.state.feature_gate.features["web.mesh_analysis_import"].update(
            visible=False, enabled=False, client_package=False
        )
        blocked_mesh = client.post(
            "/api/online-mr/mesh-analysis/import",
            files={"files": ("fixture.log", b"mesh", "text/plain")},
            data={"mr_id": profile.mr_id},
        )
        client.app.state.feature_gate.features["web.online_mr_report_export"].update(
            visible=False, enabled=False, client_package=False
        )
        blocked_online_report = client.post(
            "/api/online-mr/sessions/missing/report", json={}
        )
        client.app.state.feature_gate.features[
            "web.mesh_analysis_report_export"
        ].update(visible=False, enabled=False, client_package=False)
        blocked_mesh_report = client.post(
            "/api/rail-transit/mesh-analysis/sessions/missing/report"
        )
        client.app.state.feature_gate.features["web.rail_task_control"].update(
            visible=False, enabled=False, client_package=False
        )
        blocked_task_recovery = client.post("/api/online-mr/tasks/recover")
        client.app.state.feature_gate.features[
            "web.rail_car_network_diagnostic_execute"
        ].update(visible=True, enabled=True, client_package=True)
        blocked_car_without_control = client.post(
            "/api/rail-transit/train-communication/trains/train-1/diagnostics"
        )
        client.app.state.feature_gate.features["web.mesh_analysis_import"].update(
            visible=True, enabled=True, client_package=True
        )
        blocked_mesh_without_control = client.post(
            "/api/online-mr/mesh-analysis/import",
            files={"files": ("fixture.log", b"mesh", "text/plain")},
            data={"mr_id": profile.mr_id},
        )
        client.app.state.feature_gate.features["web.online_mr_report_export"].update(
            visible=True, enabled=True, client_package=True
        )
        blocked_online_report_without_control = client.post(
            "/api/online-mr/sessions/missing/report", json={}
        )
        client.app.state.feature_gate.features[
            "web.mesh_analysis_report_export"
        ].update(visible=True, enabled=True, client_package=True)
        blocked_mesh_report_without_control = client.post(
            "/api/rail-transit/mesh-analysis/sessions/missing/report"
        )
        client.app.state.feature_gate.features["web.rail_task_control"].update(
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
                "files": ("oversized.log", b"x" * (20 * 1024 * 1024 + 1), "text/plain")
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
