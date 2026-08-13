from __future__ import annotations


import io

from pathlib import Path

import pytest

from tests.support.mesh_analysis_test_support import (
    EmptyBaseQuery,
    create_mesh_analysis_fixture,
)

from tests.support.job_process_test_support import FakeExportProcessAdapter, FakeLocalProcessAdapter

from netconsole.application.rail_transit.web_application_service import (
    RailTransitWebApplicationService,
    RailTransitWebError,
)

from netconsole.application.web_export_process_adapter import WebExportProcessAdapter

from netconsole.core.paths import PathResolver

from netconsole.models.mesh_analysis_params import MeshAnalysisParams

from netconsole.services.job_center.task_application_service import (
    TaskApplicationService,
)

from netconsole.services.online_mr.query_service import OnlineMrQueryService

from netconsole.services.rail_transit.mesh_analysis_query_service import (
    MeshAnalysisQueryService,
)

from netconsole.services.mesh_storage_service import MeshStorageService

from netconsole.services.mesh_analysis_params_service import save_site_mesh_analysis_params

from netconsole.services.rail_transit.mesh_ap_location_service import MeshApLocationSnapshot

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
