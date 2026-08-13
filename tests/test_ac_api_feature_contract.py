from __future__ import annotations

import json

from dataclasses import replace

from pathlib import Path

import pytest

from fastapi.testclient import TestClient

from tests.support.ac_management_web_fixture import build_ac_management_fixture

from tests.support.rail_transit_base_data_fixture import mark_base_data_copy

from tests.support.job_process_test_support import FakeExportProcessAdapter, FakeLocalProcessAdapter

from netconsole.application.ac.web_application_service import AcWebApplicationService

from netconsole.backend.api.main import create_app

from netconsole.core.database import Database

from netconsole.core.runtime_mode import RuntimeMode

from netconsole.models.task_snapshot import TaskEvent, utc_now_iso

from netconsole.models.task_state import TaskState

from netconsole.repositories.ac_repository import AcRepository

from netconsole.services.job_center.task_application_service import TaskApplicationService

from netconsole.services.rail_transit.base_data_import_service import RailTransitBaseDataImportService

from netconsole.services.rail_transit.base_data_query_service import RailTransitBaseDataQueryService

from netconsole.services.rail_transit.base_data_write_guard import BaseDataWriteGuard

from netconsole.services.rail_transit.import_preview_service import RailTransitImportPreviewService

AC_FEATURE_IDS = (
    "capability.ac.extensions",
    "capability.ac.extensions.preview",
    "capability.ac.extensions.apply",
    "capability.ac.extensions.rollback",
    "capability.ac.extensions.export",
    "capability.ac.refresh",
    "capability.ac.fit_ap.delete",
    "capability.ac.fit_ap.metadata_import",
    "capability.ac.fit_ap.metadata_write",
    "capability.ac.fit_ap.history",
    "capability.ac.fit_ap.resource_export",
    "capability.ac.dangerous_actions",
    "ac.omnipeek_name_table_export",
    "capability.ac.external_terminal",
    "capability.desktop_native_integration",
)

CSV_CONTENT = (
    "AP名称,AP_MAC,归属类型,归属站点,归属区间,区间起点站,区间终点站,场段,区域,网络,线别,里程,点位说明,方向,备注\n"
    "AP-Web,0000-0000-00aa,section,车站A,A-B 区间,A,B,,,,上行,ZDK1+100,站台,上行,web\n"
).encode("utf-8-sig")

class _NoopAsyncService:
    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

def _service(paths, tasks=None, *, desktop_action_service=None):
    mark_base_data_copy(paths)
    tasks = tasks or TaskApplicationService(paths=paths, site_name="demo")
    normal = FakeLocalProcessAdapter(tasks)
    export = FakeExportProcessAdapter(tasks)
    guard = BaseDataWriteGuard(
        paths,
        feature_enabled=True,
        write_enabled=True,
        copy_write_enabled=True,
        rollback_enabled=True,
    )
    imports = RailTransitBaseDataImportService(paths, guard=guard)
    previews = RailTransitImportPreviewService(
        RailTransitBaseDataQueryService(paths), import_service=imports
    )
    service = AcWebApplicationService(
        paths,
        tasks,
        process_adapter=normal,  # type: ignore[arg-type]
        import_preview_service=previews,
        base_import_service=imports,
        export_adapter=export,  # type: ignore[arg-type]
        desktop_action_service=desktop_action_service,
    )
    return service, normal, export, tasks

def _enable_features(app, feature_ids=AC_FEATURE_IDS) -> None:
    for feature_id in feature_ids:
        app.state.feature_gate.features[feature_id] = {
            "visible": True,
            "enabled": True,
            "client_package": True,
            "internal_only": False,
        }

