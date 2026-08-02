from __future__ import annotations

import gc
import json
from pathlib import Path
from uuid import uuid4

import pytest

from netconsole.core.paths import PathResolver
from netconsole.repositories.mesh_catalog_repository import MeshCatalogRepository
from netconsole.repositories.mesh_source_index_repository import (
    MeshSourceIndexRepository,
)
from netconsole.services.mesh_catalog_index_service import MeshCatalogIndexService
from netconsole.services.mesh_import_service import MeshImportService
from netconsole.services.mesh_source_delete_service import MeshSourceDeleteService
from netconsole.services.mesh_source_rebuild_service import MeshSourceRebuildService
from netconsole.services.mesh_storage_service import MeshStorageService
from netconsole.services.rail_transit.mesh_analysis_query_service import (
    MeshAnalysisQueryService,
)

from mesh_analysis_test_support import EmptyBaseQuery


MESH_LOG = (
    "[1] 2025/12/03 10:12:33.579\n"
    "[1] Active 30f5-277a-5a2f 2025/12/03 10:12:30 0d 00h 00m 03s 1 "
    "36/43 2%/4% 45%/47% 3/1 15/27 60/72060 88/105 0/5000 2/297 "
    "314/0 0/93 0/0 0/0 0/0\n"
)


def _import_source(tmp_path: Path):
    paths = PathResolver(tmp_path)
    profile = MeshStorageService("demo", paths).create_mr_profile("列车01-MR-CT")
    external = tmp_path / "external" / "mesh.log"
    external.parent.mkdir()
    external.write_text(MESH_LOG, encoding="utf-8")
    result = MeshImportService("demo", paths).import_files(profile, [external])
    MeshCatalogIndexService(paths).rebuild_now("demo")
    repository = MeshSourceIndexRepository(
        paths.mesh_mr_db_path("demo", profile.safe_folder_name)
    )
    source = repository.list_source_files()[0]
    session_id = f"{profile.mr_id}:{source['id']}"
    return paths, profile, external, repository, source, session_id, result


def _write_report_manifest(
    paths: PathResolver,
    *,
    profile_name: str,
    session_id: str,
    bound: bool,
) -> tuple[Path, Path]:
    artifact_id = str(uuid4())
    output_root = paths.mesh_mr_export_dir("demo", profile_name)
    output_root.mkdir(parents=True, exist_ok=True)
    report = output_root / f"report-{artifact_id[:8]}.xlsx"
    report.write_bytes(b"report")
    manifest_root = (
        paths.rail_transit_root("demo") / "web_artifacts" / "manifests"
    )
    manifest_root.mkdir(parents=True, exist_ok=True)
    manifest = manifest_root / f"{artifact_id}.json"
    payload: dict[str, object] = {
        "artifact_id": artifact_id,
        "site_id": "demo",
        "owner": "web_rail_transit",
        "source": "mesh_analysis_report",
        "artifact_type": "xlsx",
        "task_id": f"rail-export-{uuid4().hex}",
        "task_type": "web_export_mesh_analysis_report",
        "task_source": "local",
        "relative_path": report.relative_to(
            paths.site_dir("demo")
        ).as_posix(),
        "completed": True,
        "file_name": report.name,
        "display_name": report.name,
    }
    if bound:
        payload["context"] = {
            "kind": "mesh_analysis_session",
            "session_id": session_id,
        }
    manifest.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    return report, manifest


def test_delete_parsed_keeps_raw_source_fingerprint_and_rebuildability(
    tmp_path: Path,
) -> None:
    paths, profile, external, repository, source, session_id, _result = (
        _import_source(tmp_path)
    )
    raw = Path(str(source["archived_path"]))
    parsed = Path(str(source["parsed_db_path"]))
    wal = parsed.with_name(parsed.name + "-wal")
    shm = parsed.with_name(parsed.name + "-shm")
    gc.collect()
    wal.unlink(missing_ok=True)
    shm.unlink(missing_ok=True)
    wal.write_bytes(b"wal")
    shm.write_bytes(b"shm")
    report, manifest = _write_report_manifest(
        paths,
        profile_name=profile.safe_folder_name,
        session_id=session_id,
        bound=True,
    )
    legacy_report, legacy_manifest = _write_report_manifest(
        paths,
        profile_name=profile.safe_folder_name,
        session_id=session_id,
        bound=False,
    )
    catalog = MeshCatalogRepository(paths.mesh_catalog_path("demo"))
    fingerprints_before = catalog.find_source_fingerprints(
        content_sha256=str(source.get("content_sha256") or ""),
        raw_sha256=str(source.get("raw_sha256") or source.get("sha256") or ""),
    )

    result = MeshSourceDeleteService(paths).delete_source(
        "demo",
        session_id,
        delete_raw_archive=False,
        delete_parsed_data=True,
        delete_generated_reports=True,
    )

    remaining = repository.get_source_file(int(source["id"]))
    assert remaining is not None
    assert str(remaining["parsed_deleted_at"])
    assert raw.is_file()
    assert external.is_file()
    assert not parsed.exists()
    assert not wal.exists()
    assert not shm.exists()
    assert not report.exists()
    assert not manifest.exists()
    assert legacy_report.is_file()
    assert legacy_manifest.is_file()
    assert result["deleted_reports"] == 1
    assert catalog.find_source_fingerprints(
        content_sha256=str(source.get("content_sha256") or ""),
        raw_sha256=str(source.get("raw_sha256") or source.get("sha256") or ""),
    ) == fingerprints_before
    page = MeshAnalysisQueryService(
        paths,
        base_query=EmptyBaseQuery(),
        schedule_catalog_index=False,
    ).list_analysis_sessions("demo")
    assert [item.session_id for item in page.items] == [session_id]
    assert page.items[0].parsed_status == "missing"

    rebuilt = MeshSourceRebuildService(paths).rebuild_source("demo", session_id)
    refreshed = repository.get_source_file(int(source["id"]))
    assert rebuilt["parsed_record_count"] == 1
    assert refreshed is not None
    assert not str(refreshed["parsed_deleted_at"])
    assert Path(str(refreshed["parsed_db_path"])).is_file()


