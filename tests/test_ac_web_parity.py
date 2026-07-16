from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ac_management_web_fixture import build_ac_management_fixture
from rail_transit_base_data_fixture import mark_base_data_copy
from web_parity_test_support import FakeExportProcessAdapter, FakeLocalProcessAdapter
from netconsole.application.ac.web_application_service import AcWebActionError, AcWebApplicationService
from netconsole.application.web_export_process_adapter import WebExportProcessAdapter
from netconsole.backend.api.main import create_app
from netconsole.core.database import Database
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.core.sites import SiteManager
from netconsole.models.api.ac_management import AcLocalRebuildRequestDTO, AcRefreshRequestDTO
from netconsole.models.task_snapshot import TaskEvent, utc_now_iso
from netconsole.models.task_state import TaskState
from netconsole.repositories.ac_repository import AcRepository, TRACKSIDE_AP_PLAN_MODE
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.job_center.task_application_service import TaskApplicationService
from netconsole.services.rail_transit.base_data_import_service import RailTransitBaseDataImportService
from netconsole.services.rail_transit.base_data_query_service import RailTransitBaseDataQueryService
from netconsole.services.rail_transit.base_data_write_guard import BaseDataWriteGuard
from netconsole.services.rail_transit.import_preview_service import RailTransitImportPreviewService


AC_FEATURE_IDS = (
    "web.ac_extensions",
    "web.ac_trackside_ap_plan",
    "web.ac_extensions_preview",
    "web.ac_extensions_apply",
    "web.ac_extensions_rollback",
    "web.ac_extensions_export",
    "web.ac_refresh",
    "web.ac_dangerous_actions",
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


def _service(paths, tasks=None):
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


def test_real_repository_rows_map_to_strict_dtos_and_default_unified_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, service = _client(tmp_path, monkeypatch)
    repository = AcRepository(Database(service.paths.site_db_path("demo")))
    repository.upsert_ap_extension_point(
        {
            "ap_name": "AP-Real",
            "ap_mac_display": "0000-0000-00bb",
            "station_name": "车站A",
            "section_name": "A-B 区间",
            "ap_point_code": "EXTRA-FIELD",
            "source_file": "fixture.xlsx",
        }
    )
    repository.replace_trackside_ap_plan_rows(
        TRACKSIDE_AP_PLAN_MODE,
        [{"station_name": "车站A", "ap_count": 8, "ap_start_address": "10.1.0.1", "mask_length": 24}],
    )

    with client:
        extensions = client.get("/api/ac-management/extensions")
        trackside = client.get("/api/ac-management/trackside-plan")

    assert extensions.status_code == 200
    assert extensions.json()["items"][0]["ap_name"] == "AP-Real"
    assert "source_file" not in extensions.json()["items"][0]
    assert trackside.status_code == 200
    assert trackside.json()["mode"] == TRACKSIDE_AP_PLAN_MODE
    assert trackside.json()["items"][0]["ap_start_address"] == "10.1.0.1"


def test_extension_import_is_durable_idempotent_atomic_and_conflict_aware(tmp_path: Path) -> None:
    paths, _db_path, _files = build_ac_management_fixture(tmp_path)
    service, _normal, _export, tasks = _service(paths)
    preview = service.preview_extension("demo", "extensions.csv", CSV_CONTENT, "text/csv")

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda _index: service.apply_extension(
                    "demo", preview.preview_id, preview.preview_digest, True
                ),
                range(2),
            )
        )

    restarted, _normal2, _export2, _tasks2 = _service(paths, tasks)
    repeated = restarted.apply_extension("demo", preview.preview_id, preview.preview_digest, True)
    assert {item.audit_id for item in results} == {preview.preview_id}
    assert repeated.audit_id == preview.preview_id
    assert repeated.status == "APPLIED"

    rollback = restarted.rollback_extension("demo", preview.preview_id, True)
    assert rollback.status == "ROLLED_BACK"
    assert not any(row["ap_name"] == "AP-Web" for row in AcRepository(Database(paths.site_db_path("demo"))).list_ap_extension_points())

    second = restarted.preview_extension("demo", "extensions.csv", CSV_CONTENT.replace(b"00aa", b"00cc"), "text/csv")
    restarted.apply_extension("demo", second.preview_id, second.preview_digest, True)
    repository = AcRepository(Database(paths.site_db_path("demo")))
    row = next(item for item in repository.list_ap_extension_points() if item["ap_name"] == "AP-Web")
    repository.upsert_ap_extension_point({**row, "remark": "later edit"})
    with pytest.raises(AcWebActionError) as exc_info:
        restarted.rollback_extension("demo", second.preview_id, True)
    assert exc_info.value.code == "BASE_DATA_ROLLBACK_CONFLICT"