def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, AcWebApplicationService]:
    paths, _db_path, _files = build_ac_management_fixture(tmp_path)
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.app_config_path.write_text('{"current_site":"demo"}', encoding="utf-8")
    app = create_app(
        RuntimeMode.SERVER,
        paths=paths,
        agent_service=_NoopAsyncService(),  # type: ignore[arg-type]
        traffic_service=_NoopAsyncService(),  # type: ignore[arg-type]
        frontend_dist=tmp_path / "missing",
    )
    service, _normal, _export, _tasks = _service(paths, app.state.task_service)
    app.state.ac_web_application_service = service
    _enable_features(app)
    return TestClient(app), service


def test_ac_local_rebuild_api_rejects_legacy_source_and_unknown_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _service_instance = _client(tmp_path, monkeypatch)
    with client:
        legacy_fields = client.post(
            "/api/ac-management/local-rebuild/optical",
            json={"ac_id": "ac-1", "source": "auto", "refresh_scope": "all"},
        )
        unknown_target = client.post(
            "/api/ac-management/local-rebuild/optical",
            json={"ac_id": "missing-ac"},
        )

    assert legacy_fields.status_code == 422
    assert unknown_target.status_code == 422


def test_fit_ap_batch_delete_api_starts_persistent_job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, service = _client(tmp_path, monkeypatch)
    with client:
        response = client.post(
            "/api/ac-management/fit-aps/delete",
            json={"ac_id": "ac-1", "ap_ids": ["ap-online"], "explicit_confirmation": True},
        )

    assert response.status_code == 202
    snapshot = service.task_service.repository("demo").get(response.json()["task_id"])
    assert snapshot is not None
    assert snapshot.task_type == "ac_fit_ap_delete_many"


def test_fit_ap_metadata_import_api_starts_persistent_job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, service = _client(tmp_path, monkeypatch)
    repository = AcRepository(Database(service.paths.site_db_path("demo")))
    ap = repository.get_fit_ap_resource_by_uuid("ac-1", "ap-online")
    assert ap is not None
    content = (
        f"AP名称,AP_MAC,归属站点,里程,点位说明,方向\n{ap['ap_name']},{ap['ap_mac']},Web站,,站台,上行\n"
    ).encode("utf-8-sig")
    with client:
        response = client.post(
            "/api/ac-management/fit-aps/metadata/import",
            files={"file": ("metadata.csv", content, "text/csv")},
        )

    assert response.status_code == 202
    snapshot = service.task_service.repository("demo").get(response.json()["task_id"])
    assert snapshot is not None
    assert snapshot.task_type == "fit_ap_metadata_import"


def test_fit_ap_metadata_save_api_starts_normalized_persistent_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, service = _client(tmp_path, monkeypatch)
    with client:
        response = client.post(
            "/api/ac-management/aps/ap-online/metadata",
            json={
                "ac_id": "ac-1",
                "site_name": "Web站",
                "mileage": "ZDK1+200",
                "location_note": "站台",
                "direction": "CW",
            },
        )

    assert response.status_code == 202
    job = service.process_adapter.jobs[response.json()["task_id"]]  # type: ignore[attr-defined]
    assert job.task_type == "fit_ap_metadata_save"
    assert job.params["metadata"] == {
        "ap_uuid": "ap-online",
        "ap_name": "AP-Online",
        "site_name": "Web站",
        "mileage": "1200",
        "location_note": "站台",
        "direction": "上行",
    }


def test_ac_task_dto_sanitizes_legacy_web_export_paths(tmp_path: Path) -> None:
    paths, _db_path, _files = build_ac_management_fixture(tmp_path)
    service, _normal, _export, tasks = _service(paths)
    started = service.start_extension_export("demo")
    repository = tasks.repository("demo")
    snapshot = repository.get(started.task_id)
    assert snapshot is not None
    leak = str(tmp_path / "legacy-ac-report.xlsx")
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
            event_id="legacy-ac-web-export-path-event",
            task_id=started.task_id,
            type="finished",
            time=now,
            source="worker",
            payload={},
        ),
    )

    serialized = json.dumps(service.get_task("demo", started.task_id).model_dump(mode="json"), ensure_ascii=False)

    assert leak not in serialized
    assert "output_path" not in serialized
    assert "<redacted-path>" in serialized


