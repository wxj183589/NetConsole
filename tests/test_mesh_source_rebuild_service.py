from __future__ import annotations

import io
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from netconsole.core.paths import PathResolver
from netconsole.parsers.mesh_log_parser import sha256_file
from netconsole.repositories.mesh_mr_repository import MeshMrRepository
from netconsole.services.background_job import BackgroundJob
from netconsole.services.job_center.job_runner import run_job
from netconsole.services.mesh_bundle_import_service import MeshBundleImportService
from netconsole.services.mesh_source_rebuild_service import (
    MeshSourceRebuildCancelled,
    MeshSourceRebuildService,
)
from netconsole.services.mesh_storage_service import MeshStorageService


LINE = (
    "[1] Active 30f5-277a-5a2f 2025/12/03 10:12:30 0d 00h 00m 03s 1 "
    "36/43 2%/4% 45%/47% 3/1 15/27 60/72060 88/105 0/5000 2/297 "
    "314/0 0/93 0/0 0/0 0/0"
)


def _log(second: int) -> bytes:
    return (f"[1] 2025/12/03 10:12:{second:02d}.579 (3)\n{LINE}\n").encode()


def _preview(tmp_path: Path) -> tuple[PathResolver, object, dict[str, object]]:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    storage = MeshStorageService("demo", paths)
    profile = storage.create_mr_profile("列车01-MR-CT")
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("01CTmeshlog.log", _log(33))
        bundle.writestr("1CTmeshlog.log", _log(34))
    archive.seek(0)
    service = MeshBundleImportService("demo", paths)
    preview = service.create_preview("mesh.zip", archive, [profile])
    mappings = [
        {"member_id": item["member_id"], "train_number": "01", "role": "CT", "profile_id": profile.mr_id}
        for item in preview["items"]
    ]
    service.approve_preview(str(preview["preview_id"]), mappings, [profile.mr_id])
    result = service.import_approved_preview(str(preview["preview_id"]), mappings, job_id="source-rebuild-fixture")
    return paths, profile, result


def test_source_rebuild_restores_bundle_member_and_keeps_other_source_unchanged(tmp_path: Path) -> None:
    paths, profile, result = _preview(tmp_path)
    repository = MeshMrRepository(paths.mesh_mr_db_path("demo", profile.safe_folder_name))
    sources = repository.list_source_files()
    assert len(sources) == 2
    selected, other = sources
    selected_detail = Path(str(selected["parsed_db_path"]))
    other_detail = Path(str(other["parsed_db_path"]))
    other_before = sha256_file(other_detail)
    raw = Path(str(selected["archived_path"]))
    raw.unlink()

    rebuilt = MeshSourceRebuildService(paths).rebuild_source(
        "demo",
        f"{profile.mr_id}:{selected['id']}",
    )
    refreshed = repository.get_source_file(int(selected["id"]))

    assert rebuilt["created_session_ids"] == [f"{profile.mr_id}:{selected['id']}"]
    assert rebuilt["raw_archived_count"] == 0
    assert rebuilt["parsed_record_count"] >= 1
    assert refreshed is not None
    restored_raw = Path(str(refreshed["archived_path"]))
    assert not restored_raw.exists()
    assert Path(str(refreshed["parsed_db_path"])).is_file()
    assert sha256_file(other_detail) == other_before
    assert selected_detail.name == Path(str(refreshed["parsed_db_path"])).name
    assert str(tmp_path / "imports") not in json.dumps(refreshed, ensure_ascii=False, default=str)
    with sqlite3.connect(refreshed["parsed_db_path"]) as connection:
        assert connection.execute("SELECT COUNT(*) FROM mesh_links").fetchone()[0] >= 1
    assert len(result["created_session_ids"]) == 2


