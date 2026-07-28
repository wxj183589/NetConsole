from __future__ import annotations

import json
import sqlite3
import stat
import zipfile
from contextlib import closing
from pathlib import Path

import pytest

from netconsole.core.paths import PathResolver
from netconsole.repositories.mesh_mr_repository import SCHEMA_VERSION, MeshMrRepository
from netconsole.services import mesh_bundle_import_service as bundle_module
from netconsole.services.mesh_bundle_import_service import (
    MeshBundleImportError,
    MeshBundleImportService,
)
from netconsole.services.mesh_import_service import MeshImportService
from netconsole.services.mesh_log_analysis_service import PARSER_VERSION
from netconsole.services.mesh_storage_service import MeshStorageService


LINE_ACTIVE = (
    "[1] Active 30f5-277a-5a2f 2025/12/03 10:12:30 0d 00h 00m 03s 1 "
    "36/43 2%/4% 45%/47% 3/1 15/27 60/72060 88/105 0/5000 2/297 "
    "314/0 0/93 0/0 0/0 0/0"
)
VALID_LOG = ("[1] 2025/12/03 10:12:33.579 (3)\n" + LINE_ACTIVE + "\n").encode()


def _zip(path: Path, names: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in names.items():
            archive.writestr(name, content)


def _mark_first_member_encrypted(path: Path) -> None:
    payload = bytearray(path.read_bytes())
    for signature, offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        position = payload.find(signature)
        assert position >= 0
        flags = int.from_bytes(payload[position + offset : position + offset + 2], "little") | 0x1
        payload[position + offset : position + offset + 2] = flags.to_bytes(2, "little")
    path.write_bytes(payload)


def test_bundle_manifest_maps_train_role_and_06_alias(tmp_path: Path) -> None:
    archive = tmp_path / "mesh.zip"
    _zip(
        archive,
        {
            "nested/01CTmeshlog.log": b"ct",
            "6CWmeshlog.log": b"cw",
            "06CTmeshlog.log": b"ct2",
        },
    )
    manifest = MeshBundleImportService("demo", PathResolver(tmp_path)).inspect(archive)

    assert [(item.train_number, item.role, item.train_aliases) for item in manifest.members] == [
        ("01", "CT", ("01",)),
        ("06", "CW", ("6", "06")),
        ("06", "CT", ("06",)),
    ]
    assert [item.file_order for item in manifest.members] == [1, 2, 3]


def test_bundle_rejects_traversal_symlink_and_encrypted_members(tmp_path: Path) -> None:
    service = MeshBundleImportService("demo", PathResolver(tmp_path))
    traversal = tmp_path / "traversal.zip"
    _zip(traversal, {"../escape.log": b"bad"})
    with pytest.raises(MeshBundleImportError, match="越界"):
        service.inspect(traversal)

    symlink = tmp_path / "symlink.zip"
    with zipfile.ZipFile(symlink, "w") as archive:
        entry = zipfile.ZipInfo("01CTmeshlog.log")
        entry.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(entry, "target")
    with pytest.raises(MeshBundleImportError, match="符号链接"):
        service.inspect(symlink)

    encrypted = tmp_path / "encrypted.zip"
    _zip(encrypted, {"01CTmeshlog.log": b"fixture"})
    _mark_first_member_encrypted(encrypted)
    with pytest.raises(MeshBundleImportError, match="禁止加密"):
        service.inspect(encrypted)


def test_bundle_enforces_archive_member_and_compression_boundaries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = MeshBundleImportService("demo", PathResolver(tmp_path))
    archive = tmp_path / "members.zip"
    _zip(archive, {f"{index:02d}CTmeshlog.log": bytes([index]) for index in range(3)})
    monkeypatch.setattr(bundle_module, "_MAX_MEMBER_COUNT", 2)
    with pytest.raises(MeshBundleImportError, match="成员数量"):
        service.inspect(archive)

    monkeypatch.setattr(bundle_module, "_MAX_MEMBER_COUNT", 64)
    compressed = tmp_path / "ratio.zip"
    _zip(compressed, {"01CTmeshlog.log": b"A" * 1_000_000})
    with pytest.raises(MeshBundleImportError, match="压缩比"):
        service.inspect(compressed)

    monkeypatch.setattr(bundle_module, "_MAX_ARCHIVE_SIZE", 8)
    with pytest.raises(MeshBundleImportError, match="50 MiB"):
        service.inspect(archive)


def test_bundle_profile_mapping_uses_unmatched_contract(tmp_path: Path) -> None:
    archive = tmp_path / "mesh.zip"
    _zip(
        archive,
        {
            "6CWmeshlog.log": b"cw",
            "01CTmeshlog.log": b"ct",
            "02CTmeshlog.log": b"ct2",
        },
    )
    service = MeshBundleImportService("demo", PathResolver(tmp_path))
    manifest = service.inspect(archive)
    profiles = [
        {"mr_id": "p6", "display_name": "06-MR-CW"},
        {"mr_id": "p1a", "display_name": "01-MR-CT"},
        {"mr_id": "p1b", "display_name": "01MR-CT"},
    ]

    matches = service.match_profiles(manifest, profiles)
    assert [(item.member.train_number, item.status, item.profile_id) for item in matches] == [
        ("06", "matched", "p6"),
        ("01", "ambiguous", None),
        ("02", "unmatched", None),
    ]


def test_bundle_profile_mapping_accepts_tc_only_as_legacy_cw_alias(tmp_path: Path) -> None:
    archive = tmp_path / "mesh.zip"
    _zip(archive, {"6CWmeshlog.log": b"cw", "6CTmeshlog.log": b"ct"})
    service = MeshBundleImportService("demo", PathResolver(tmp_path))

    matches = service.match_profiles(
        service.inspect(archive),
        [
            {"mr_id": "legacy-tc", "display_name": "列车06-MR-TC"},
            {"mr_id": "ct", "display_name": "列车06-MR-CT"},
        ],
    )

    assert [(item.member.role, item.profile_id) for item in matches] == [
        ("CW", "legacy-tc"),
        ("CT", "ct"),
    ]


def test_preview_uses_safe_token_and_twelve_tmp_path_members(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    storage = MeshStorageService("demo", paths)
    identities = [(train, role) for train in ("01", "02", "03", "04", "34", "06") for role in ("CT", "CW")]
    profiles = [storage.create_mr_profile(f"{train}-MR-{role}") for train, role in identities]
    archive = tmp_path / "twelve.zip"
    _zip(archive, {f"{train}{role}meshlog.log": f"{train}-{role}".encode() for train, role in identities})

    service = MeshBundleImportService("demo", paths)
    with archive.open("rb") as source:
        preview = service.create_preview(archive.name, source, profiles)

    assert preview["member_count"] == 12
    assert len(str(preview["preview_id"])) == 32
    assert all(item["candidates"] for item in preview["items"])
    assert str(tmp_path) not in json.dumps(preview, ensure_ascii=False)


def test_successful_worker_commit_rewrites_staging_paths_and_finalizes_manifest(
    tmp_path: Path,
) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    profile = MeshStorageService("demo", paths).create_mr_profile("01-MR-CT")
    archive = tmp_path / "bundle.zip"
    _zip(archive, {"01CTmeshlog.log": VALID_LOG})
    service = MeshBundleImportService("demo", paths)
    with archive.open("rb") as source:
        preview = service.create_preview(archive.name, source, [profile])
    mappings = [
        {
            "member_id": "01CTmeshlog.log",
            "train_number": "01",
            "role": "CT",
            "profile_id": profile.mr_id,
        }
    ]
    service.approve_preview(str(preview["preview_id"]), mappings, [profile.mr_id])

    result = service.import_approved_preview(
        str(preview["preview_id"]),
        mappings,
        job_id="mesh-bundle-fixture",
    )

    assert result["imported_count"] == 1
    repository = MeshMrRepository(paths.mesh_mr_db_path("demo", profile.safe_folder_name))
    source_row = repository.list_source_files()[0]
    parsed_path = Path(str(source_row["parsed_db_path"]))
    assert parsed_path.is_file()
    assert parsed_path.is_relative_to(paths.mesh_mr_parsed_dir("demo", profile.safe_folder_name))
    assert ".staging" not in str(parsed_path)
    assert source_row["raw_relative_path"].startswith("raw/")
    assert source_row["parsed_relative_path"].startswith("parsed/")
    assert source_row["archive_sha256"] == preview["archive_sha256"]
    assert source_row["bundle_member_id"] == "01CTmeshlog.log"
    with sqlite3.connect(parsed_path) as connection:
        assert connection.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0] == SCHEMA_VERSION
    manifest_path = paths.site_mesh_root("demo") / "bundles" / preview["archive_sha256"] / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "success"
    assert manifest["parser_version"] == PARSER_VERSION
    assert manifest["parsed_schema_version"] == SCHEMA_VERSION
    assert manifest["file_mappings"][0]["original_name"] == "01CTmeshlog.log"

    duplicate = service.import_approved_preview(
        str(preview["preview_id"]),
        mappings,
        job_id="mesh-bundle-duplicate",
    )
    assert duplicate["idempotent"] is True
    assert repository.summary()["source_file_count"] == 1


def test_worker_commit_keeps_catalog_file_when_another_process_has_open_reader(
    tmp_path: Path,
) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    storage = MeshStorageService("demo", paths)
    profile = storage.create_mr_profile("01-MR-CT")
    archive = tmp_path / "bundle.zip"
    _zip(archive, {"01CTmeshlog.log": VALID_LOG})
    service = MeshBundleImportService("demo", paths)
    with archive.open("rb") as source:
        preview = service.create_preview(archive.name, source, [profile])
    mappings = [
        {
            "member_id": "01CTmeshlog.log",
            "train_number": "01",
            "role": "CT",
            "profile_id": profile.mr_id,
        }
    ]
    service.approve_preview(str(preview["preview_id"]), mappings, [profile.mr_id])

    catalog_path = paths.mesh_catalog_path("demo")
    with closing(sqlite3.connect(catalog_path)) as reader:
        reader.execute("PRAGMA journal_mode = WAL")
        reader.execute("BEGIN")
        assert reader.execute(
            "SELECT source_file_count FROM mr_profiles WHERE mr_id = ?",
            (profile.mr_id,),
        ).fetchone() == (0,)
        result = service.import_approved_preview(
            str(preview["preview_id"]),
            mappings,
            job_id="mesh-bundle-open-catalog-reader",
        )

    assert result["imported_count"] == 1
    refreshed = MeshStorageService("demo", paths).catalog.get_profile(profile.mr_id)
    assert refreshed is not None
    assert refreshed.source_file_count == 1


def test_worker_commit_keeps_profile_directory_with_open_reader(
    tmp_path: Path,
) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    storage = MeshStorageService("demo", paths)
    profile = storage.create_mr_profile("01-MR-CT")
    archive = tmp_path / "bundle.zip"
    _zip(archive, {"01CTmeshlog.log": VALID_LOG})
    service = MeshBundleImportService("demo", paths)
    with archive.open("rb") as source:
        preview = service.create_preview(archive.name, source, [profile])
    mappings = [
        {
            "member_id": "01CTmeshlog.log",
            "train_number": "01",
            "role": "CT",
            "profile_id": profile.mr_id,
        }
    ]
    service.approve_preview(str(preview["preview_id"]), mappings, [profile.mr_id])

    profile_database = paths.mesh_mr_db_path("demo", profile.safe_folder_name)
    with closing(sqlite3.connect(profile_database)) as reader:
        reader.execute("PRAGMA journal_mode = WAL")
        reader.execute("BEGIN")
        assert reader.execute("SELECT COUNT(*) FROM source_files").fetchone() == (0,)
        result = service.import_approved_preview(
            str(preview["preview_id"]),
            mappings,
            job_id="mesh-bundle-open-profile-reader",
        )
        assert reader.execute("SELECT COUNT(*) FROM source_files").fetchone() == (0,)
        reader.commit()
        assert reader.execute("SELECT COUNT(*) FROM source_files").fetchone() == (1,)

    assert result["imported_count"] == 1
    assert MeshMrRepository(profile_database).summary()["source_file_count"] == 1


def test_failed_worker_does_not_change_production_or_publish_success_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    profile = MeshStorageService("demo", paths).create_mr_profile("01-MR-CT")
    archive = tmp_path / "bundle.zip"
    _zip(archive, {"01CTmeshlog.log": VALID_LOG})
    service = MeshBundleImportService("demo", paths)
    with archive.open("rb") as source:
        preview = service.create_preview(archive.name, source, [profile])
    mappings = [{"member_id": "01CTmeshlog.log", "train_number": "01", "role": "CT", "profile_id": profile.mr_id}]
    service.approve_preview(str(preview["preview_id"]), mappings, [profile.mr_id])

    def fail_import(*_args, **_kwargs):
        raise RuntimeError("fixture failure")

    monkeypatch.setattr("netconsole.services.mesh_import_service.MeshImportService.import_files", fail_import)
    with pytest.raises(RuntimeError, match="fixture failure"):
        service.import_approved_preview(
            str(preview["preview_id"]),
            mappings,
            job_id="mesh-bundle-failed",
        )

    repository = MeshMrRepository(paths.mesh_mr_db_path("demo", profile.safe_folder_name))
    assert repository.summary()["source_file_count"] == 0
    assert not (paths.site_mesh_root("demo") / "bundles" / preview["archive_sha256"]).exists()


def test_bundle_import_rebuilds_legacy_index_only_inside_staging(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    profile = MeshStorageService("demo", paths).create_mr_profile("01-MR-CT")
    first = tmp_path / "first.log"
    first.write_bytes(VALID_LOG)
    MeshImportService("demo", paths).import_files(profile, [first])
    index = paths.mesh_mr_db_path("demo", profile.safe_folder_name)
    with closing(sqlite3.connect(index)) as connection:
        connection.execute("UPDATE schema_meta SET value = '1' WHERE key = 'schema_version'")
        connection.execute("UPDATE meta SET value = '1' WHERE key = 'schema_version'")
        connection.commit()
    legacy_bytes = index.read_bytes()
    archive = tmp_path / "bundle.zip"
    _zip(archive, {"01CTmeshlog.log": VALID_LOG.replace(b"33.579", b"34.579")})
    service = MeshBundleImportService("demo", paths)
    with archive.open("rb") as source:
        preview = service.create_preview(archive.name, source, [profile])
    mappings = [{"member_id": "01CTmeshlog.log", "train_number": "01", "role": "CT", "profile_id": profile.mr_id}]
    service.approve_preview(str(preview["preview_id"]), mappings, [profile.mr_id])

    result = service.import_approved_preview(str(preview["preview_id"]), mappings, job_id="legacy-index-import")

    assert result["imported_count"] == 1
    assert result["parsed_record_count"] >= 1
    assert index.read_bytes() != legacy_bytes
    repository = MeshMrRepository(index)
    source_rows = repository.list_source_files()
    assert len(source_rows) == 2
    assert all(Path(str(row["archived_path"])).is_file() for row in source_rows)
    assert all(str(tmp_path) not in str(row["original_path"]) for row in source_rows)
    for row in source_rows:
        detail_path = Path(str(row["parsed_db_path"]))
        with closing(sqlite3.connect(detail_path)) as connection:
            detail_source = connection.execute(
                "SELECT original_path, archived_path FROM source_files"
            ).fetchone()
        assert detail_source is not None
        assert ".staging" not in str(detail_source[0])
        assert ".staging" not in str(detail_source[1])
    assert not list(index.parent.glob("*.schema_archive_*"))