def test_ac_task_dto_redacts_non_export_paths_and_secrets(tmp_path: Path) -> None:
    paths, _db_path, _files = build_ac_management_fixture(tmp_path)
    service, _normal, _export, tasks = _service(paths)
    started = service.start_local_rebuild("demo", "ac_overview_refresh", ac_id="")
    repository = tasks.repository("demo")
    snapshot = repository.get(started.task_id)
    assert snapshot is not None
    leak = str(tmp_path / "ac-rebuild.json")
    now = utc_now_iso()
    repository.record(
        replace(
            snapshot,
            status=TaskState.FAILED,
            finished_time=now,
            updated_time=now,
            message=f"读取失败：{leak}",
            error_message="token=ac-secret Bearer bearer-secret",
        ),
        TaskEvent(
            event_id="legacy-ac-local-path-event",
            task_id=started.task_id,
            type="failed",
            time=now,
            source="worker",
            payload={},
        ),
    )

    serialized = json.dumps(service.get_task("demo", started.task_id).model_dump(mode="json"), ensure_ascii=False)

    assert leak not in serialized
    assert "ac-secret" not in serialized
    assert "bearer-secret" not in serialized
    assert "<redacted-path>" in serialized
    assert "token=<redacted>" in serialized
    assert "Bearer <redacted>" in serialized


def test_fine_grained_feature_gates_block_child_actions_independently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _service_instance = _client(tmp_path, monkeypatch)
    with client:
        client.app.state.feature_gate.features["capability.ac.dangerous_actions"].update(visible=False, enabled=False, client_package=False)
        blocked_action = client.post(
            "/api/ac-management/actions/plans", json={"target_id": "ac-1", "action_id": "persist_auto_ap"}
        )
        client.app.state.feature_gate.features["capability.ac.extensions.preview"].update(visible=False, enabled=False, client_package=False)
        blocked_preview = client.post(
            "/api/ac-management/extensions/import-preview",
            files={"file": ("extensions.csv", CSV_CONTENT, "text/csv")},
        )
        client.app.state.feature_gate.features["capability.ac.refresh"].update(visible=False, enabled=False, client_package=False)
        blocked_refresh = client.post("/api/ac-management/local-rebuild/optical", json={"ac_id": "ac-1"})
        blocked_task_recovery = client.post("/api/ac-management/web-tasks/recover")
        blocked_export_without_task_control = client.post("/api/ac-management/extensions/export")
        client.app.state.feature_gate.features["capability.ac.extensions.apply"].update(visible=False, enabled=False, client_package=False)
        blocked_apply = client.post(
            "/api/ac-management/extensions/import-apply",
            json={"preview_id": "missing", "preview_digest": "missing", "explicit_confirmation": True},
        )
        client.app.state.feature_gate.features["capability.ac.extensions.rollback"].update(visible=False, enabled=False, client_package=False)
        blocked_rollback = client.post(
            "/api/ac-management/extensions/audits/missing/rollback",
            json={"explicit_confirmation": True},
        )
        client.app.state.feature_gate.features["capability.ac.extensions.export"].update(visible=False, enabled=False, client_package=False)
        client.app.state.feature_gate.features["capability.ac.refresh"].update(visible=True, enabled=True, client_package=True)
        blocked_export = client.post("/api/ac-management/extensions/export")
        readable = client.get("/api/ac-management/extensions")

    assert blocked_action.status_code == 404
    assert blocked_preview.status_code == 404
    assert blocked_refresh.status_code == 404
    assert blocked_task_recovery.status_code == 404
    assert blocked_export_without_task_control.status_code == 404
    assert blocked_apply.status_code == 404
    assert blocked_rollback.status_code == 404
    assert blocked_export.status_code == 404
    assert readable.status_code == 200
