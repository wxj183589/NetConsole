from __future__ import annotations

import hashlib

from pathlib import Path

import pytest

from tests.support.ac_management_web_fixture import build_ac_management_fixture

from tests.support.rail_transit_base_data_fixture import mark_base_data_copy

from tests.support.job_process_test_support import FakeExportProcessAdapter, FakeLocalProcessAdapter

from netconsole.application.ac.web_application_service import AcWebActionError, AcWebApplicationService

from netconsole.application.web_export_process_adapter import WebExportProcessAdapter

from netconsole.core.database import Database

from netconsole.models.device import Device

from netconsole.repositories.ac_repository import AcRepository

from netconsole.repositories.device_repository import DeviceRepository

from netconsole.services.job_center.handlers.legacy_tasks import run_background_task

from netconsole.services.job_center.task_application_service import TaskApplicationService

from netconsole.services.rail_transit.base_data_import_service import RailTransitBaseDataImportService

from netconsole.services.rail_transit.base_data_query_service import RailTransitBaseDataQueryService

from netconsole.services.rail_transit.base_data_write_guard import BaseDataWriteGuard

from netconsole.services.rail_transit.import_preview_service import RailTransitImportPreviewService

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


def test_fit_ap_resource_export_service_uses_scoped_snapshot_inputs(tmp_path: Path) -> None:
    paths, _db_path, _files = build_ac_management_fixture(tmp_path)
    service, _normal, export, _tasks = _service(paths)

    filtered = service.start_fit_ap_resource_export(
        "demo",
        ac_id="ac-1",
        scope="filtered",
        selected_ap_ids=[],
        filters={"status": "offline", "query": "", "unknown": "ignored"},
    )
    payload = export.jobs[filtered.task_id].params["payload"]
    assert payload["scope"] == "filtered"
    assert payload["filters"] == {"status": "offline"}
    assert payload["selected_ap_ids"] == []

    selected = service.start_fit_ap_resource_export(
        "demo",
        ac_id="ac-1",
        scope="selected",
        selected_ap_ids=["ap-online", "ap-offline"],
        filters={"status": "offline"},
    )
    selected_payload = export.jobs[selected.task_id].params["payload"]
    assert selected_payload["filters"] == {}
    assert selected_payload["selected_ap_ids"] == ["ap-online", "ap-offline"]

    with pytest.raises(AcWebActionError, match="请先选择"):
        service.start_fit_ap_resource_export(
            "demo",
            ac_id="ac-1",
            scope="selected",
            selected_ap_ids=[],
        )
    with pytest.raises(AcWebActionError, match="不属于当前 AC"):
        service.start_fit_ap_resource_export(
            "demo",
            ac_id="ac-1",
            scope="selected",
            selected_ap_ids=["foreign-ap"],
        )
    with pytest.raises(AcWebActionError, match="没有可导出"):
        service.start_fit_ap_resource_export(
            "demo",
            ac_id="ac-1",
            scope="filtered",
            selected_ap_ids=[],
            filters={"query": "missing-ap"},
        )


