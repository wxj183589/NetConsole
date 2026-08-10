from __future__ import annotations

import sqlite3
from pathlib import Path

from netconsole.core.paths import PathResolver
from netconsole.services.background_job import BackgroundJob
from netconsole.repositories.mesh_mr_repository import MeshMrRepository, SCHEMA_VERSION
from netconsole.services.job_center.handlers.mesh_jobs import mesh_derived_data_repair
from netconsole.services.job_center.job_context import JobContext
from netconsole.services.mesh_derived_data_maintenance_service import (
    MeshDerivedDataMaintenanceService,
    MeshRepairMode,
)
from netconsole.services.mesh_local_scan_service import MeshLocalScanService
from netconsole.services.mesh_storage_service import MeshStorageService


LINE = (
    "[1] Active 30f5-277a-5a2f 2026/08/03 10:12:30 0d 00h 00m 03s 1 "
    "36/43 2%/4% 45%/47% 3/1 15/27 60/72060 88/105 0/5000 2/297 "
    "314/0 0/93 0/0 0/0 0/0"
)


def _paths(tmp_path: Path) -> PathResolver:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    paths.site_dir("demo").mkdir(parents=True, exist_ok=True)
    return paths


def _make_old_empty_index(paths: PathResolver, profile) -> Path:
    index = paths.mesh_mr_db_path("demo", profile.safe_folder_name)
    MeshMrRepository(index)
    with sqlite3.connect(index) as connection:
        connection.execute("UPDATE schema_meta SET value = 'old' WHERE key = 'schema_version'")
        connection.execute("UPDATE meta SET value = 'old' WHERE key = 'schema_version'")
    return index


def test_profiles_without_sources_do_not_block_empty_database_recreate(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    storage = MeshStorageService("demo", paths)
    profiles = [storage.create_mr_profile(f"列车{index:02d}-MR-{role}") for index in range(1, 19) for role in ("CT", "CW")]
    selected = next(item for item in profiles if item.display_name == "列车07-MR-CT")
    index = _make_old_empty_index(paths, selected)
    raw = paths.mesh_mr_raw_dir("demo", selected.safe_folder_name) / "列车07-MR-CT-2026_08_03_1meshlog.log"
    raw.write_text("[1] 2026/08/03 10:12:33.579 (3)\n" + LINE + "\n", encoding="utf-8")

    inspection = MeshDerivedDataMaintenanceService(paths).inspect("demo")

    assert inspection["repair_mode"] == MeshRepairMode.EMPTY_DATABASE_RECREATE.value
    assert len(inspection["profiles"]) == 36
    assert len(inspection["incompatible_profiles"]) == 1
    assert inspection["incompatible_profiles"][0]["registered_source_count"] == 0

    result = MeshDerivedDataMaintenanceService(paths).repair("demo")

    assert result["repair_mode"] == MeshRepairMode.EMPTY_DATABASE_RECREATE.value
    assert raw.is_file()
    assert MeshMrRepository(index).list_source_files() == []
    assert MeshDerivedDataMaintenanceService(paths).inspect("demo")["compatible"] is True


def test_empty_recreate_resumes_selected_local_scan_candidate(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    storage = MeshStorageService("demo", paths)
    profiles = [storage.create_mr_profile(f"列车{index:02d}-MR-{role}") for index in range(1, 19) for role in ("CT", "CW")]
    selected = next(item for item in profiles if item.display_name == "列车07-MR-CT")
    _make_old_empty_index(paths, selected)
    raw = paths.mesh_mr_raw_dir("demo", selected.safe_folder_name) / "列车07-MR-CT-2026_08_03_1meshlog.log"
    raw.write_text("[1] 2026/08/03 10:12:33.579 (3)\n" + LINE + "\n", encoding="utf-8")

    scan_service = MeshLocalScanService("demo", paths)
    scan_id = scan_service.create_scan_id()
    scan_service.scan(scan_id)
    candidate = scan_service.get_scan(scan_id)["candidates"][0]
    maintenance = MeshDerivedDataMaintenanceService(paths)
    operation = maintenance.enqueue_operation(
        "demo",
        kind="mesh_local_scan_import",
        payload={
            "scan_id": scan_id,
            "mappings": [{"candidate_id": candidate["candidate_id"], "profile_id": selected.mr_id}],
        },
    )

    job = BackgroundJob(
        job_id="mesh-derived-repair-test",
        task_type="mesh_derived_data_repair",
        params={
            "site_name": "demo",
            "app_root": str(paths.app_root),
            "data_root": str(paths.data_root),
        },
    )
    result = mesh_derived_data_repair(JobContext.from_job(job))

    assert operation["operation_id"]
    assert result["repair_mode"] == MeshRepairMode.EMPTY_DATABASE_RECREATE.value
    assert result["resumed_count"] == 1
    final = scan_service.get_scan(scan_id)
    assert final["candidates"][0]["scan_status"] == "imported"
    assert len(MeshMrRepository(paths.mesh_mr_db_path("demo", selected.safe_folder_name)).list_source_files()) == 1
