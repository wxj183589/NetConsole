from __future__ import annotations

import json

from concurrent.futures import ThreadPoolExecutor

from dataclasses import replace

from pathlib import Path

import pytest

from fastapi.testclient import TestClient

from tests.support.ac_management_web_fixture import build_ac_management_fixture

from tests.support.rail_transit_base_data_fixture import mark_base_data_copy

from tests.support.job_process_test_support import FakeExportProcessAdapter, FakeLocalProcessAdapter

from netconsole.application.ac.web_application_service import AcWebActionError, AcWebApplicationService

from netconsole.backend.api.main import create_app

from netconsole.core.database import Database

from netconsole.core.runtime_mode import RuntimeMode

from netconsole.core.sites import SiteManager

from netconsole.models.api.ac_management import AcLocalRebuildRequestDTO, AcRefreshRequestDTO

from netconsole.models.task_state import TaskState

from netconsole.repositories.ac_repository import AcRepository

from netconsole.repositories.device_repository import DeviceRepository

from netconsole.services.job_center.handlers.ac_jobs import ac_fit_ap_delete_many, fit_ap_metadata_import

from netconsole.services.job_center.handlers.device_jobs import fit_ap_metadata_save

from netconsole.services.job_center.job_context import JobContext

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


def test_ac_web_result_summary_preserves_partial_component_ledger() -> None:
    summary = AcWebApplicationService._result_summary(
        {
            "success": False,
            "business_outcome": "PARTIAL_SUCCESS",
            "partial_success": True,
            "persisted_components": ["AC_BASIC"],
            "failed_components": ["DEVICE_DETAIL"],
            "skipped_components": ["RADIO"],
            "collection": {
                "success": False,
                "business_outcome": "PARTIAL_SUCCESS",
                "partial_success": True,
                "persisted_components": ["AC_BASIC"],
                "failed_components": ["DEVICE_DETAIL"],
                "skipped_components": ["RADIO"],
                "error_message": "collector failed",
            },
        }
    )

    assert summary["business_outcome"] == "PARTIAL_SUCCESS"
    assert summary["partial_success"] is True
    assert summary["persisted_components"] == ["AC_BASIC"]
    assert summary["failed_components"] == ["DEVICE_DETAIL"]
    assert summary["skipped_components"] == ["RADIO"]
    assert summary["collection"]["business_outcome"] == "PARTIAL_SUCCESS"
    assert summary["collection"]["persisted_components"] == ["AC_BASIC"]

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