def test_action_plan_persists_revalidates_site_and_target_and_records_fake_task(tmp_path: Path) -> None:
    paths, _db_path, _files = build_ac_management_fixture(tmp_path)
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.app_config_path.write_text('{"current_site":"demo"}', encoding="utf-8")
    service, _normal, _export, tasks = _service(paths)
    plan = service.create_action_plan("demo", "ac-1", "save_config")
    assert plan.command_summary == ["save force"]

    restarted, _normal2, _export2, _tasks2 = _service(paths, tasks)
    with pytest.raises(AcWebActionError) as altered_request:
        restarted.confirm_action_plan("demo", plan.plan_id, "0" * 64, plan.confirm_token)
    assert altered_request.value.code == "PLAN_TAMPERED"
    confirmed = restarted.confirm_action_plan("demo", plan.plan_id, plan.plan_digest, plan.confirm_token)
    assert confirmed.status == "CONFIRMED"
    with pytest.raises(AcWebActionError, match="已确认"):
        restarted.confirm_action_plan("demo", plan.plan_id, plan.plan_digest, plan.confirm_token)

    target = DeviceRepository(Database(paths.site_db_path("demo"))).get_by_uuid("ac-1")
    assert target is not None
    target.name = "已变更 AC"
    DeviceRepository(Database(paths.site_db_path("demo"))).update(target)
    with pytest.raises(AcWebActionError) as stale:
        restarted.execute_action_plan("demo", plan.plan_id)
    assert stale.value.code == "TARGET_STALE"

    valid = restarted.create_action_plan("demo", "ac-1", "save_config")
    restarted.confirm_action_plan("demo", valid.plan_id, valid.plan_digest, valid.confirm_token)
    executed = restarted.execute_action_plan("demo", valid.plan_id)
    snapshot = tasks.repository("demo").get(executed.task_id)
    assert executed.status == "FAKE_COMPLETED"
    assert snapshot is not None and snapshot.source == "fake"
    assert snapshot.result["real_device_called"] is False
    with pytest.raises(AcWebActionError):
        restarted.execute_action_plan("demo", valid.plan_id)
    SiteManager(paths).init_site_database("other")
    with pytest.raises(AcWebActionError) as crossed:
        restarted.preview_action_plan("other", valid.plan_id)
    assert crossed.value.code == "PLAN_SITE_MISMATCH"

    tampered = restarted.create_action_plan("demo", "ac-1", "save_config")
    tampered_path = restarted._plan_path(tampered.plan_id)
    tampered_payload = json.loads(tampered_path.read_text(encoding="utf-8"))
    tampered_payload["commands"] = ["display current-configuration"]
    tampered_path.write_text(json.dumps(tampered_payload), encoding="utf-8")
    with pytest.raises(AcWebActionError) as altered_plan:
        restarted.confirm_action_plan(
            "demo", tampered.plan_id, tampered.plan_digest, tampered.confirm_token
        )
    assert altered_plan.value.code == "PLAN_TAMPERED"

    expired = restarted.create_action_plan("demo", "ac-1", "save_config")
    expired_path = restarted._plan_path(expired.plan_id)
    expired_payload = json.loads(expired_path.read_text(encoding="utf-8"))
    expired_payload["expires_at"] = 0
    expired_path.write_text(json.dumps(expired_payload), encoding="utf-8")
    with pytest.raises(AcWebActionError) as expired_plan:
        restarted.confirm_action_plan(
            "demo", expired.plan_id, expired.plan_digest, expired.confirm_token
        )
    assert expired_plan.value.code == "PLAN_EXPIRED"


def test_site_escape_is_rejected_before_path_resolution(tmp_path: Path) -> None:
    paths, _db_path, _files = build_ac_management_fixture(tmp_path)
    service, _normal, _export, _tasks = _service(paths)
    for value in (r"..\..\escaped", r"\\server\share", r"C:\escaped"):
        with pytest.raises(AcWebActionError) as exc_info:
            service.list_extensions(value)
        assert exc_info.value.code == "SITE_CONTEXT_INVALID"
    assert not (paths.sites_dir.parent / "escaped").exists()


