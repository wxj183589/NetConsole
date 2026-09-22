from __future__ import annotations

from pathlib import Path

from netconsole.services.background_job import BackgroundJob
from netconsole.services.job_center.job_runner import run_job
from netconsole.services.mesh_write_authority import (
    MESH_IDENTITY_REMAP_OPERATION,
    MESH_SOURCE_DELETE_OPERATION,
    MeshProductionSiteScope,
    build_mesh_write_plan,
    mesh_source_plan_facts,
    mesh_source_revisions,
    resolve_mesh_production_scope,
)
from netconsole.services.rail_transit.mesh_analysis_query_service import (
    MeshAnalysisQueryService,
)
from tests.support.mesh_analysis_test_support import (
    EmptyBaseQuery,
    create_mesh_analysis_fixture,
)


def _identity_job(
    paths,
    session_id: str,
    *,
    force_reparse: bool = False,
) -> BackgroundJob:
    query = MeshAnalysisQueryService(
        paths,
        base_query=EmptyBaseQuery(),  # type: ignore[arg-type]
        schedule_catalog_index=False,
    )
    context = query._context("demo", session_id)
    revisions = mesh_source_revisions(context.mr_id, context.source_id, context.source)
    scope = resolve_mesh_production_scope(paths, "demo")
    facts = mesh_source_plan_facts(paths, scope, context)
    plan = build_mesh_write_plan(
        scope,
        profile_id=context.mr_id,
        source_id=context.source_id,
        operation=MESH_IDENTITY_REMAP_OPERATION,
        explicit_confirmation=True,
        **revisions,
        safe_folder_name=str(facts["safe_folder_name"]),
        source_index_sha256=str(facts["source_index_sha256"]),
        parsed_sha256=str(facts["parsed_sha256"]),
        peer_set_digest=str(facts["peer_set_digest"]),
        identity_snapshot_revision=int(facts["identity_snapshot_revision"]),
        raw_sha256=str(facts["raw_sha256"]),
        content_sha256=str(context.source.get("content_sha256") or ""),
        identity_index_revision=int(context.source.get("identity_index_revision") or 0),
        maintenance_kind="identity_projection_refresh",
        force_reparse=force_reparse,
    )
    return BackgroundJob(
        job_id="mesh-authority-test",
        task_type="mesh_analysis_maintenance",
        params={
            "app_root": str(paths.app_root),
            "data_root": str(paths.data_root),
            "site_name": "demo",
            "session_id": session_id,
            "maintenance_kind": "identity_projection_refresh",
            "force_reparse": force_reparse,
            "explicit_confirmation": True,
            "mesh_write_plan": plan,
            "mesh_authorization_token": "",
        },
    )