def test_ac_omnipeek_preview_and_export_are_scoped_to_current_ac_selection(tmp_path: Path) -> None:
    paths, _db_path, _files = build_ac_management_fixture(tmp_path)
    service, normal, export, _tasks = _service(paths)
    repository = AcRepository(Database(paths.site_db_path("demo")))
    repository.upsert_ap_extension_point(
        {"ap_name": "AP-Online", "ap_mac_display": "0000-0000-0001", "station_name": "车站A"}
    )
    repository.upsert_ap_extension_point(
        {"ap_name": "Other-AC-AP", "ap_mac_display": "0000-0000-00ff", "station_name": "其他局点"}
    )
    DeviceRepository(Database(paths.site_db_path("demo"))).create(
        Device(
            name="列车01-MR-A",
            system_name="列车01-MR-A",
            device_type="Cloud-AP",
            mac_address="74ad-cb9d-3320",
        )
    )

    preview = service.start_omnipeek_preview("demo", ac_id="ac-1", ap_ids=["ap-online"])
    preview_job = normal.jobs[preview.task_id]
    assert preview_job.params["selected_fit_ap_ids"] == ["ap-online"]
    assert preview_job.params["include_device_mr"] is False
    result = run_background_task(preview_job, should_cancel=lambda: False)
    assert result["source_counts"]["AP扩展信息"] == 1
    assert all(item["name"] != "Other-AC-AP" for item in result["items"])
    normal.complete(preview.task_id, result)
    ready = service.get_omnipeek_preview("demo", preview.task_id)

    assert ready.ready is True
    assert ready.input_ap_count == 1
    assert ready.exportable_entry_count > 0
    assert ready.error_count == 0
    assert ready.items
    assert ready.items[0].item_key
    assert ready.items[0].group
    assert ready.items[0].color

    mr_preview = service.start_omnipeek_preview(
        "demo",
        ac_id="ac-1",
        ap_ids=[],
        options={
            "line_name": "测试线路",
            "include_ac_fit_ap": False,
            "include_ap_extensions": False,
            "include_device_mr": True,
            "onboard_radio_mode": "r1_only",
        },
    )
    mr_result = run_background_task(normal.jobs[mr_preview.task_id], should_cancel=lambda: False)
    normal.complete(mr_preview.task_id, mr_result)
    mr_ready = service.get_omnipeek_preview("demo", mr_preview.task_id, status_filter="all", search="列车01")
    assert mr_ready.config["line_name"] == "测试线路"
    assert mr_ready.config["include_device_mr"] is True
    assert mr_ready.source_counts["设备管理"] == 1
    assert mr_ready.total == 1
    assert mr_ready.items[0].type_label == "车载MR"

    all_preview = service.start_omnipeek_preview("demo", ac_id="ac-1", ap_ids=[])
    all_result = run_background_task(normal.jobs[all_preview.task_id], should_cancel=lambda: False)
    assert all_result["source_counts"]["AC FIT-AP资源"] == 3
    assert all_result["source_counts"]["AP扩展信息"] == 1
    assert all(item["name"] != "Other-AC-AP" for item in all_result["items"])
    normal.complete(all_preview.task_id, all_result)

    started = service.start_omnipeek_export("demo", ac_id="ac-1", ap_ids=["ap-online"])
    export_job = export.jobs[started.task_id]
    assert export_job.site_name == "demo"
    assert export_job.params["payload"]["source"] == {
        "ac_uuid": "ac-1",
        "selected_fit_ap_ids": ["ap-online"],
        "selected_device_uuids": [],
        "scope_extensions_to_fit_ap": True,
    }
    assert export_job.params["payload"]["config"]["include_device_mr"] is False
    output = export.complete(started.task_id, b'<NameTable Version="3.0"></NameTable>')
    opened, _name = service.open_omnipeek_export("demo", started.artifact_id)
    assert opened == output

    with pytest.raises(AcWebActionError) as foreign:
        service.start_omnipeek_preview("demo", ac_id="ac-1", ap_ids=["not-current-ac"])
    assert foreign.value.code == "AP_TARGET_NOT_AUTHORIZED"


def test_ac_omnipeek_export_runs_shared_process_and_keeps_log(tmp_path: Path) -> None:
    paths, _db_path, _files = build_ac_management_fixture(tmp_path)
    service, _normal, _fake_export, tasks = _service(paths)
    adapter = WebExportProcessAdapter(tasks)
    service.export_adapter = adapter
    try:
        started = service.start_omnipeek_export(
            "demo", ac_id="ac-1", ap_ids=["ap-online"]
        )
        assert adapter.wait(started.task_id, timeout=30)
        path, name = service.open_omnipeek_export("demo", started.artifact_id)
    finally:
        adapter.shutdown()

    content = path.read_text(encoding="utf-8")
    log_path = path.with_name(f"{path.stem}_导出日志.txt")
    assert name.endswith("名称表.nam")
    assert '<NameTable Version="3.0">' in content
    assert "00:00:00:00:00:01" in content
    assert "00:00:00:00:00:02" not in content
    assert log_path.is_file()
    assert "AC FIT-AP资源：1 条" in log_path.read_text(encoding="utf-8")


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