def test_real_repository_rows_map_to_strict_extension_dtos_without_duplicate_plan_api(
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
    with client:
        extensions = client.get("/api/ac-management/extensions")
        trackside = client.get("/api/ac-management/trackside-plan")

    assert extensions.status_code == 200
    assert extensions.json()["items"][0]["ap_name"] == "AP-Real"
    assert "source_file" not in extensions.json()["items"][0]
    assert trackside.status_code == 404


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


def test_action_plan_persists_revalidates_target_and_starts_real_fixed_command_task(tmp_path: Path) -> None:
    paths, _db_path, _files = build_ac_management_fixture(tmp_path)
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.app_config_path.write_text('{"current_site":"demo"}', encoding="utf-8")
    service, _normal, _export, tasks = _service(paths)
    plan = service.create_action_plan("demo", "ac-1", "persist_auto_ap")
    assert plan.command_summary == ["system-view", "wlan auto-ap persistent all", "save force", "return", "quit"]
    with pytest.raises(AcWebActionError) as unsupported:
        service.create_action_plan("demo", "ac-1", "save_config")
    assert unsupported.value.code == "ACTION_NOT_ALLOWED"

    restarted, normal, _export2, _tasks2 = _service(paths, tasks)
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

    valid = restarted.create_action_plan("demo", "ac-1", "enable_ap_remote_login")
    restarted.confirm_action_plan("demo", valid.plan_id, valid.plan_digest, valid.confirm_token)
    executed = restarted.execute_action_plan("demo", valid.plan_id)
    job = normal.jobs[executed.task_id]
    snapshot = tasks.repository("demo").get(executed.task_id)
    assert executed.status == "EXECUTING"
    assert job.task_type == "ac_command_action_execute"
    assert job.params["action"] == "enable_ap_remote_login"
    assert job.params["command_sequence"] == list(executed.command_summary)
    assert job.params["resource_keys"] == ["demo:ac-1:ac_config_write"]
    assert snapshot is not None and snapshot.source == "local" and snapshot.owner == "web_ac"
    normal.complete(
        executed.task_id,
        {
            "success": True,
            "action": "enable_ap_remote_login",
            "commands": list(executed.command_summary),
            "command_results": [{"command": command, "success": True} for command in executed.command_summary],
            "collect_run_uuid": "run-action-1",
        },
    )
    assert restarted.preview_action_plan("demo", valid.plan_id).status == "COMPLETED"
    audit = restarted.action_audit("demo", valid.plan_id)
    assert audit["executor"] == "LOCAL"
    assert audit["real_device_task"] is True
    assert audit["result_summary"]["success"] is True
    with pytest.raises(AcWebActionError):
        restarted.execute_action_plan("demo", valid.plan_id)

    cancel_plan = restarted.create_action_plan("demo", "ac-1", "persist_auto_ap")
    restarted.confirm_action_plan("demo", cancel_plan.plan_id, cancel_plan.plan_digest, cancel_plan.confirm_token)
    cancelling = restarted.execute_action_plan("demo", cancel_plan.plan_id)
    restarted.cancel_task("demo", cancelling.task_id)
    assert restarted.preview_action_plan("demo", cancel_plan.plan_id).status == "CANCELLED"
    SiteManager(paths).init_site_database("other")
    with pytest.raises(AcWebActionError) as crossed:
        restarted.preview_action_plan("other", valid.plan_id)
    assert crossed.value.code == "PLAN_SITE_MISMATCH"

    tampered = restarted.create_action_plan("demo", "ac-1", "persist_auto_ap")
    tampered_path = restarted._plan_path(tampered.plan_id)
    tampered_payload = json.loads(tampered_path.read_text(encoding="utf-8"))
    tampered_payload["commands"] = ["display current-configuration"]
    tampered_path.write_text(json.dumps(tampered_payload), encoding="utf-8")
    with pytest.raises(AcWebActionError) as altered_plan:
        restarted.confirm_action_plan(
            "demo", tampered.plan_id, tampered.plan_digest, tampered.confirm_token
        )
    assert altered_plan.value.code == "PLAN_TAMPERED"

    expired = restarted.create_action_plan("demo", "ac-1", "persist_auto_ap")
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

    assert set(AcRefreshRequestDTO.model_fields) == {"ac_id", "ap_id"}
    started = service.start_refresh("demo", "fit-ap", ac_id="ac-1")
    job = normal.jobs[started.task_id]

    assert job.task_type == "ac_fit_ap_resources_refresh"
    assert job.params["mode"] == "collect"
    assert job.params["source"] == "cli"
    assert job.params["device_uuid"] == "ac-1"
    assert started.status == "RUNNING"
    normal.complete(started.task_id)

    ac_started = service.start_refresh("demo", "ac", ac_id="ac-1")
    assert normal.jobs[ac_started.task_id].task_type == "ac_info_refresh"
    normal.complete(ac_started.task_id)

    detail_started = service.start_refresh("demo", "ap-detail", ac_id="ac-1", ap_id="ap-online")
    detail_job = normal.jobs[detail_started.task_id]
    assert detail_job.task_type == "ac_fit_ap_detail_refresh"
    assert detail_job.params["ap_uuid"] == "ap-online"
    normal.complete(detail_started.task_id)

    optical_started = service.start_refresh("demo", "optical", ac_id="ac-1")
    optical_job = normal.jobs[optical_started.task_id]
    assert optical_job.task_type == "ac_fit_ap_optical_refresh"
    assert optical_job.params["mode"] == "collect"
    assert optical_job.params["source"] == "auto"
    assert optical_job.params["refresh_scope"] == "all"

    with pytest.raises(AcWebActionError) as wrong_ap:
        service.start_refresh("demo", "ap-detail", ac_id="ac-1", ap_id="missing-ap")
    assert wrong_ap.value.code == "AP_TARGET_NOT_AUTHORIZED"


def test_fit_ap_batch_delete_requires_confirmation_and_scopes_every_ap_to_selected_ac(tmp_path: Path) -> None:
    paths, _db_path, _files = build_ac_management_fixture(tmp_path)
    service, normal, _export, _tasks = _service(paths)

    with pytest.raises(AcWebActionError) as unconfirmed:
        service.start_fit_ap_delete("demo", ac_id="ac-1", ap_ids=["ap-online"], explicit_confirmation=False)
    assert unconfirmed.value.code == "CONFIRMATION_REQUIRED"
    with pytest.raises(AcWebActionError) as foreign:
        service.start_fit_ap_delete("demo", ac_id="ac-1", ap_ids=["missing-ap"], explicit_confirmation=True)
    assert foreign.value.code == "AP_TARGET_NOT_AUTHORIZED"

    started = service.start_fit_ap_delete(
        "demo",
        ac_id="ac-1",
        ap_ids=["ap-online", "ap-online"],
        explicit_confirmation=True,
    )
    job = normal.jobs[started.task_id]
    assert job.task_type == "ac_fit_ap_delete_many"
    assert job.params["ap_uuids"] == ["ap-online"]
    progress: list[tuple[str, int, int, str]] = []
    result = ac_fit_ap_delete_many(
        JobContext(
            job.job_id,
            job.task_type,
            job.params,
            lambda stage, current, total, message: progress.append((stage, current, total, message)),
            lambda: False,
            paths,
        )
    )

    assert result == {"count": 1}
    assert progress[-1][1:3] == (1, 1)
    assert AcRepository(Database(paths.site_db_path("demo"))).get_fit_ap_resource_by_uuid("ac-1", "ap-online") is None


def test_fit_ap_metadata_upload_runs_existing_import_job_and_cleans_staging_file(tmp_path: Path) -> None:
    paths, _db_path, _files = build_ac_management_fixture(tmp_path)
    service, normal, _export, _tasks = _service(paths)
    repository = AcRepository(Database(paths.site_db_path("demo")))
    ap = repository.get_fit_ap_resource_by_uuid("ac-1", "ap-online")
    assert ap is not None and ap["ap_mac"]
    repository.upsert_fit_ap_resource("ac-1", ap)
    content = (
        "AP名称,AP_MAC,归属站点,里程,点位说明,方向\n"
        f"{ap['ap_name']},{ap['ap_mac']},Web站,ZDK1+200,站台,上行\n"
    ).encode("utf-8-sig")

    with pytest.raises(AcWebActionError) as invalid_type:
        service.start_fit_ap_metadata_import("demo", file_name="metadata.txt", content=content)
    assert invalid_type.value.code == "IMPORT_TYPE_INVALID"
    started = service.start_fit_ap_metadata_import("demo", file_name="metadata.csv", content=content)
    job = normal.jobs[started.task_id]
    input_path = Path(str(job.params["path"]))
    assert input_path.is_file()
    result = fit_ap_metadata_import(JobContext(job.job_id, job.task_type, job.params, None, lambda: False, paths))
    normal.complete(job.job_id, result)

    assert result["updated"] == 1
    assert result["skipped"] == 0
    assert not input_path.exists()
    updated = repository.get_fit_ap_resource_by_uuid("ac-1", "ap-online")
    assert updated is not None and updated["site_name"] == "Web站"


def test_fit_ap_metadata_save_validates_ac_scope_and_persists_through_job(tmp_path: Path) -> None:
    paths, _db_path, _files = build_ac_management_fixture(tmp_path)
    service, normal, _export, _tasks = _service(paths)
    with pytest.raises(AcWebActionError) as foreign:
        service.start_fit_ap_metadata_save(
            "demo",
            ac_id="ac-1",
            ap_id="missing-ap",
            metadata={},
        )
    assert foreign.value.code == "AP_TARGET_NOT_AUTHORIZED"

    started = service.start_fit_ap_metadata_save(
        "demo",
        ac_id="ac-1",
        ap_id="ap-online",
        metadata={"site_name": "Web站", "mileage": "ZDK1+200", "location_note": "站台", "direction": "CW"},
    )
    job = normal.jobs[started.task_id]
    result = fit_ap_metadata_save(JobContext(job.job_id, job.task_type, job.params, None, lambda: False, paths))
    normal.complete(job.job_id, result)

    metadata = AcRepository(Database(paths.site_db_path("demo"))).get_fit_ap_metadata_by_uuid("ap-online")
    assert result["metadata"]["ap_uuid"] == "ap-online"
    assert metadata is not None
    assert metadata["site_name"] == "Web站"
    assert metadata["mileage"] == "1200"
    assert metadata["location_note"] == "站台"
    assert metadata["direction"] == "上行"
