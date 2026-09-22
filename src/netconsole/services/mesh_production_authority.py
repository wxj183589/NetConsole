"""Canonical authority boundary for mutating MESH maintenance operations.

The generic ``--allow-production-write`` switch is deliberately only operator
intent.  MESH writers must also resolve the persisted canonical Site Registry
binding and present an operation-specific capability token before constructing
any MESH repository or service.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Mapping

from netconsole.core.paths import PathResolver
from netconsole.core.runtime_environment import (
    ProductionWriteBlockedError,
    data_environment,
    require_data_root_write_allowed,
)
from netconsole.services.production_database_maintenance import (
    ProductionMaintenanceError,
    resolve_production_site_scope,
    resolve_production_site_scope_by_directory,
)
from netconsole.services.database_upgrade.coordinator import database_maintenance_lock
from netconsole.repositories.mesh_mr_repository import MeshMrRepository
from netconsole.services.ap_identity.normalizers import normalize_mac_key
from netconsole.services.mesh_peer_mapping_service import MeshPeerMappingService


MESH_DERIVED_REBUILD_OPERATION = "mesh_derived_rebuild"
MESH_IDENTITY_REMAP_OPERATION = "mesh_identity_remap"
MESH_SOURCE_DELETE_OPERATION = "mesh_source_delete"
MESH_DERIVED_REBUILD_AUTHORIZED = "MESH_DERIVED_REBUILD_AUTHORIZED"
MESH_IDENTITY_REMAP_AUTHORIZED = "MESH_IDENTITY_REMAP_AUTHORIZED"
MESH_SOURCE_DELETE_AUTHORIZED = "MESH_SOURCE_DELETE_AUTHORIZED"

_OPERATION_TOKENS = {
    MESH_DERIVED_REBUILD_OPERATION: MESH_DERIVED_REBUILD_AUTHORIZED,
    MESH_IDENTITY_REMAP_OPERATION: MESH_IDENTITY_REMAP_AUTHORIZED,
    MESH_SOURCE_DELETE_OPERATION: MESH_SOURCE_DELETE_AUTHORIZED,
}


class MeshProductionAuthorizationError(ProductionWriteBlockedError):
    """MESH write authority was not proven for the requested operation."""


@dataclass(frozen=True)
class MeshProductionSiteScope:
    """The canonical site identity and its registry-bound directory."""

    canonical_site_id: str
    directory_name: str
    site_root: Path
    is_production: bool


def resolve_mesh_production_scope(
    paths: PathResolver,
    site_ref: str,
) -> MeshProductionSiteScope:
    """Resolve a MESH site without discovering or creating repository state.

    Development/test roots retain the existing directory-based behavior.  A
    Production root must resolve through the persisted allowlisted Site
    Registry; ``site_ref`` may be either its canonical ID or its registered
    directory name.  The returned directory name is what legacy MESH path
    helpers require, while ``canonical_site_id`` is the stable plan identity.
    """

    environment = data_environment(paths.data_root)
    if not environment.is_production:
        raw_site = str(site_ref or "").strip()
        site_root = paths.site_dir(raw_site).resolve()
        return MeshProductionSiteScope(
            canonical_site_id=raw_site,
            directory_name=site_root.name,
            site_root=site_root,
            is_production=False,
        )

    requested = str(site_ref or "").strip()
    try:
        canonical_site_id, site_root = resolve_production_site_scope(paths, requested)
    except ProductionMaintenanceError as by_id_error:
        try:
            canonical_site_id, site_root = resolve_production_site_scope_by_directory(
                paths,
                requested,
            )
        except ProductionMaintenanceError:
            raise MeshProductionAuthorizationError(
                "MESH_PRODUCTION_SITE_NOT_CANONICAL"
            ) from by_id_error
    resolved_root = Path(site_root).resolve()
    return MeshProductionSiteScope(
        canonical_site_id=canonical_site_id,
        directory_name=resolved_root.name,
        site_root=resolved_root,
        is_production=True,
    )


def require_mesh_write_authority(
    paths: PathResolver,
    site_ref: str,
    *,
    operation: str,
    allow_production_write: bool = False,
    authorization_token: str = "",
) -> MeshProductionSiteScope:
    """Prove the MESH operation may write, before any MESH constructor runs.

    ``allow_production_write`` is intentionally passed to the generic runtime
    gate only.  Production additionally requires the exact operation token;
    one MESH operation token can never authorize another operation.
    """

    scope = resolve_mesh_production_scope(paths, site_ref)
    if not scope.is_production:
        require_data_root_write_allowed(
            paths.data_root,
            operation,
            allow_production_write=allow_production_write,
        )
        return scope

    require_data_root_write_allowed(
        paths.data_root,
        operation,
        allow_production_write=allow_production_write,
    )
    expected = _OPERATION_TOKENS.get(str(operation))
    if expected is None:
        raise MeshProductionAuthorizationError(
            f"MESH_OPERATION_NOT_ALLOWLISTED: {operation}"
        )
    if str(authorization_token or "") != expected:
        raise MeshProductionAuthorizationError(
            f"MESH_OPERATION_AUTHORIZATION_REQUIRED: {expected}"
        )
    return scope


def expected_mesh_authorization_token(operation: str) -> str:
    """Return the capability token expected for one allowlisted operation."""

    try:
        return _OPERATION_TOKENS[str(operation)]
    except KeyError as exc:
        raise MeshProductionAuthorizationError(
            f"MESH_OPERATION_NOT_ALLOWLISTED: {operation}"
        ) from exc


def stable_plan_digest(value: Mapping[str, object]) -> str:
    """Hash a JSON-compatible plan body with deterministic key ordering."""

    return hashlib.sha256(
        json.dumps(
            dict(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def mesh_plan_digest(value: Mapping[str, object]) -> str:
    """Compatibility alias for callers that name the digest after MESH."""

    return stable_plan_digest(value)


def mesh_source_revisions(
    profile_id: str,
    source_id: str | int,
    source: Mapping[str, object],
) -> dict[str, str]:
    """Build deterministic source/catalog revisions for a task plan.

    The MESH source index does not expose one monotonically increasing row
    revision.  Binding the complete read-only source row gives the worker a
    conservative compare-and-apply contract without changing the index
    schema.  The catalog revision includes the profile/source identity so a
    row moving between profiles cannot accidentally validate.
    """

    source_payload = dict(source)
    return {
        "source_revision": stable_plan_digest({"source": source_payload}),
        "catalog_revision": stable_plan_digest(
            {
                "profile_id": str(profile_id),
                "source_id": str(source_id),
                "source": source_payload,
            }
        ),
    }


def build_mesh_write_plan(
    scope: MeshProductionSiteScope,
    *,
    profile_id: str,
    source_id: str | int,
    operation: str,
    explicit_confirmation: bool,
    source_revision: str,
    catalog_revision: str,
    safe_folder_name: str = "",
    source_index_sha256: str = "",
    parsed_sha256: str = "",
    peer_set_digest: str = "",
    identity_snapshot_revision: int = 0,
    raw_sha256: str = "",
    content_sha256: str = "",
    identity_index_revision: int = 0,
    maintenance_kind: str = "",
    force_reparse: bool = False,
    delete_raw_archive: bool = False,
    delete_parsed_data: bool = True,
    delete_generated_reports: bool = True,
) -> dict[str, object]:
    """Create a JSON-safe immutable-by-digest source operation plan."""

    body: dict[str, object] = {
        "canonical_site_id": str(scope.canonical_site_id),
        "site_directory_name": str(scope.directory_name),
        "profile_id": str(profile_id),
        "source_id": str(source_id),
        "operation": str(operation),
        "explicit_confirmation": bool(explicit_confirmation),
        "source_revision": str(source_revision or ""),
        "catalog_revision": str(catalog_revision or ""),
        "safe_folder_name": str(safe_folder_name or ""),
        "source_index_sha256": str(source_index_sha256 or ""),
        "parsed_sha256": str(parsed_sha256 or ""),
        "peer_set_digest": str(peer_set_digest or ""),
        "identity_snapshot_revision": int(identity_snapshot_revision or 0),
        "raw_sha256": str(raw_sha256 or ""),
        "content_sha256": str(content_sha256 or ""),
        "identity_index_revision": int(identity_index_revision or 0),
        "maintenance_kind": str(maintenance_kind or ""),
        "force_reparse": bool(force_reparse),
        "delete_raw_archive": bool(delete_raw_archive),
        "delete_parsed_data": bool(delete_parsed_data),
        "delete_generated_reports": bool(delete_generated_reports),
    }
    return {**body, "plan_digest": stable_plan_digest(body)}


def validate_mesh_write_plan(
    plan: Mapping[str, object],
    scope: MeshProductionSiteScope,
    *,
    operation: str,
    profile_id: str,
    source_id: str | int,
    explicit_confirmation: bool,
    source_revision: str,
    catalog_revision: str,
    safe_folder_name: str = "",
    source_index_sha256: str = "",
    parsed_sha256: str = "",
    peer_set_digest: str = "",
    identity_snapshot_revision: int = 0,
    raw_sha256: str = "",
    content_sha256: str = "",
    identity_index_revision: int = 0,
    maintenance_kind: str = "",
    force_reparse: bool = False,
    delete_raw_archive: bool = False,
    delete_parsed_data: bool = True,
    delete_generated_reports: bool = True,
) -> dict[str, object]:
    """Fail closed when the submitted plan no longer matches current facts."""

    selected = dict(plan or {})
    provided_digest = str(selected.pop("plan_digest", "") or "")
    if not provided_digest or provided_digest != stable_plan_digest(selected):
        raise MeshProductionAuthorizationError("MESH_SOURCE_PLAN_DIGEST_INVALID")
    expected = build_mesh_write_plan(
        scope,
        profile_id=profile_id,
        source_id=source_id,
        operation=operation,
        explicit_confirmation=explicit_confirmation,
        source_revision=source_revision,
        catalog_revision=catalog_revision,
        safe_folder_name=safe_folder_name,
        source_index_sha256=source_index_sha256,
        parsed_sha256=parsed_sha256,
        peer_set_digest=peer_set_digest,
        identity_snapshot_revision=identity_snapshot_revision,
        raw_sha256=raw_sha256,
        content_sha256=content_sha256,
        identity_index_revision=identity_index_revision,
        maintenance_kind=maintenance_kind,
        force_reparse=force_reparse,
        delete_raw_archive=delete_raw_archive,
        delete_parsed_data=delete_parsed_data,
        delete_generated_reports=delete_generated_reports,
    )
    if selected != {key: value for key, value in expected.items() if key != "plan_digest"}:
        raise MeshProductionAuthorizationError("MESH_SOURCE_PLAN_STALE")
    if not bool(selected.get("explicit_confirmation")):
        raise MeshProductionAuthorizationError("MESH_SOURCE_CONFIRMATION_REQUIRED")
    return {**selected, "plan_digest": provided_digest}


def mesh_source_plan_facts(
    paths: PathResolver,
    scope: MeshProductionSiteScope,
    context: object,
) -> dict[str, object]:
    """Read and bind the current source/detail/identity facts without writes."""

    safe_folder_name = str(getattr(context, "safe_folder_name", "") or "")
    if (
        not safe_folder_name
        or safe_folder_name in {".", ".."}
        or Path(safe_folder_name).name != safe_folder_name
        or "/" in safe_folder_name
        or "\\" in safe_folder_name
    ):
        raise MeshProductionAuthorizationError("MESH_PROFILE_IDENTITY_INVALID")
    mesh_root = paths.site_mesh_root(scope.directory_name)
    profile_root = paths.mesh_mr_root(scope.directory_name, safe_folder_name)
    index_path = Path(getattr(context, "index_db")).absolute()
    detail_value = getattr(context, "detail_db", None)
    raw_value = getattr(context, "raw_path", None)
    detail_path = Path(detail_value).absolute() if detail_value is not None else None
    raw_path = Path(raw_value).absolute() if raw_value is not None else None
    if scope.is_production:
        for label, candidate in (
            ("mesh_root", mesh_root),
            ("profile_root", profile_root),
            ("source_index", index_path),
            ("parsed_db", detail_path),
            ("raw_source", raw_path),
        ):
            if candidate is not None:
                _require_production_mesh_path(scope, mesh_root, candidate, label)
    source_index_sha256 = _file_sha256(index_path)
    parsed_sha256 = _file_sha256(detail_path) if detail_path is not None else ""
    raw_sha256 = _file_sha256(raw_path) if raw_path is not None else ""
    peer_keys: tuple[str, ...] = ()
    if detail_path is not None and detail_path.is_file():
        peer_keys = tuple(
            sorted(
                {
                    key
                    for peer in MeshMrRepository(detail_path, read_only=True).distinct_peer_macs()
                    if (key := normalize_mac_key(peer))
                }
            )
        )
    peer_set_digest = stable_plan_digest({"peer_keys": list(peer_keys)})
    identity_snapshot_revision = MeshPeerMappingService(
        scope.directory_name,
        paths,
    ).current_identity_revision()
    return {
        "safe_folder_name": safe_folder_name,
        "source_index_sha256": source_index_sha256,
        "parsed_sha256": parsed_sha256,
        "raw_sha256": raw_sha256,
        "peer_keys": peer_keys,
        "peer_set_digest": peer_set_digest,
        "identity_snapshot_revision": identity_snapshot_revision,
    }


def require_mesh_profile_scope(
    paths: PathResolver,
    scope: MeshProductionSiteScope,
    safe_folder_name: str,
) -> Path:
    """Validate a catalog profile identity before any profile file is read."""

    value = str(safe_folder_name or "")
    if (
        not value
        or value in {".", ".."}
        or Path(value).name != value
        or "/" in value
        or "\\" in value
    ):
        raise MeshProductionAuthorizationError("MESH_PROFILE_IDENTITY_INVALID")
    profile_root = paths.mesh_mr_root(scope.directory_name, value)
    if scope.is_production:
        mesh_root = paths.site_mesh_root(scope.directory_name)
        for label, candidate in (
            ("profile_root", profile_root),
            ("raw_root", paths.mesh_mr_raw_dir(scope.directory_name, value)),
            ("parsed_root", paths.mesh_mr_parsed_dir(scope.directory_name, value)),
            ("source_index", paths.mesh_mr_db_path(scope.directory_name, value)),
        ):
            _require_production_mesh_path(scope, mesh_root, candidate, label)
    return profile_root.resolve()


def _require_production_mesh_path(
    scope: MeshProductionSiteScope,
    mesh_root: Path,
    candidate: Path,
    label: str,
) -> None:
    raw_mesh_root = mesh_root.absolute()
    raw_candidate = candidate.absolute()
    resolved_mesh_root = raw_mesh_root.resolve()
    resolved_candidate = raw_candidate.resolve()
    if (
        resolved_mesh_root != scope.site_root
        and not resolved_mesh_root.is_relative_to(scope.site_root)
    ):
        raise MeshProductionAuthorizationError("MESH_ROOT_OUTSIDE_CANONICAL_SITE")
    if (
        resolved_candidate != resolved_mesh_root
        and not resolved_candidate.is_relative_to(resolved_mesh_root)
    ):
        raise MeshProductionAuthorizationError(f"MESH_PATH_OUTSIDE_CANONICAL_ROOT:{label}")
    current = raw_candidate
    while True:
        if _is_link_or_junction(current):
            raise MeshProductionAuthorizationError(f"MESH_REPARSE_POINT_REJECTED:{label}")
        if current == raw_mesh_root or current.parent == current:
            break
        current = current.parent


def _is_link_or_junction(path: Path) -> bool:
    if path.is_symlink():
        return True
    checker = getattr(path, "is_junction", None)
    return bool(checker()) if callable(checker) else False


def _file_sha256(path: Path | None) -> str:
    if path is None or not path.is_file() or path.is_symlink():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@contextmanager
def mesh_operation_lock(
    paths: PathResolver,
    scope: MeshProductionSiteScope,
    operation: str,
    *,
    profile_id: str = "",
    source_id: str = "",
) -> Iterator[None]:
    """Serialize one canonical MESH operation across process boundaries."""

    # The operation/profile/source are deliberately not part of the lock key.
    # All MESH writers for one canonical site must serialize against one
    # another, including CLI paths that do not carry a source identity.
    del operation, profile_id, source_id
    parts = [
        "mesh-production",
        scope.canonical_site_id,
    ]
    key = ":".join(part.replace(":", "_") for part in parts)
    with database_maintenance_lock(paths, key):
        yield


mesh_write_lock = mesh_operation_lock


__all__ = [
    "MESH_DERIVED_REBUILD_AUTHORIZED",
    "MESH_DERIVED_REBUILD_OPERATION",
    "MESH_IDENTITY_REMAP_AUTHORIZED",
    "MESH_IDENTITY_REMAP_OPERATION",
    "MESH_SOURCE_DELETE_AUTHORIZED",
    "MESH_SOURCE_DELETE_OPERATION",
    "MeshProductionAuthorizationError",
    "MeshProductionSiteScope",
    "expected_mesh_authorization_token",
    "build_mesh_write_plan",
    "mesh_operation_lock",
    "mesh_plan_digest",
    "mesh_source_revisions",
    "mesh_source_plan_facts",
    "require_mesh_profile_scope",
    "mesh_write_lock",
    "require_mesh_write_authority",
    "resolve_mesh_production_scope",
    "stable_plan_digest",
    "validate_mesh_write_plan",
]
