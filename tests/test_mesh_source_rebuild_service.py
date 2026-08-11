from __future__ import annotations

import io
import json
import sqlite3
import zipfile
from copy import deepcopy
from contextlib import closing
from pathlib import Path

import pytest

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.parsers.mesh_log_parser import MeshLogParser, sha256_file
from netconsole.repositories.ac_repository import AcRepository
from netconsole.repositories.mesh_mr_repository import (
    MeshIdentityRemapValidationError,
    MeshMrRepository,
)
from netconsole.services.background_job import BackgroundJob
from netconsole.services.job_center.job_runner import run_job
from netconsole.services.mesh_bundle_import_service import MeshBundleImportService
from netconsole.services.mesh_import_service import MeshImportService
from netconsole.services.mesh_source_rebuild_service import (
    MeshSourceRebuildCancelled,
    MeshSourceRebuildService,
)
from netconsole.services.mesh_peer_mapping_service import MeshPeerMappingService
from netconsole.services.mesh_storage_service import MeshStorageService
from netconsole.services.rail_transit.mesh_analysis_query_service import (
    MeshAnalysisQueryService,
)
from scripts.maintenance.remap_mesh_identity import (
    apply_plan as apply_identity_remap_plan,
    build_plan as build_identity_remap_plan,
    manifest as identity_remap_manifest,
)


LINE = (
    "[1] Active 30f5-277a-5a2f 2025/12/03 10:12:30 0d 00h 00m 03s 1 "
    "36/43 2%/4% 45%/47% 3/1 15/27 60/72060 88/105 0/5000 2/297 "
    "314/0 0/93 0/0 0/0 0/0"
)
TRIANGLE_LINE = LINE.replace("5a2f", "5a3f").replace("03s 1 36/43", "03s 2 36/43")


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


def test_new_mesh_import_uses_current_parser_without_upgrade_prompt(
    tmp_path: Path,
) -> None:
    paths, profile, _result = _preview(tmp_path)
    source = MeshMrRepository(
        paths.mesh_mr_db_path("demo", profile.safe_folder_name)
    ).list_source_files()[0]

    detail = MeshAnalysisQueryService(paths).get_analysis_session(
        "demo",
        f"{profile.mr_id}:{source['id']}",
    )

    assert detail.maintenance_state.schema_status == "current"
    assert detail.maintenance_state.parser_status == "current"
    assert detail.maintenance_state.derived_analysis_status == "current"


