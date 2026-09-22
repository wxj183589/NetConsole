from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

import pytest

import netconsole.services.mesh_production_authority as authority_module
from netconsole.core.paths import PathResolver
from netconsole.core.runtime_environment import write_data_environment
from netconsole.core.runtime_mode import DataEnvironmentInfo, DataEnvironmentMode
from netconsole.services.mesh_write_authority import (
    MESH_DERIVED_REBUILD_AUTHORIZED,
    MESH_IDENTITY_REMAP_AUTHORIZED,
    MESH_SOURCE_DELETE_AUTHORIZED,
    MESH_SOURCE_DELETE_OPERATION,
    MeshProductionAuthorizationError,
    MeshProductionSiteScope,
    build_mesh_write_plan,
    mesh_operation_lock,
    mesh_source_revisions,
    require_mesh_write_authority,
    resolve_mesh_production_scope,
    validate_mesh_write_plan,
)
import scripts.maintenance.rebuild_mesh_parsed_data as rebuild_module
from scripts.maintenance.rebuild_mesh_parsed_data import build_plan as build_rebuild_plan
from scripts.maintenance.rebuild_mesh_parsed_data import apply_plan as apply_rebuild_plan
from scripts.maintenance.remap_mesh_identity import apply_plan as apply_identity_plan