def test_worker_rejects_identity_plan_force_reparse_tampering_before_service(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths, session_id, _detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    job = _identity_job(paths, session_id, force_reparse=False)
    job.params["force_reparse"] = True
    called = {"value": False}

    class ForbiddenService:
        def __init__(self, _paths):
            called["value"] = True

        def rebuild_source(self, *_args, **_kwargs):
            called["value"] = True
            return {}

    monkeypatch.setattr(
        "netconsole.services.job_center.handlers.mesh_jobs.MeshSourceRebuildService",
        ForbiddenService,
    )
    result = run_job(job)

    assert result.ok is False
    assert result.error == "MESH_MAINTENANCE_PARAMS_INVALID"
    assert called["value"] is False


def test_worker_validates_plan_before_running_identity_only_service(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths, session_id, _detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    job = _identity_job(paths, session_id, force_reparse=False)
    captured: dict[str, object] = {}

    class FakeService:
        def __init__(self, _paths):
            pass

        def remap_identity_only(self, *_args, **kwargs):
            captured.update(kwargs)
            return {"parsed_record_count": 1}

    monkeypatch.setattr(
        "netconsole.services.job_center.handlers.mesh_jobs.MeshSourceRebuildService",
        FakeService,
    )
    result = run_job(job)

    assert result.ok is True
    assert captured["expected_peer_keys"]


def test_worker_allows_parsed_only_delete_but_blocks_production_raw_delete(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths, session_id, _detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    query = MeshAnalysisQueryService(paths, schedule_catalog_index=False)
    current = query._context("demo", session_id)
    revisions = mesh_source_revisions(current.mr_id, current.source_id, current.source)
    scope = resolve_mesh_production_scope(paths, "demo")
    facts = mesh_source_plan_facts(paths, scope, current)
    plan = build_mesh_write_plan(
        scope,
        profile_id=current.mr_id,
        source_id=current.source_id,
        operation=MESH_SOURCE_DELETE_OPERATION,
        explicit_confirmation=True,
        **revisions,
        safe_folder_name=str(facts["safe_folder_name"]),
        source_index_sha256=str(facts["source_index_sha256"]),
        parsed_sha256=str(facts["parsed_sha256"]),
        raw_sha256=str(facts["raw_sha256"]),
        content_sha256=str(current.source.get("content_sha256") or ""),
        delete_raw_archive=False,
        delete_parsed_data=True,
        delete_generated_reports=True,
    )
    job = BackgroundJob(
        job_id="mesh-delete-authority-test",
        task_type="mesh_analysis_source_delete",
        params={
            "app_root": str(paths.app_root),
            "data_root": str(paths.data_root),
            "site_name": "demo",
            "session_id": session_id,
            "delete_raw_archive": False,
            "delete_parsed_data": True,
            "delete_generated_reports": True,
            "explicit_confirmation": True,
            "mesh_write_plan": plan,
            "mesh_plan_digest": plan["plan_digest"],
            "mesh_canonical_site_id": "demo",
            "mesh_profile_id": plan["profile_id"],
            "mesh_source_id": plan["source_id"],
            "mesh_operation": MESH_SOURCE_DELETE_OPERATION,
            "mesh_authorization_token": "",
        },
    )
    captured: dict[str, object] = {}

    class FakeDelete:
        def __init__(self, _paths):
            pass

        def delete_source(self, *_args, **kwargs):
            captured.update(kwargs)
            return {"already_deleted": False}

    monkeypatch.setattr(
        "netconsole.services.job_center.handlers.mesh_jobs.MeshSourceDeleteService",
        FakeDelete,
    )
    assert run_job(job).ok is True
    assert captured["delete_raw_archive"] is False

    production_scope = MeshProductionSiteScope(
        canonical_site_id="sxl1",
        directory_name="demo",
        site_root=paths.site_dir("demo"),
        is_production=True,
    )
    raw_plan = build_mesh_write_plan(
        production_scope,
        profile_id=current.mr_id,
        source_id=current.source_id,
        operation=MESH_SOURCE_DELETE_OPERATION,
        explicit_confirmation=True,
        **revisions,
        raw_sha256=str(current.source.get("raw_sha256") or current.source.get("sha256") or ""),
        content_sha256=str(current.source.get("content_sha256") or ""),
        delete_raw_archive=True,
        delete_parsed_data=True,
        delete_generated_reports=True,
    )
    raw_job = BackgroundJob(
        job_id="mesh-raw-delete-authority-test",
        task_type="mesh_analysis_source_delete",
        params={
            **job.params,
            "mesh_write_plan": raw_plan,
            "mesh_plan_digest": raw_plan["plan_digest"],
            "mesh_canonical_site_id": "sxl1",
            "mesh_profile_id": raw_plan["profile_id"],
            "mesh_source_id": raw_plan["source_id"],
            "delete_raw_archive": True,
            "mesh_authorization_token": "MESH_SOURCE_DELETE_AUTHORIZED",
        },
    )
    monkeypatch.setattr(
        "netconsole.services.job_center.handlers.mesh_jobs.resolve_mesh_production_scope",
        lambda *_args, **_kwargs: production_scope,
    )
    monkeypatch.setattr(
        "netconsole.services.job_center.handlers.mesh_jobs.require_mesh_write_authority",
        lambda *_args, **_kwargs: production_scope,
    )
    blocked = run_job(raw_job)
    assert blocked.ok is False
    assert blocked.error == "MESH_PRODUCTION_RAW_DELETE_UNSUPPORTED"
