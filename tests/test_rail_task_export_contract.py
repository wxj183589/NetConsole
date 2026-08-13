from __future__ import annotations

import hashlib

import inspect

import json

from dataclasses import replace

from pathlib import Path

import pytest

from fastapi.testclient import TestClient

from tests.support.job_process_test_support import FakeExportProcessAdapter, FakeLocalProcessAdapter

from netconsole.application.rail_transit.web_application_service import (
    RailTransitWebApplicationService,
    RailTransitWebError,
)

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

from netconsole.repositories.online_mr_diagnosis_repository import OnlineMrDiagnosisRepository

from netconsole.services.rail_transit.online_mr_diagnosis_parser import PARSER_VERSION

from netconsole.services.mesh_storage_service import MeshStorageService

from netconsole.services.rail_transit.car_network_diagnostic import (
    CarNetworkNode,
    CarNetworkPointTableStore,
)

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