def _relocated_production_fixture(tmp_path: Path) -> tuple[PathResolver, Path]:
    root = tmp_path / "relocated-production"
    write_data_environment(
        root,
        DataEnvironmentInfo(
            DataEnvironmentMode.PRODUCTION,
            created_from="mesh-production-authority-test",
            readonly_warning=True,
        ),
    )
    site_root = root / "sites" / "relocated-sxl1"
    site_root.mkdir(parents=True)
    config = root / "config"
    config.mkdir(parents=True)
    (config / "site_registry.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "sites": [
                    {
                        "site_id": "sxl1",
                        "display_name": "绍兴地铁1号线",
                        "relative_path": "sites/relocated-sxl1",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return PathResolver(data_root=root), site_root


def test_relocated_production_scope_is_registry_bound_and_token_specific(tmp_path: Path) -> None:
    paths, site_root = _relocated_production_fixture(tmp_path)

    scope = resolve_mesh_production_scope(paths, "sxl1")

    assert scope.canonical_site_id == "sxl1"
    assert scope.site_root == site_root.resolve()
    assert scope.directory_name == "relocated-sxl1"
    with pytest.raises(MeshProductionAuthorizationError, match="MESH_DERIVED_REBUILD_AUTHORIZED"):
        require_mesh_write_authority(
            paths,
            "sxl1",
            operation="mesh_derived_rebuild",
            allow_production_write=True,
        )

    authorized = require_mesh_write_authority(
        paths,
        "sxl1",
        operation="mesh_derived_rebuild",
        allow_production_write=True,
        authorization_token=MESH_DERIVED_REBUILD_AUTHORIZED,
    )
    assert authorized == scope

    with pytest.raises(MeshProductionAuthorizationError, match="MESH_IDENTITY_REMAP_AUTHORIZED"):
        require_mesh_write_authority(
            paths,
            "sxl1",
            operation="mesh_identity_remap",
            allow_production_write=True,
            authorization_token=MESH_DERIVED_REBUILD_AUTHORIZED,
        )
    assert MESH_IDENTITY_REMAP_AUTHORIZED != MESH_DERIVED_REBUILD_AUTHORIZED


def test_rebuild_plan_contains_stable_authority_binding(tmp_path: Path) -> None:
    paths = PathResolver(data_root=tmp_path)

    plan = build_rebuild_plan(paths, "missing")

    assert plan == []


def test_rebuild_production_plan_resolves_authority_before_maintenance_constructor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, _site_root = _relocated_production_fixture(tmp_path)
    calls: list[str] = []
    original_resolver = rebuild_module.resolve_mesh_production_scope

    def resolver(*args, **kwargs):
        calls.append("authority")
        return original_resolver(*args, **kwargs)

    class FakeMaintenance:
        def __init__(self, _paths):
            assert calls == ["authority"]

        def inspect(self, _site, *, profile_ids=None):
            return {"profiles": []}

    monkeypatch.setattr(rebuild_module, "resolve_mesh_production_scope", resolver)
    monkeypatch.setattr(rebuild_module, "MeshDerivedDataMaintenanceService", FakeMaintenance)

    assert rebuild_module.build_plan(paths, "sxl1") == []


def test_direct_production_apply_requires_operation_capability_token(
    tmp_path: Path,
) -> None:
    paths, _site_root = _relocated_production_fixture(tmp_path)

    with pytest.raises(MeshProductionAuthorizationError, match="MESH_DERIVED_REBUILD_AUTHORIZED"):
        apply_rebuild_plan(
            paths,
            "sxl1",
            [],
            allow_production_write=True,
        )
    with pytest.raises(MeshProductionAuthorizationError, match="MESH_IDENTITY_REMAP_AUTHORIZED"):
        apply_identity_plan(
            paths,
            "sxl1",
            [],
            allow_production_write=True,
            authorization_token=MESH_DERIVED_REBUILD_AUTHORIZED,
        )
    assert apply_identity_plan(
        paths,
        "sxl1",
        [],
        allow_production_write=True,
        authorization_token=MESH_IDENTITY_REMAP_AUTHORIZED,
    )["succeeded"] == 0


def test_mesh_operation_lock_is_shared_across_mutating_operations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, site_root = _relocated_production_fixture(tmp_path)
    scope = MeshProductionSiteScope(
        canonical_site_id="sxl1",
        directory_name=site_root.name,
        site_root=site_root,
        is_production=True,
    )
    keys: list[str] = []

    @contextmanager
    def fake_lock(_paths, key: str):
        keys.append(key)
        yield

    monkeypatch.setattr(authority_module, "database_maintenance_lock", fake_lock)
    with mesh_operation_lock(
        paths,
        scope,
        "mesh_identity_remap",
        profile_id="mr-ct",
        source_id="1",
    ):
        pass
    with mesh_operation_lock(
        paths,
        scope,
        "mesh_derived_rebuild",
        profile_id="other-profile",
        source_id="99",
    ):
        pass

    assert len(keys) == 2
    assert keys[0] == keys[1]


def test_source_delete_has_independent_capability_and_tamper_evident_plan(
    tmp_path: Path,
) -> None:
    scope = MeshProductionSiteScope(
        canonical_site_id="sxl1",
        directory_name="relocated-sxl1",
        site_root=tmp_path,
        is_production=True,
    )
    revisions = mesh_source_revisions(
        "mr-1",
        "7",
        {"raw_sha256": "raw-v1", "content_sha256": "content-v1"},
    )
    plan = build_mesh_write_plan(
        scope,
        profile_id="mr-1",
        source_id="7",
        operation=MESH_SOURCE_DELETE_OPERATION,
        explicit_confirmation=True,
        **revisions,
        raw_sha256="raw-v1",
        content_sha256="content-v1",
        delete_raw_archive=False,
    )

    assert plan["plan_digest"]
    assert validate_mesh_write_plan(
        plan,
        scope,
        operation=MESH_SOURCE_DELETE_OPERATION,
        profile_id="mr-1",
        source_id="7",
        explicit_confirmation=True,
        **revisions,
        raw_sha256="raw-v1",
        content_sha256="content-v1",
        delete_raw_archive=False,
    )["plan_digest"] == plan["plan_digest"]
    tampered = {**plan, "delete_raw_archive": True}
    with pytest.raises(MeshProductionAuthorizationError, match="PLAN_DIGEST_INVALID"):
        validate_mesh_write_plan(
            tampered,
            scope,
            operation=MESH_SOURCE_DELETE_OPERATION,
            profile_id="mr-1",
            source_id="7",
            explicit_confirmation=True,
            **revisions,
            raw_sha256="raw-v1",
            content_sha256="content-v1",
            delete_raw_archive=True,
        )
    assert MESH_SOURCE_DELETE_AUTHORIZED != MESH_DERIVED_REBUILD_AUTHORIZED
