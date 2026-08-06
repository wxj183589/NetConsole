from __future__ import annotations

import gzip
import sqlite3
from pathlib import Path

from netconsole.core.paths import PathResolver
from netconsole.application.rail_transit.web_application_service import RailTransitWebApplicationService
from netconsole.services.mesh_local_scan_service import MeshLocalScanService
from netconsole.services.mesh_storage_service import MeshStorageService


LINE_ACTIVE = (
    "[1] Active 30f5-277a-5a2f 2026/08/03 10:12:30 0d 00h 00m 03s 1 "
    "36/43 2%/4% 45%/47% 3/1 15/27 60/72060 88/105 0/5000 2/297 "
    "314/0 0/93 0/0 0/0 0/0"
)


def _log(timestamp: str) -> bytes:
    return (f"[1] {timestamp} (3)\n{LINE_ACTIVE}\n").encode()


def _paths(tmp_path: Path) -> PathResolver:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    paths.site_dir("demo").mkdir(parents=True, exist_ok=True)
    return paths


def test_local_scan_is_recursive_site_scoped_and_content_based(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    profile = MeshStorageService("demo", paths).create_mr_profile("列车07-MR-CT")
    raw = paths.mesh_mr_raw_dir("demo", profile.safe_folder_name)
    first = raw / "列车07-MR-CT-2026_08_03_1meshlog.log.gz"
    nested = raw / "2026" / "renamed.log.gz"
    different = raw / "2026" / "same-name.log"
    nested.parent.mkdir(parents=True)
    body = _log("2026/08/03 10:12:33.579")
    first.write_bytes(gzip.compress(body, mtime=1))
    nested.write_bytes(first.read_bytes())
    different.write_bytes(_log("2026/08/04 10:12:33.579"))
    (raw / "writing.log.gz.part").write_bytes(b"partial")
    (raw / "ignored.tmp").write_bytes(b"temporary")
    (raw / "broken.log.gz").write_bytes(b"not-gzip")
    other = paths.mesh_mr_raw_dir("other-site", profile.safe_folder_name)
    other.mkdir(parents=True)
    (other / "other.log").write_bytes(body)

    service = MeshLocalScanService("demo", paths)
    scan = service.scan(service.create_scan_id())
    result = service.get_scan(str(scan["scan_id"]))

    assert result["stats"] == {
        "found_count": 4,
        "unregistered_count": 2,
        "imported_count": 0,
        "duplicate_count": 1,
        "invalid_count": 1,
        "needs_metadata_count": 0,
        "failed_count": 0,
        "waiting_repair_count": 0,
        "repairing_count": 0,
        "queued_count": 0,
        "parsing_count": 0,
        "repair_failed_count": 0,
        "parse_failed_count": 0,
        "ignored_count": 0,
    }
    rows = {item["file_name"]: item for item in result["candidates"]}
    assert rows[first.name]["scan_status"] == "unregistered"
    assert rows[nested.name]["scan_status"] == "duplicate"
    assert rows[different.name]["scan_status"] == "unregistered"
    assert rows["broken.log.gz"]["scan_status"] == "invalid"
    assert "GZIP 文件损坏" in rows["broken.log.gz"]["error_message"]
    assert all("other-site" not in item["relative_path"] for item in result["candidates"])


def test_local_scan_import_reuses_managed_raw_and_records_provenance(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    profile = MeshStorageService("demo", paths).create_mr_profile("列车07-MR-CT")
    raw = paths.mesh_mr_raw_dir("demo", profile.safe_folder_name)
    source = raw / "2026" / "manual-copy.log"
    source.parent.mkdir(parents=True)
    source.write_bytes(_log("2026/08/03 10:12:33.579"))
    service = MeshLocalScanService("demo", paths)
    scan_id = service.create_scan_id()
    service.scan(scan_id)
    candidate = service.get_scan(scan_id)["candidates"][0]

    result = service.import_candidates(
        scan_id,
        [{"candidate_id": candidate["candidate_id"], "profile_id": profile.mr_id}],
        job_id="mesh-local-import-test",
    )

    assert result["imported_count"] == 1
    assert result["failed_count"] == 0
    assert source.is_file()
    with sqlite3.connect(paths.mesh_mr_db_path("demo", profile.safe_folder_name)) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute("SELECT * FROM source_files").fetchone()
    assert row is not None
    assert row["archived_path"] == str(source.resolve())
    assert row["source_type"] == "local_scan"
    assert row["parse_task_id"] == "mesh-local-import-test"
    with sqlite3.connect(paths.mesh_catalog_path("demo")) as connection:
        indexed = connection.execute(
            "SELECT source_type FROM mesh_session_index WHERE session_id = ?",
            (result["created_session_ids"][0],),
        ).fetchone()
    assert indexed == ("local_scan",)

    renamed = source.with_name("renamed-after-import.log")
    source.rename(renamed)
    next_scan = service.create_scan_id()
    service.scan(next_scan)
    duplicate = service.get_scan(next_scan)["candidates"][0]
    assert duplicate["scan_status"] == "duplicate"
    assert duplicate["existing_session_id"] == result["created_session_ids"][0]


def test_local_scan_ignored_candidate_cannot_be_imported(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    profile = MeshStorageService("demo", paths).create_mr_profile("列车07-MR-CT")
    source = paths.mesh_mr_raw_dir("demo", profile.safe_folder_name) / "ignored.log"
    source.write_bytes(_log("2026/08/03 10:12:33.579"))
    service = MeshLocalScanService("demo", paths)
    scan_id = service.create_scan_id()
    service.scan(scan_id)
    candidate_id = service.get_scan(scan_id)["candidates"][0]["candidate_id"]
    service.ignore_candidates(scan_id, [candidate_id])

    result = service.import_candidates(
        scan_id,
        [{"candidate_id": candidate_id, "profile_id": profile.mr_id}],
        job_id="mesh-local-import-ignored",
    )

    assert result["imported_count"] == 0
    assert result["failed_count"] == 1
    assert "不可导入" in result["failed_files"][0]["error"]


def test_local_scan_jobs_are_visible_to_rail_task_polling() -> None:
    assert {"mesh_local_scan", "mesh_local_scan_import"} <= RailTransitWebApplicationService._ALLOWED_TASK_TYPES
    assert RailTransitWebApplicationService._result_summary(
        "mesh_local_scan",
        {"scan_id": "mls1_" + "a" * 32},
    ) == {"scan_id": "mls1_" + "a" * 32}
