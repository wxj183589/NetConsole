from __future__ import annotations

import gzip
import zipfile
from pathlib import Path

import pytest

from netconsole.core.paths import PathResolver
from netconsole.parsers.mesh_log_parser import inspect_mesh_log_path, parse_log_timestamp_line
from netconsole.repositories.mesh_mr_repository import MeshMrRepository
from netconsole.services.mesh_bundle_import_service import MeshBundleImportError, MeshBundleImportService
from netconsole.services.mesh_import_service import MeshImportService
from netconsole.services.mesh_storage_service import MeshStorageService


LINE_ACTIVE = (
    "[1] Active 30f5-277a-5a2f 2026/07/28 00:18:50 0d 00h 00m 03s 1 "
    "36/43 2%/4% 45%/47% 3/1 15/27 60/72060 88/105 0/5000 2/297 "
    "314/0 0/93 0/0 0/0 0/0"
)


def _log(timestamp: str) -> bytes:
    return (f"[1] {timestamp}\n{LINE_ACTIVE}\n").encode()


def _zip(path: Path, members: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in members.items():
            archive.writestr(name, content)


def test_timestamp_scanner_accepts_supported_forms_and_skips_invalid(tmp_path: Path) -> None:
    for value, expected in (
        ("[1] 2026/07/28 00:18:56.311", "2026-07-28T00:18:56.311000"),
        ("[0001] 2026/07/28 00:18:56.311", "2026-07-28T00:18:56.311000"),
        ("2026/07/28 00:18:56.311", "2026-07-28T00:18:56.311000"),
        ("[1] 2026-07-28 00:18:56.311000", "2026-07-28T00:18:56.311000"),
        ("INFO 2026-07-28 00:18:56.3 WMESH", "2026-07-28T00:18:56.300000"),
    ):
        assert parse_log_timestamp_line(value).isoformat() == expected
    assert parse_log_timestamp_line("[1] 2026/13/45 25:99:99.999") is None

    path = tmp_path / "meshlog.log"
    path.write_bytes(
        b"\xef\xbb\xbf\nMESH LOG\n[1] 2026/13/45 25:99:99.999\n"
        + _log("2026/07/28 00:18:56.311")
    )
    metadata = inspect_mesh_log_path(path)
    assert metadata.first_log_timestamp.isoformat() == "2026-07-28T00:18:56.311000"
    assert metadata.last_log_timestamp.isoformat() == "2026-07-28T00:18:56.311000"
    assert metadata.raw_sha256 != metadata.content_sha256


def test_generic_meshlog_uses_log_date_and_daily_sequence(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    profile = MeshStorageService("demo", paths).create_mr_profile("列车34-MR-CT")
    service = MeshImportService("demo", paths)
    files: list[Path] = []
    for folder, timestamp in (
        ("first", "2026/07/28 00:18:56.311"),
        ("second", "2026/07/28 08:20:15.126"),
        ("third", "2026/07/29 00:03:22.001"),
    ):
        path = tmp_path / folder / "meshlog.log"
        path.parent.mkdir()
        path.write_bytes(_log(timestamp))
        files.append(path)

    for path in files:
        service.import_files(profile, [path])

    repository = MeshMrRepository(paths.mesh_mr_db_path("demo", profile.safe_folder_name))
    rows = repository.list_source_files()
    assert [row["stored_filename"] for row in rows] == [
        "2026_07_28_1meshlog.log",
        "2026_07_28_2meshlog.log",
        "2026_07_29_1meshlog.log",
    ]
    assert [row["daily_sequence"] for row in rows] == [1, 2, 1]
    assert rows[0]["original_filename"] == "meshlog.log"
    assert rows[0]["log_date"] == "2026-07-28"
    assert rows[0]["rename_status"] == "renamed_by_log_date_sequence"
    assert rows[0]["raw_sha256"] == rows[0]["content_sha256"]


def test_sequence_uses_max_existing_value_and_normalized_names_are_stable(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    storage = MeshStorageService("demo", paths)
    profile = storage.create_mr_profile("列车34-MR-CT")
    raw_root = paths.mesh_mr_raw_dir("demo", profile.safe_folder_name)
    existing_dir = raw_root / "2026" / "07"
    existing_dir.mkdir(parents=True)
    for sequence in (1, 2, 4):
        (existing_dir / f"2026_07_28_{sequence}meshlog.log").write_bytes(b"old")
    source = tmp_path / "meshlog.log"
    source.write_bytes(_log("2026/07/28 13:20:16.625"))

    archived = storage.archive_raw_file_with_metadata(
        profile,
        source,
        inspect_mesh_log_path(source).first_log_timestamp,
    )

    assert archived.stored_filename == "2026_07_28_5meshlog.log"
    normalized = tmp_path / "2026_07_28_6meshlog.log"
    normalized.write_bytes(_log("2026/07/28 14:20:16.625"))
    stable = storage.archive_raw_file_with_metadata(
        profile,
        normalized,
        inspect_mesh_log_path(normalized).first_log_timestamp,
    )
    assert stable.stored_filename == "2026_07_28_6meshlog.log"
    assert stable.rename_status == "already_normalized"


def test_recompressed_gzip_duplicate_does_not_consume_sequence(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    profile = MeshStorageService("demo", paths).create_mr_profile("列车34-MR-CT")
    body = _log("2026/07/28 00:18:56.311")
    first = tmp_path / "first" / "meshlog.log.gz"
    second = tmp_path / "second" / "meshlog.log.gz"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_bytes(gzip.compress(body, mtime=1))
    second.write_bytes(gzip.compress(body, mtime=2))

    result = MeshImportService("demo", paths).import_files(profile, [first, second])

    assert result.imported_count == 1
    assert result.duplicate_count == 1
    rows = MeshMrRepository(paths.mesh_mr_db_path("demo", profile.safe_folder_name)).list_source_files()
    assert len(rows) == 1
    assert rows[0]["stored_filename"] == "2026_07_28_1meshlog.log.gz"
    assert rows[0]["raw_sha256"] != rows[0]["content_sha256"]
    assert result.source_results[1]["existing_stored_filename"] == rows[0]["stored_filename"]


def test_unknown_timestamp_is_archived_without_fabricated_date(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    profile = MeshStorageService("demo", paths).create_mr_profile("列车34-MR-CT")
    source = tmp_path / "meshlog.log"
    source.write_text("MESH title without timestamp\n", encoding="utf-8")

    result = MeshImportService("demo", paths).import_files(profile, [source])

    assert result.imported_count == 1
    assert result.parsed_record_count == 0
    row = MeshMrRepository(paths.mesh_mr_db_path("demo", profile.safe_folder_name)).list_source_files()[0]
    assert row["stored_filename"] == "unknown_date_1meshlog.log"
    assert row["log_date"] in (None, "")
    assert row["daily_sequence"] == 1
    assert row["rename_status"] == "timestamp_not_found"
    assert row["source_status"] == "timestamp_not_found"
    assert "未识别到首个有效日志时间" in row["rename_warning"]


def test_batch_duplicate_keeps_one_member_and_cross_profile_duplicate_is_blocked(
    tmp_path: Path,
) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    storage = MeshStorageService("demo", paths)
    ct = storage.create_mr_profile("列车34-MR-CT")
    cw = storage.create_mr_profile("列车34-MR-CW")
    archive = tmp_path / "batch.zip"
    body = _log("2026/07/28 00:18:56.311")
    _zip(archive, {"a/meshlog.log": body, "b/meshlog.log": body})
    service = MeshBundleImportService("demo", paths)
    with archive.open("rb") as source:
        preview = service.create_preview(archive.name, source, [ct, cw])
    assert preview["items"][1]["duplicate_status"] == "duplicate_in_current_batch"
    mappings = [
        {
            "member_id": item["member_id"],
            "train_number": "34",
            "role": "CT",
            "profile_id": ct.mr_id,
        }
        for item in preview["items"]
    ]
    _manifest, approved = service.approve_preview(
        str(preview["preview_id"]),
        mappings,
        [ct.mr_id, cw.mr_id],
    )
    assert len(approved) == 1
    result = service.import_approved_preview(
        str(preview["preview_id"]),
        approved,
        job_id="batch-duplicate",
    )
    assert result["imported_count"] == 1
    assert result["duplicate_count"] == 1

    other = tmp_path / "other.zip"
    _zip(other, {"meshlog.log": body})
    second_service = MeshBundleImportService("demo", paths)
    with other.open("rb") as source:
        second_preview = second_service.create_preview(other.name, source, [ct, cw])
    ct_state = next(
        state
        for state in second_preview["items"][0]["profile_import_states"]
        if state["profile_id"] == ct.mr_id
    )
    assert ct_state["duplicate_status"] == "duplicate_same_mr"
    assert ct_state["existing_stored_filename"] == "2026_07_28_1meshlog.log"
    with pytest.raises(MeshBundleImportError, match="其他 MR"):
        second_service.approve_preview(
            str(second_preview["preview_id"]),
            [
                {
                    "member_id": second_preview["items"][0]["member_id"],
                    "train_number": "34",
                    "role": "CW",
                    "profile_id": cw.mr_id,
                }
            ],
            [ct.mr_id, cw.mr_id],
        )