def test_source_rebuild_prefers_identity_only_remap_for_healthy_detail(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths, profile, _result = _preview(tmp_path)
    repository = MeshMrRepository(paths.mesh_mr_db_path("demo", profile.safe_folder_name))
    source = repository.list_source_files()[0]
    detail = Path(str(source["parsed_db_path"]))
    raw = Path(str(source["archived_path"]))
    raw_before = sha256_file(raw)
    with sqlite3.connect(detail) as connection:
        facts_before = connection.execute(
            """
            SELECT peer_mac_raw, sample_time, local_rssi_db, peer_rssi_db,
                   local_tx_busy, peer_tx_busy, link_state, record_fingerprint
            FROM mesh_links ORDER BY id
            """
        ).fetchall()
        link_count_before = connection.execute(
            "SELECT COUNT(*) FROM mesh_links"
        ).fetchone()[0]

    def fail_parse(*_args, **_kwargs):
        raise AssertionError("healthy detail must not be reparsed")

    monkeypatch.setattr(
        "netconsole.services.mesh_source_rebuild_service.MeshLogParser.parse_file",
        fail_parse,
    )
    rebuilt = MeshSourceRebuildService(paths).rebuild_source(
        "demo",
        f"{profile.mr_id}:{source['id']}",
    )

    assert rebuilt["recovery_source"] == "identity_only_remap"
    assert rebuilt["raw_archived_count"] == 0
    assert sha256_file(raw) == raw_before
    with sqlite3.connect(detail) as connection:
        facts_after = connection.execute(
            """
            SELECT peer_mac_raw, sample_time, local_rssi_db, peer_rssi_db,
                   local_tx_busy, peer_tx_busy, link_state, record_fingerprint
            FROM mesh_links ORDER BY id
            """
        ).fetchall()
        assert connection.execute("SELECT COUNT(*) FROM mesh_links").fetchone()[0] == link_count_before
    assert facts_after == facts_before


def test_identity_remap_finishes_successfully_when_cancel_arrives_after_commit(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths, profile, _result = _preview(tmp_path)
    repository = MeshMrRepository(paths.mesh_mr_db_path("demo", profile.safe_folder_name))
    source = repository.list_source_files()[0]
    detail = Path(str(source["parsed_db_path"]))
    original_checkpoint = MeshSourceRebuildService._checkpoint
    state = {"cancelled": False}

    def checkpoint_then_cancel(path: Path) -> None:
        original_checkpoint(path)
        state["cancelled"] = True

    monkeypatch.setattr(
        MeshSourceRebuildService,
        "_checkpoint",
        staticmethod(checkpoint_then_cancel),
    )

    rebuilt = MeshSourceRebuildService(paths).rebuild_source(
        "demo",
        f"{profile.mr_id}:{source['id']}",
        should_cancel=lambda: state["cancelled"],
    )

    assert state["cancelled"] is True
    assert rebuilt["recovery_source"] == "identity_only_remap"
    assert rebuilt["parsed_record_count"] >= 1
    assert detail.is_file()


def test_source_rebuild_cancel_before_commit_uses_cancelled_job_terminal(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths, profile, _result = _preview(tmp_path)
    repository = MeshMrRepository(paths.mesh_mr_db_path("demo", profile.safe_folder_name))
    source = repository.list_source_files()[0]

    with pytest.raises(MeshSourceRebuildCancelled):
        MeshSourceRebuildService(paths).rebuild_source(
            "demo",
            f"{profile.mr_id}:{source['id']}",
            should_cancel=lambda: True,
        )

    class CancelledService:
        def __init__(self, _paths: PathResolver) -> None:
            pass

        def rebuild_source(self, *_args, **_kwargs):
            raise MeshSourceRebuildCancelled("MESH 来源重建任务已取消")

    monkeypatch.setattr(
        "netconsole.services.job_center.handlers.mesh_jobs.MeshSourceRebuildService",
        CancelledService,
    )
    result = run_job(
        BackgroundJob(
            job_id="mesh-source-cancelled",
            task_type="mesh_source_rebuild",
            params={
                "app_root": str(tmp_path),
                "data_root": str(tmp_path),
                "site_name": "demo",
                "session_id": f"{profile.mr_id}:{source['id']}",
            },
        )
    )

    assert result.cancelled is True
    assert result.ok is False
    assert result.error == "MESH 来源重建任务已取消"