def test_ac_local_rebuild_validates_target_and_task_recovery_scope(tmp_path: Path) -> None:
    paths, _db_path, _files = build_ac_management_fixture(tmp_path)
    service, normal, _export, tasks = _service(paths)

    assert set(AcLocalRebuildRequestDTO.model_fields) == {"ac_id"}
    with pytest.raises(AcWebActionError) as missing_target:
        service.start_local_rebuild("demo", "ac_fit_ap_optical_refresh", ac_id="missing-ac")
    assert missing_target.value.code == "TARGET_NOT_AUTHORIZED"

    started = service.start_local_rebuild("demo", "ac_fit_ap_optical_refresh", ac_id="ac-1")
    job = normal.jobs[started.task_id]
    assert job.params["ac_uuid"] == "ac-1"
    assert "source" not in job.params
    assert "refresh_scope" not in job.params
    assert "mode" not in job.params
    assert service.get_task("demo", started.task_id).task_id == started.task_id

    snapshot = tasks.repository("demo").get(started.task_id)
    assert snapshot is not None
    normal.jobs.pop(started.task_id)
    normal.callbacks.pop(started.task_id)
    tasks.repository("demo").save(replace(snapshot, owner_pid=2_147_483_000, status=TaskState.RUNNING))
    foreign = tasks.create_external_task(
        task_id="foreign-ac-task",
        task_type="ac_fit_ap_optical_refresh",
        task_name="foreign",
        source="local",
        site_name="demo",
        owner="other-owner",
    )
    tasks.repository("demo").save(replace(foreign, owner_pid=2_147_482_999, status=TaskState.RUNNING))

    recovered = service.recover_tasks("demo")
    assert [item.task_id for item in recovered] == [started.task_id]
    assert recovered[0].status == "FAILED"
    assert tasks.repository("demo").get("foreign-ac-task").status == TaskState.RUNNING
    with pytest.raises(AcWebActionError) as foreign_task:
        service.get_task("demo", "foreign-ac-task")
    assert foreign_task.value.code == "TASK_NOT_FOUND"


def test_fit_ap_refresh_starts_real_collect_job_with_fixed_parameters(tmp_path: Path) -> None:
    paths, _db_path, _files = build_ac_management_fixture(tmp_path)
    service, normal, _export, _tasks = _service(paths)

    assert set(AcRefreshRequestDTO.model_fields) == {"ac_id"}
    started = service.start_refresh("demo", "fit-ap", ac_id="ac-1")
    job = normal.jobs[started.task_id]

    assert job.task_type == "ac_fit_ap_resources_refresh"
    assert job.params["mode"] == "collect"
    assert job.params["source"] == "cli"
    assert job.params["device_uuid"] == "ac-1"
    assert started.status == "RUNNING"


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


def test_ac_extension_export_runs_in_qt_free_process_and_publishes_hash_manifest(tmp_path: Path) -> None:
    paths, _db_path, _files = build_ac_management_fixture(tmp_path)
    service, _normal, _fake_export, tasks = _service(paths)
    AcRepository(Database(paths.site_db_path("demo"))).upsert_ap_extension_point(
        {"ap_name": "AP-Export", "ap_mac_display": "0000-0000-00ee", "station_name": "车站A"}
    )
    adapter = WebExportProcessAdapter(tasks)
    service.export_adapter = adapter
    try:
        started = service.start_extension_export("demo")
        assert adapter.wait(started.task_id, timeout=30)
        path, _name = service.open_extension_export("demo", started.artifact_id)
        metadata = service.artifact_store.task_metadata(
            "demo",
            started.task_id,
            owner="web_ac",
            source_task_types={"ac_extension_export": "web_export_fit_ap_extension_xlsx"},
        )
    finally:
        adapter.shutdown()

    assert path.is_file()
    assert metadata is not None and metadata["completed"] is True
    assert metadata["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    snapshot = tasks.repository("demo").get(started.task_id)
    assert snapshot is not None and snapshot.result_path == ""
    assert "output_path" not in snapshot.result


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
        client.app.state.feature_gate.features["web.ac_dangerous_actions"].update(visible=False, enabled=False, client_package=False)
        blocked_action = client.post(
            "/api/ac-management/actions/plans", json={"target_id": "ac-1", "action_id": "save_config"}
        )
        client.app.state.feature_gate.features["web.ac_extensions_preview"].update(visible=False, enabled=False, client_package=False)
        blocked_preview = client.post(
            "/api/ac-management/extensions/import-preview",
            files={"file": ("extensions.csv", CSV_CONTENT, "text/csv")},
        )
        client.app.state.feature_gate.features["web.ac_refresh"].update(visible=False, enabled=False, client_package=False)
        blocked_refresh = client.post("/api/ac-management/local-rebuild/optical", json={"ac_id": "ac-1"})
        blocked_task_recovery = client.post("/api/ac-management/web-tasks/recover")
        blocked_export_without_task_control = client.post("/api/ac-management/extensions/export")
        client.app.state.feature_gate.features["web.ac_extensions_apply"].update(visible=False, enabled=False, client_package=False)
        blocked_apply = client.post(
            "/api/ac-management/extensions/import-apply",
            json={"preview_id": "missing", "preview_digest": "missing", "explicit_confirmation": True},
        )
        client.app.state.feature_gate.features["web.ac_extensions_rollback"].update(visible=False, enabled=False, client_package=False)
        blocked_rollback = client.post(
            "/api/ac-management/extensions/audits/missing/rollback",
            json={"explicit_confirmation": True},
        )
        client.app.state.feature_gate.features["web.ac_extensions_export"].update(visible=False, enabled=False, client_package=False)
        client.app.state.feature_gate.features["web.ac_refresh"].update(visible=True, enabled=True, client_package=True)
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