def test_delete_complete_preserves_external_file_and_allows_reimport(
    tmp_path: Path,
) -> None:
    paths, profile, external, repository, source, session_id, _result = (
        _import_source(tmp_path)
    )
    raw = Path(str(source["archived_path"]))
    parsed = Path(str(source["parsed_db_path"]))
    report, manifest = _write_report_manifest(
        paths,
        profile_name=profile.safe_folder_name,
        session_id=session_id,
        bound=True,
    )

    first = MeshSourceDeleteService(paths).delete_source(
        "demo",
        session_id,
        delete_raw_archive=True,
        delete_parsed_data=True,
        delete_generated_reports=False,
    )
    second = MeshSourceDeleteService(paths).delete_source(
        "demo",
        session_id,
        delete_raw_archive=True,
        delete_parsed_data=True,
        delete_generated_reports=True,
    )

    assert external.is_file()
    assert not raw.exists()
    assert not parsed.exists()
    assert not report.exists()
    assert not manifest.exists()
    assert repository.get_source_file(int(source["id"])) is None
    assert first["delete_generated_reports"] is True
    assert second["already_deleted"] is True
    reimported = MeshImportService("demo", paths).import_files(profile, [external])
    assert reimported.duplicate_count == 0
    assert len(repository.list_source_files()) == 1


def test_delete_complete_tolerates_missing_raw_and_parsed_files(
    tmp_path: Path,
) -> None:
    paths, _profile, external, repository, source, session_id, _result = (
        _import_source(tmp_path)
    )
    gc.collect()
    Path(str(source["archived_path"])).unlink()
    Path(str(source["parsed_db_path"])).unlink()

    result = MeshSourceDeleteService(paths).delete_source(
        "demo",
        session_id,
        delete_raw_archive=True,
        delete_parsed_data=True,
        delete_generated_reports=True,
    )

    assert result["already_deleted"] is False
    assert result["deleted_files"] == 0
    assert result["deleted_file_count"] == 0
    assert result["missing_file_count"] == 2
    assert external.is_file()
    assert repository.get_source_file(int(source["id"])) is None


def test_delete_catalog_failure_restores_files_and_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, profile, external, repository, source, session_id, _result = (
        _import_source(tmp_path)
    )
    raw = Path(str(source["archived_path"]))
    parsed = Path(str(source["parsed_db_path"]))
    report, manifest = _write_report_manifest(
        paths,
        profile_name=profile.safe_folder_name,
        session_id=session_id,
        bound=True,
    )

    def fail_delete(*_args, **_kwargs):
        raise RuntimeError("catalog failure")

    monkeypatch.setattr(MeshCatalogRepository, "delete_source_index", fail_delete)
    with pytest.raises(RuntimeError, match="catalog failure"):
        MeshSourceDeleteService(paths).delete_source(
            "demo",
            session_id,
            delete_raw_archive=True,
            delete_parsed_data=True,
            delete_generated_reports=True,
        )

    assert external.is_file()
    assert raw.is_file()
    assert parsed.is_file()
    assert report.is_file()
    assert manifest.is_file()
    assert repository.get_source_file(int(source["id"])) is not None
    catalog = MeshCatalogRepository(paths.mesh_catalog_path("demo"))
    assert catalog.find_source_fingerprints(
        content_sha256=str(source.get("content_sha256") or ""),
        raw_sha256=str(source.get("raw_sha256") or source.get("sha256") or ""),
    )