def test_source_rebuild_force_reparse_replaces_existing_detail_from_raw(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, profile, _result = _preview(tmp_path)
    repository = MeshMrRepository(paths.mesh_mr_db_path("demo", profile.safe_folder_name))
    source = repository.list_source_files()[0]
    detail = Path(str(source["parsed_db_path"]))
    raw = Path(str(source["archived_path"]))
    raw_before = sha256_file(raw)
    with closing(sqlite3.connect(detail)) as connection:
        connection.execute("UPDATE mesh_links SET link_count = 0")
        connection.commit()
        assert connection.execute("SELECT DISTINCT link_count FROM mesh_links").fetchall() == [(0,)]

    original_parse = MeshLogParser.parse_file
    parsed_paths: list[Path] = []

    def observe_parse(self, path: Path, *args, **kwargs):
        parsed_paths.append(path)
        return original_parse(self, path, *args, **kwargs)

    monkeypatch.setattr(MeshLogParser, "parse_file", observe_parse)

    rebuilt = MeshSourceRebuildService(paths).rebuild_source(
        "demo",
        f"{profile.mr_id}:{source['id']}",
        force_reparse=True,
    )

    assert rebuilt["recovery_source"] == "raw_reparse"
    assert parsed_paths == [raw]
    assert sha256_file(raw) == raw_before
    with closing(sqlite3.connect(detail)) as connection:
        assert connection.execute("SELECT DISTINCT link_count FROM mesh_links").fetchall() == [(1,)]


def test_source_rebuild_identity_validation_uses_persisted_deduplicated_count(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, profile, _result = _preview(tmp_path)
    repository = MeshMrRepository(paths.mesh_mr_db_path("demo", profile.safe_folder_name))
    source = repository.list_source_files()[0]
    detail = Path(str(source["parsed_db_path"]))
    original_parse = MeshLogParser.parse_file

    def duplicate_parser_output(self, path: Path, *args, **kwargs):
        info, records, issues = original_parse(self, path, *args, **kwargs)
        return info, [*records, deepcopy(records[0])], issues

    monkeypatch.setattr(MeshLogParser, "parse_file", duplicate_parser_output)

    rebuilt = MeshSourceRebuildService(paths).rebuild_source(
        "demo",
        f"{profile.mr_id}:{source['id']}",
        force_reparse=True,
    )

    with closing(sqlite3.connect(detail)) as connection:
        persisted = int(connection.execute("SELECT COUNT(*) FROM mesh_links").fetchone()[0])
    assert rebuilt["parsed_record_count"] == persisted
    assert rebuilt["identity_remap"]["link_row_count"] == persisted


def test_source_rebuild_force_reparse_restores_previously_filtered_triangle_links(
    tmp_path: Path,
) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    profile = MeshStorageService("demo", paths).create_mr_profile("列车01-MR-CT")
    raw_source = tmp_path / "triangle-meshlog.log"
    raw_source.write_text(
        "[1] 2026/08/07 10:02:52.478\n" + LINE + "\n" + TRIANGLE_LINE + "\n",
        encoding="utf-8",
    )
    MeshImportService("demo", paths).import_files(profile, [raw_source])
    repository = MeshMrRepository(paths.mesh_mr_db_path("demo", profile.safe_folder_name))
    source = repository.list_source_files()[0]
    detail = Path(str(source["parsed_db_path"]))
    with closing(sqlite3.connect(detail)) as connection:
        connection.execute("DELETE FROM mesh_links WHERE link_count = 2")
        connection.commit()
        assert connection.execute("SELECT DISTINCT link_count FROM mesh_links").fetchall() == [(1,)]

    rebuilt = MeshSourceRebuildService(paths).rebuild_source(
        "demo",
        f"{profile.mr_id}:{source['id']}",
        force_reparse=True,
    )

    assert rebuilt["recovery_source"] == "raw_reparse"
    with closing(sqlite3.connect(detail)) as connection:
        assert connection.execute("SELECT link_count FROM mesh_links ORDER BY id").fetchall() == [(1,), (2,)]


def test_identity_only_remap_rebuilds_stale_base_only_index_and_projects_location(
    tmp_path: Path,
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
        assert connection.execute(
            "SELECT COUNT(*) FROM mesh_links WHERE peer_identity_status = 'matched'"
        ).fetchone()[0] == 0

    database = Database(paths.site_db_path("demo"))
    database.initialize()
    AcRepository(database).upsert_ap_extension_point(
        {
            "ap_name": "AP-BASE-01",
            "ap_point_code": "P-001",
            "ap_vendor": "",
            "ap_mac_display": "30f5-277a-5a20",
            "belong_type": "section",
            "station_name": "站点A",
            "section_name": "站点A-站点B",
            "section_start_station": "站点A",
            "section_end_station": "站点B",
            "line_side": "上行",
            "direction": "正向",
            "mileage_text": "K12+300",
        }
    )

    rebuilt = MeshSourceRebuildService(paths).rebuild_source(
        "demo",
        f"{profile.mr_id}:{source['id']}",
    )

    assert rebuilt["recovery_source"] == "identity_only_remap"
    assert rebuilt["identity_remap"]["after"]["matched"] == 1
    assert rebuilt["message"] == (
        "AP 身份重映射完成：1 个 Peer 已映射，"
        "1 条链路身份投影已更新，Identity revision 1。"
        "站点已解析 1，未解析 0（来源：base_data=1）。"
    )
    assert sha256_file(raw) == raw_before
    with sqlite3.connect(detail) as connection:
        facts_after = connection.execute(
            """
            SELECT peer_mac_raw, sample_time, local_rssi_db, peer_rssi_db,
                   local_tx_busy, peer_tx_busy, link_state, record_fingerprint
            FROM mesh_links ORDER BY id
            """
        ).fetchall()
        identity = connection.execute(
            """
            SELECT peer_ap_name, peer_ap_mac, peer_site, peer_radio_id,
                   peer_identity_status, peer_identity_source
            FROM mesh_links ORDER BY id LIMIT 1
            """
        ).fetchone()
    assert facts_after == facts_before
    assert identity == (
        "AP-BASE-01",
        "30:f5:27:7a:5a:20",
        "站点A",
        1,
        "matched",
        "base_data",
    )
    link = MeshAnalysisQueryService(paths).list_link_details(
        "demo",
        f"{profile.mr_id}:{source['id']}",
    ).items[0]
    assert link.peer_ap_name == "AP-BASE-01"
    assert link.peer_ap_mac == "30:f5:27:7a:5a:20"
    assert link.station == "站点A"
    assert link.section == "站点A-站点B"
    assert link.mileage == "K12+300"
    assert link.line_side == "上行"


def test_identity_remap_validation_failure_does_not_publish_ready_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, profile, _result = _preview(tmp_path)
    index = MeshMrRepository(paths.mesh_mr_db_path("demo", profile.safe_folder_name))
    source = index.list_source_files()[0]
    detail = Path(str(source["parsed_db_path"]))
    detail_repo = MeshMrRepository(detail)
    peer = detail_repo.distinct_peer_macs()[0]
    with sqlite3.connect(detail) as connection:
        detail_metadata_before = connection.execute(
            """
            SELECT identity_index_revision, identity_mapped_at,
                   identity_mapping_status
            FROM source_files
            """
        ).fetchall()
        mapping_before = connection.execute(
            "SELECT * FROM mesh_peer_mapping ORDER BY peer_mac_normalized"
        ).fetchall()

    monkeypatch.setattr(
        MeshPeerMappingService,
        "current_identity_revision",
        lambda _self: 8,
    )
    monkeypatch.setattr(
        MeshPeerMappingService,
        "build_rows",
        lambda _self, _peers: [
            {
                "peer_mac_normalized": peer,
                "peer_ap_name": "AP-SYNTHETIC",
                "peer_ap_mac": "083b-e9ec-a2e0",
                "peer_radio_id": 2,
                "peer_radio_label": "radio2",
                "peer_radio_mac": peer,
                "peer_site": "合成站点",
                "match_rule": "h3c_physical_mac_to_r2_exact_v1",
                "match_confidence": 95,
                "identity_status": "matched",
                "identity_source": "base_data",
            }
        ],
    )
    monkeypatch.setattr(
        MeshMrRepository,
        "_update_mesh_link_identity_projection",
        staticmethod(lambda _conn: None),
    )

    with pytest.raises(
        MeshIdentityRemapValidationError,
        match="MESH_IDENTITY_REMAP_ZERO_PERSISTED_MATCH",
    ):
        MeshSourceRebuildService(paths).rebuild_source(
            "demo",
            f"{profile.mr_id}:{source['id']}",
        )

    refreshed = index.get_source_file(int(source["id"]))
    assert refreshed is not None
    assert refreshed["identity_index_revision"] == source["identity_index_revision"]
    assert refreshed["identity_mapped_at"] == source["identity_mapped_at"]
    assert refreshed["identity_mapping_status"] == source["identity_mapping_status"]
    with sqlite3.connect(detail) as connection:
        assert connection.execute(
            """
            SELECT identity_index_revision, identity_mapped_at,
                   identity_mapping_status
            FROM source_files
            """
        ).fetchall() == detail_metadata_before
        assert connection.execute(
            "SELECT * FROM mesh_peer_mapping ORDER BY peer_mac_normalized"
        ).fetchall() == mapping_before


def test_identity_remap_maintenance_plan_is_read_only_and_apply_reuses_service(
    tmp_path: Path,
) -> None:
    paths, profile, _result = _preview(tmp_path)
    index = MeshMrRepository(paths.mesh_mr_db_path("demo", profile.safe_folder_name))
    sources = index.list_source_files()
    protected = [
        paths.mesh_catalog_path("demo"),
        paths.mesh_mr_db_path("demo", profile.safe_folder_name),
        *(Path(str(source["parsed_db_path"])) for source in sources),
        *(Path(str(source["archived_path"])) for source in sources),
    ]
    before = {path: sha256_file(path) for path in protected if path.is_file()}

    plan = build_identity_remap_plan(
        paths,
        "demo",
        profile_filter=profile.mr_id,
    )
    dry_run = identity_remap_manifest(plan, site_name="demo")

    assert dry_run["mode"] == "dry-run"
    assert dry_run["sources_scanned"] == 2
    assert dry_run["eligible_sources"] == 2
    assert dry_run["distinct_peers"] == 1
    assert dry_run["distinct_peer_occurrences"] == 2
    assert "30f5277a5a2f" not in json.dumps(dry_run)
    assert before == {
        path: sha256_file(path) for path in protected if path.is_file()
    }

    applied = apply_identity_remap_plan(paths, "demo", plan)

    assert applied["succeeded"] == 2
    assert applied["failed"] == 0
    assert applied["skipped"] == 0
    assert all(
        item["identity_remap"]["validation_status"] == "passed"
        for item in applied["results"]
    )
    assert all(
        sha256_file(Path(str(source["archived_path"])))
        == before[Path(str(source["archived_path"]))]
        for source in sources
    )


def test_identity_remap_maintenance_apply_isolates_source_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, profile, _result = _preview(tmp_path)
    plan = build_identity_remap_plan(
        paths,
        "demo",
        profile_filter=profile.mr_id,
    )
    calls: list[str] = []

    def rebuild_source(_self, _site: str, session_id: str):
        calls.append(session_id)
        if session_id == plan[0].session_id:
            raise RuntimeError("synthetic failure")
        return {"identity_remap": {"validation_status": "passed"}}

    monkeypatch.setattr(MeshSourceRebuildService, "rebuild_source", rebuild_source)

    result = apply_identity_remap_plan(paths, "demo", plan)

    assert calls == [entry.session_id for entry in plan]
    assert result["succeeded"] == 1
    assert result["failed"] == 1
    assert result["skipped"] == 0


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

    captured_kwargs: dict[str, object] = {}

    class CancelledService:
        def __init__(self, _paths: PathResolver) -> None:
            pass

        def rebuild_source(self, *_args, **_kwargs):
            captured_kwargs.update(_kwargs)
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
    assert captured_kwargs["force_reparse"] is True
