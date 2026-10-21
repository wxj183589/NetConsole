"""Immutable HTTP authority for database maintenance jobs.

This module is intentionally a narrow boundary around the current database
upgrade service.  It binds the canonical site, MESH Profile/backup target and
the observable SQLite/WAL state at submission time, then repeats the checks
inside the worker and immediately before each mutator.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

from netconsole.core.paths import PathResolver
from netconsole.core.runtime_environment import (
    data_environment,
    production_write_allowed,
    require_data_root_write_allowed,
)
from netconsole.repositories.mesh_mr_repository import SCHEMA_VERSION as MESH_SCHEMA_VERSION
from netconsole.services.database_upgrade.backup_store import DatabaseBackupStore
from netconsole.services.database_upgrade.sqlite_consistency import validate_sqlite
from netconsole.services.mesh_derived_data_maintenance_service import (
    MeshDerivedDataMaintenanceService,
)
from netconsole.services.mesh_production_authority import resolve_mesh_production_scope
from netconsole.services.rail_transit.mesh_analysis_query_service import MeshAnalysisQueryService


DATABASE_UPGRADE_AUTHORIZED = "DATABASE_UPGRADE_AUTHORIZED"
DATABASE_BACKUP_CREATE_AUTHORIZED = "DATABASE_BACKUP_CREATE_AUTHORIZED"
DATABASE_BACKUP_RESTORE_AUTHORIZED = "DATABASE_BACKUP_RESTORE_AUTHORIZED"
DATABASE_BACKUP_DELETE_AUTHORIZED = "DATABASE_BACKUP_DELETE_AUTHORIZED"
LEGACY_DATABASE_ARCHIVE_MIGRATION_AUTHORIZED = "LEGACY_DATABASE_ARCHIVE_MIGRATION_AUTHORIZED"
READ_ONLY_VALIDATION = "READ_ONLY_VALIDATION"
AUTHORITY_SCHEMA_VERSION = 1
STARTUP_RECOVERY_AUTHORITY = "DATABASE_STARTUP_RECOVERY_AUTHORITY"
STARTUP_RECOVERY_SOURCE_AUTHORITY = "SOURCE_AUTHORITY"
STARTUP_RECOVERY_LEGACY_MESH_ADAPTER = "LEGACY_MESH_REBUILD_ADAPTER"
STARTUP_RECOVERY_TEST_ADAPTER = "TEST_SYNTHETIC_ADAPTER"
STARTUP_RECOVERY_PRODUCTION_MAINTENANCE_ADAPTER = "PRODUCTION_MAINTENANCE_ADAPTER"

_PRODUCTION_MAINTENANCE_DATABASES = frozenset({"devices.db", "tasks.db"})
_PRODUCTION_MAINTENANCE_EVIDENCE_KEYS = frozenset(
    {
        "current_implementation_head",
        "rehearsal_evidence_head",
        "source_snapshot_identity",
        "manifest_generated_head",
        "storage_registry_sha256",
        "production_maintenance_script_sha256",
    }
)

_OPERATION_BY_TASK: dict[str, tuple[str, str]] = {
    "database_upgrade": ("DATABASE_UPGRADE", DATABASE_UPGRADE_AUTHORIZED),
    "database_batch_upgrade": ("DATABASE_UPGRADE", DATABASE_UPGRADE_AUTHORIZED),
    "database_batch_backup": ("DATABASE_BACKUP_CREATE", DATABASE_BACKUP_CREATE_AUTHORIZED),
    "database_backup_validation": (READ_ONLY_VALIDATION, ""),
    "legacy_database_archive_migration": (
        "LEGACY_DATABASE_ARCHIVE_MIGRATION",
        LEGACY_DATABASE_ARCHIVE_MIGRATION_AUTHORIZED,
    ),
    "database_backup_restore": ("DATABASE_BACKUP_RESTORE", DATABASE_BACKUP_RESTORE_AUTHORIZED),
    "database_backup_delete": ("DATABASE_BACKUP_DELETE", DATABASE_BACKUP_DELETE_AUTHORIZED),
    "database_backup_batch_delete": ("DATABASE_BACKUP_DELETE", DATABASE_BACKUP_DELETE_AUTHORIZED),
}
_PROFILE_TASKS = frozenset({"database_upgrade", "database_batch_upgrade", "database_batch_backup"})
_BACKUP_TASKS = frozenset(
    {
        "database_backup_validation",
        "database_backup_restore",
        "database_backup_delete",
        "database_backup_batch_delete",
    }
)


class DatabaseMaintenanceAuthorityError(ValueError):
    """A database maintenance scope or capability failed closed."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = str(code)
        super().__init__(message or self.code)


class DatabaseMaintenanceAuthorityCancelled(DatabaseMaintenanceAuthorityError):
    """The worker cancellation callback fired during authority checking."""


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise DatabaseMaintenanceAuthorityError("DATABASE_TARGET_UNREADABLE") from exc
    return digest.hexdigest()


_MANIFEST_BINDING_KEYS = (
    "backup_id",
    "database_kind",
    "scope_type",
    "scope_id",
    "original_database_path",
    "backup_database_path",
    "database_size",
    "database_sha256",
    "migration_strategy",
)


def _manifest_binding(item: Mapping[str, Any]) -> str:
    """Digest the immutable backup identity, excluding lifecycle metadata."""

    return _digest({key: item.get(key) for key in _MANIFEST_BINDING_KEYS})


def _is_reparse(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        return bool(int(getattr(path.lstat(), "st_file_attributes", 0) or 0) & 0x400)
    except (FileNotFoundError, OSError):
        return False


def _contained(path: Path, root: Path, code: str) -> Path:
    resolved_root = root.resolve()
    raw = Path(path).expanduser()
    resolved = raw.resolve(strict=False)
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise DatabaseMaintenanceAuthorityError(code) from exc
    current = raw
    while True:
        if _is_reparse(current):
            raise DatabaseMaintenanceAuthorityError(code)
        if current == resolved_root:
            break
        if current.parent == current:
            raise DatabaseMaintenanceAuthorityError(code)
        current = current.parent
    return resolved


def _site_binding(paths: PathResolver, site_ref: str) -> dict[str, Any]:
    try:
        scope = resolve_mesh_production_scope(paths, str(site_ref or "").strip())
    except Exception as exc:
        raise DatabaseMaintenanceAuthorityError("DATABASE_SITE_NOT_CANONICAL") from exc
    site_root = _contained(scope.site_root, paths.data_root, "DATABASE_SITE_PATH_INVALID")
    expected_root = paths.site_dir(scope.directory_name).resolve()
    if site_root != expected_root or site_root.parent != paths.sites_dir.resolve():
        raise DatabaseMaintenanceAuthorityError("DATABASE_SITE_DESCRIPTOR_MISMATCH")
    return {
        "canonical_site_id": str(scope.canonical_site_id),
        "site_directory_name": str(scope.directory_name),
        "site_root": site_root,
        "is_production": bool(scope.is_production),
    }


def _validate_production_maintenance_evidence(
    value: Mapping[str, Any],
) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise DatabaseMaintenanceAuthorityError("DATABASE_PRODUCTION_EVIDENCE_INVALID")
    result = {str(key): str(raw or "") for key, raw in value.items()}
    missing = sorted(key for key in _PRODUCTION_MAINTENANCE_EVIDENCE_KEYS if not result.get(key))
    if missing:
        raise DatabaseMaintenanceAuthorityError(
            f"DATABASE_PRODUCTION_EVIDENCE_INCOMPLETE: {','.join(missing)}"
        )
    if result["manifest_generated_head"].casefold() != result["current_implementation_head"].casefold():
        raise DatabaseMaintenanceAuthorityError("DATABASE_PRODUCTION_EVIDENCE_HEAD_MISMATCH")
    for key in ("storage_registry_sha256", "production_maintenance_script_sha256"):
        digest = result[key].casefold()
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise DatabaseMaintenanceAuthorityError("DATABASE_PRODUCTION_EVIDENCE_DIGEST_INVALID")
    return result


def _validate_production_rollback_owner(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise DatabaseMaintenanceAuthorityError("DATABASE_PRODUCTION_ROLLBACK_OWNER_INVALID")
    result = dict(value)
    required = {
        "backup_set_id",
        "site_id",
        "operation_id",
        "database",
        "source_identity",
        "schema_fingerprint",
        "rollback_required",
        "observation_state",
        "retire_state",
    }
    missing = sorted(key for key in required if not str(result.get(key) or "").strip())
    if missing:
        raise DatabaseMaintenanceAuthorityError(
            f"DATABASE_PRODUCTION_ROLLBACK_OWNER_INCOMPLETE: {','.join(missing)}"
        )
    if str(result.get("database") or "") not in _PRODUCTION_MAINTENANCE_DATABASES:
        raise DatabaseMaintenanceAuthorityError("UNSUPPORTED_DATABASE_KIND")
    if result.get("rollback_required") is not True:
        raise DatabaseMaintenanceAuthorityError("DATABASE_PRODUCTION_ROLLBACK_OWNER_INVALID")
    if str(result.get("observation_state") or "") != "VERIFIED" or str(result.get("retire_state") or "") != "PROTECT":
        raise DatabaseMaintenanceAuthorityError("DATABASE_PRODUCTION_ROLLBACK_OWNER_INVALID")
    resources = result.get("resources")
    if resources is not None:
        if not isinstance(resources, list) or not resources:
            raise DatabaseMaintenanceAuthorityError("DATABASE_PRODUCTION_ROLLBACK_OWNER_INVALID")
        return result
    for key in ("backup_sha256", "backup_relative_path"):
        if not str(result.get(key) or "").strip():
            raise DatabaseMaintenanceAuthorityError("DATABASE_PRODUCTION_ROLLBACK_OWNER_INCOMPLETE")
    try:
        if int(result.get("backup_size") or 0) <= 0:
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise DatabaseMaintenanceAuthorityError("DATABASE_PRODUCTION_ROLLBACK_OWNER_INVALID") from exc
    return result


def build_startup_recovery_authority(
    paths: PathResolver,
    *,
    operation_id: str,
    database_kind: str,
    scope_type: str,
    scope_id: str,
    active_path: Path,
    shadow_path: Path | None,
    rollback_path: Path | None,
    backup_path: Path | None,
    maintenance_lock: str,
    source_authority: Mapping[str, Any] | None = None,
    allow_legacy_mesh_adapter: bool = False,
    production_maintenance_evidence: Mapping[str, Any] | None = None,
    production_rollback_owner: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist the P7.3-F-bound identity needed by startup recovery.

    Startup recovery is not a new user-facing maintenance operation.  It is a
    continuation of an already-authorized database operation, so the journal
    carries the existing HTTP authority as evidence and adds only the exact
    operation/artifact binding required to recover it after a process exit.
    """

    selected_kind = str(database_kind or "").strip()
    selected_scope_type = str(scope_type or "").strip()
    selected_scope_id = str(scope_id or "").strip()
    selected_operation = str(operation_id or "").strip()
    if not all((selected_kind, selected_scope_type, selected_scope_id, selected_operation)):
        raise DatabaseMaintenanceAuthorityError("DATABASE_STARTUP_AUTHORITY_INCOMPLETE")
    source: dict[str, Any] = {}
    if source_authority is not None:
        if not isinstance(source_authority, Mapping):
            raise DatabaseMaintenanceAuthorityError("DATABASE_AUTHORITY_INVALID")
        _validate_digest(source_authority)
        source = dict(source_authority)
    production_evidence: dict[str, str] = {}
    if production_maintenance_evidence is not None:
        production_evidence = _validate_production_maintenance_evidence(
            production_maintenance_evidence
        )
    rollback_owner = (
        _validate_production_rollback_owner(production_rollback_owner)
        if production_rollback_owner is not None
        else None
    )
    if production_evidence and rollback_owner is None:
        raise DatabaseMaintenanceAuthorityError("DATABASE_PRODUCTION_ROLLBACK_OWNER_REQUIRED")
    if source and production_evidence:
        raise DatabaseMaintenanceAuthorityError("DATABASE_STARTUP_AUTHORITY_MODES_CONFLICT")
    if allow_legacy_mesh_adapter and production_evidence:
        raise DatabaseMaintenanceAuthorityError("DATABASE_STARTUP_AUTHORITY_MODES_CONFLICT")
    is_production = data_environment(paths.data_root).is_production
    if is_production and not source and not allow_legacy_mesh_adapter and not production_evidence:
        raise DatabaseMaintenanceAuthorityError("DATABASE_STARTUP_AUTHORITY_REQUIRED")

    site_ref = str(
        source.get("site_directory_name")
        or (
            selected_scope_id.split(":", 1)[0]
            if ":" in selected_scope_id
            else selected_scope_id if production_evidence else ""
        )
    ).strip()
    if selected_kind == "mesh_derived":
        site = _site_binding(paths, site_ref)
        prefix = f"{site['site_directory_name']}:"
        if selected_scope_type != "site_profile" or not selected_scope_id.startswith(prefix):
            raise DatabaseMaintenanceAuthorityError("DATABASE_SCOPE_NOT_CANONICAL")
        safe_profile = selected_scope_id[len(prefix) :]
        if not safe_profile or Path(safe_profile).name != safe_profile or "/" in safe_profile or "\\" in safe_profile:
            raise DatabaseMaintenanceAuthorityError("DATABASE_SCOPE_NOT_CANONICAL")
        expected_active = paths.mesh_mr_db_path(str(site["site_directory_name"]), safe_profile).resolve()
        if active_path.resolve() != expected_active:
            raise DatabaseMaintenanceAuthorityError("DATABASE_DESCRIPTOR_PATH_INVALID")
    elif is_production:
        if not production_evidence or selected_kind not in _PRODUCTION_MAINTENANCE_DATABASES:
            raise DatabaseMaintenanceAuthorityError("UNSUPPORTED_DATABASE_KIND")
        site = _site_binding(paths, site_ref)
        if selected_scope_type != "site" or selected_scope_id != str(site["canonical_site_id"]):
            raise DatabaseMaintenanceAuthorityError("DATABASE_SCOPE_NOT_CANONICAL")
        site_root = Path(str(site["site_root"])).resolve()
        expected_active = site_root / "db" / selected_kind
        if active_path.resolve() != expected_active:
            raise DatabaseMaintenanceAuthorityError("DATABASE_DESCRIPTOR_PATH_INVALID")
    else:
        if not site_ref:
            site_ref = "__test__"
        site_root = (
            paths.data_root.resolve()
            if production_evidence
            else paths.site_dir(site_ref).resolve()
        )
        site = {
            "canonical_site_id": site_ref,
            "site_directory_name": site_ref,
            "site_root": site_root,
            "is_production": False,
        }
        # Generic test adapters may use a temporary data-root-relative path;
        # production recovery never accepts this branch.
        expected_active = active_path.resolve()

    site_root = _contained(Path(str(site["site_root"])), paths.data_root, "DATABASE_SITE_PATH_INVALID")
    artifact_paths: dict[str, str] = {}
    for name, candidate in (
        ("active_path", active_path),
        ("shadow_path", shadow_path),
        ("rollback_path", rollback_path),
    ):
        if candidate is None:
            continue
        resolved = _contained(
            Path(candidate),
            site_root
            if selected_kind == "mesh_derived" or production_evidence
            else paths.data_root,
            "DATABASE_RECOVERY_ARTIFACT_INVALID",
        )
        artifact_paths[name] = str(resolved)
    if backup_path is not None:
        artifact_paths["backup_path"] = str(
            _contained(Path(backup_path), paths.database_upgrade_backups_dir, "DATABASE_RECOVERY_BACKUP_INVALID")
        )
    if source:
        if str(source.get("task_type") or "") not in {
            "database_upgrade",
            "database_batch_upgrade",
            "database_backup_restore",
        }:
            raise DatabaseMaintenanceAuthorityError("DATABASE_TASK_TYPE_MISMATCH")
        if str(source.get("database_kind") or "") != selected_kind:
            raise DatabaseMaintenanceAuthorityError("DATABASE_SITE_SCOPE_STALE")
        if str(source.get("canonical_site_id") or "") != str(site["canonical_site_id"]):
            raise DatabaseMaintenanceAuthorityError("DATABASE_SITE_SCOPE_STALE")
        if str(source.get("site_directory_name") or "") != str(site["site_directory_name"]):
            raise DatabaseMaintenanceAuthorityError("DATABASE_SITE_SCOPE_STALE")
        source_scopes = [item for item in source.get("scopes") or () if isinstance(item, Mapping)]
        source_backups = [item for item in source.get("backups") or () if isinstance(item, Mapping)]
        source_targets = source_scopes or source_backups
        if source_targets and not any(
            str(item.get("scope_id") or "") == selected_scope_id
            and (
                not item.get("database_path")
                or Path(str(item.get("database_path") or "")).resolve() == expected_active
            )
            for item in source_targets
        ):
            raise DatabaseMaintenanceAuthorityError("DATABASE_TARGET_STALE")

    authority_mode = (
        STARTUP_RECOVERY_SOURCE_AUTHORITY
        if source
        else STARTUP_RECOVERY_PRODUCTION_MAINTENANCE_ADAPTER
        if production_evidence
        else STARTUP_RECOVERY_LEGACY_MESH_ADAPTER
        if allow_legacy_mesh_adapter
        else STARTUP_RECOVERY_TEST_ADAPTER
    )
    if allow_legacy_mesh_adapter and selected_kind != "mesh_derived":
        raise DatabaseMaintenanceAuthorityError("DATABASE_STARTUP_LEGACY_ADAPTER_INVALID")

    body: dict[str, Any] = {
        "schema_version": AUTHORITY_SCHEMA_VERSION,
        "authority_type": STARTUP_RECOVERY_AUTHORITY,
        "authority_mode": authority_mode,
        "operation_id": selected_operation,
        "database_kind": selected_kind,
        "scope_type": selected_scope_type,
        "scope_id": selected_scope_id,
        "maintenance_lock": str(maintenance_lock or ""),
        "canonical_site_id": str(site["canonical_site_id"]),
        "site_directory_name": str(site["site_directory_name"]),
        "site_root_relative_path": site_root.relative_to(paths.data_root.resolve()).as_posix()
        if site_root != paths.data_root.resolve()
        else "",
        "database_path": str(expected_active),
        "artifacts": artifact_paths,
        "source_authority": source,
    }
    if production_evidence:
        body["production_maintenance_evidence"] = production_evidence
        body["production_rollback_owner"] = rollback_owner
    return {**body, "authority_digest": _digest(body)}


def validate_startup_recovery_authority(
    paths: PathResolver,
    authority: Mapping[str, Any],
    *,
    operation_id: str,
) -> dict[str, Any]:
    """Revalidate persisted startup authority without mutating any artifact."""

    if not isinstance(authority, Mapping):
        raise DatabaseMaintenanceAuthorityError("DATABASE_STARTUP_AUTHORITY_REQUIRED")
    _validate_digest(authority)
    if int(authority.get("schema_version") or 0) != AUTHORITY_SCHEMA_VERSION:
        raise DatabaseMaintenanceAuthorityError("DATABASE_STARTUP_AUTHORITY_SCHEMA_UNSUPPORTED")
    if str(authority.get("authority_type") or "") != STARTUP_RECOVERY_AUTHORITY:
        raise DatabaseMaintenanceAuthorityError("DATABASE_STARTUP_AUTHORITY_TYPE_INVALID")
    selected_operation = str(operation_id or "").strip()
    if str(authority.get("operation_id") or "") != selected_operation:
        raise DatabaseMaintenanceAuthorityError("DATABASE_OPERATION_ID_MISMATCH")
    if not str(authority.get("maintenance_lock") or "").strip():
        raise DatabaseMaintenanceAuthorityError("DATABASE_MAINTENANCE_LOCK_REQUIRED")
    source = authority.get("source_authority")
    if source:
        if not isinstance(source, Mapping):
            raise DatabaseMaintenanceAuthorityError("DATABASE_AUTHORITY_INVALID")
        _validate_digest(source)
    production_evidence_raw = authority.get("production_maintenance_evidence")
    production_evidence = (
        _validate_production_maintenance_evidence(production_evidence_raw)
        if production_evidence_raw is not None
        else {}
    )
    production_rollback_owner_raw = authority.get("production_rollback_owner")
    production_rollback_owner = (
        _validate_production_rollback_owner(production_rollback_owner_raw)
        if production_rollback_owner_raw is not None
        else None
    )
    if source and production_evidence:
        raise DatabaseMaintenanceAuthorityError("DATABASE_STARTUP_AUTHORITY_MODES_CONFLICT")
    authority_mode = str(authority.get("authority_mode") or "")
    if source:
        if authority_mode != STARTUP_RECOVERY_SOURCE_AUTHORITY:
            raise DatabaseMaintenanceAuthorityError("DATABASE_STARTUP_AUTHORITY_MODE_INVALID")
    elif production_evidence:
        if authority_mode != STARTUP_RECOVERY_PRODUCTION_MAINTENANCE_ADAPTER:
            raise DatabaseMaintenanceAuthorityError("DATABASE_STARTUP_AUTHORITY_MODE_INVALID")
        if production_rollback_owner is None:
            raise DatabaseMaintenanceAuthorityError("DATABASE_PRODUCTION_ROLLBACK_OWNER_REQUIRED")
    elif data_environment(paths.data_root).is_production:
        if authority_mode != STARTUP_RECOVERY_LEGACY_MESH_ADAPTER or str(authority.get("database_kind") or "") != "mesh_derived":
            raise DatabaseMaintenanceAuthorityError("DATABASE_STARTUP_AUTHORITY_REQUIRED")
    elif authority_mode not in {STARTUP_RECOVERY_TEST_ADAPTER, STARTUP_RECOVERY_LEGACY_MESH_ADAPTER}:
        raise DatabaseMaintenanceAuthorityError("DATABASE_STARTUP_AUTHORITY_MODE_INVALID")
    database_kind = str(authority.get("database_kind") or "")
    site_ref = str(authority.get("site_directory_name") or "").strip()
    expected_site_root: Path
    if database_kind == "mesh_derived":
        site = _site_binding(paths, site_ref)
        if str(site["canonical_site_id"]) != str(authority.get("canonical_site_id") or ""):
            raise DatabaseMaintenanceAuthorityError("DATABASE_SITE_SCOPE_STALE")
        if str(site["site_directory_name"]) != site_ref:
            raise DatabaseMaintenanceAuthorityError("DATABASE_SITE_DESCRIPTOR_MISMATCH")
        scope_id = str(authority.get("scope_id") or "")
        prefix = f"{site_ref}:"
        safe_profile = scope_id[len(prefix) :] if scope_id.startswith(prefix) else ""
        if (
            str(authority.get("scope_type") or "") != "site_profile"
            or not safe_profile
            or Path(safe_profile).name != safe_profile
            or "/" in safe_profile
            or "\\" in safe_profile
        ):
            raise DatabaseMaintenanceAuthorityError("DATABASE_SCOPE_NOT_CANONICAL")
        expected_database = paths.mesh_mr_db_path(site_ref, safe_profile).resolve()
        if Path(str(authority.get("database_path") or "")).resolve() != expected_database:
            raise DatabaseMaintenanceAuthorityError("DATABASE_DESCRIPTOR_PATH_INVALID")
        expected_site_root = site["site_root"]
    elif (
        authority_mode == STARTUP_RECOVERY_PRODUCTION_MAINTENANCE_ADAPTER
        and data_environment(paths.data_root).is_production
    ):
        if database_kind not in _PRODUCTION_MAINTENANCE_DATABASES:
            raise DatabaseMaintenanceAuthorityError("UNSUPPORTED_DATABASE_KIND")
        site = _site_binding(paths, site_ref)
        if str(site["canonical_site_id"]) != str(authority.get("canonical_site_id") or ""):
            raise DatabaseMaintenanceAuthorityError("DATABASE_SITE_SCOPE_STALE")
        if str(authority.get("scope_type") or "") != "site" or str(authority.get("scope_id") or "") != str(site["canonical_site_id"]):
            raise DatabaseMaintenanceAuthorityError("DATABASE_SCOPE_NOT_CANONICAL")
        expected_site_root = site["site_root"]
        expected_database = expected_site_root / "db" / database_kind
        if Path(str(authority.get("database_path") or "")).resolve() != expected_database.resolve():
            raise DatabaseMaintenanceAuthorityError("DATABASE_DESCRIPTOR_PATH_INVALID")
    elif data_environment(paths.data_root).is_production:
        raise DatabaseMaintenanceAuthorityError("UNSUPPORTED_DATABASE_KIND")
    else:
        site_root = Path(str(authority.get("site_root_relative_path") or ""))
        if site_root:
            expected_site_root = paths.data_root.resolve() / site_root
        else:
            expected_site_root = paths.data_root.resolve()
    if database_kind == "mesh_derived" or (
        authority_mode == STARTUP_RECOVERY_PRODUCTION_MAINTENANCE_ADAPTER
        and data_environment(paths.data_root).is_production
    ):
        expected_relative_site_root = expected_site_root.relative_to(paths.data_root.resolve()).as_posix()
        if str(authority.get("site_root_relative_path") or "") != expected_relative_site_root:
            raise DatabaseMaintenanceAuthorityError("DATABASE_SITE_DESCRIPTOR_MISMATCH")
    else:
        expected_relative_site_root = str(authority.get("site_root_relative_path") or "")
    _contained(expected_site_root, paths.data_root, "DATABASE_SITE_PATH_INVALID")
    artifacts = authority.get("artifacts")
    if not isinstance(artifacts, Mapping):
        raise DatabaseMaintenanceAuthorityError("DATABASE_RECOVERY_ARTIFACTS_REQUIRED")
    for key, raw in artifacts.items():
        if key == "backup_path":
            _contained(Path(str(raw)), paths.database_upgrade_backups_dir, "DATABASE_RECOVERY_BACKUP_INVALID")
        else:
            _contained(
                Path(str(raw)),
                expected_site_root
                if database_kind == "mesh_derived"
                or (
                    authority_mode == STARTUP_RECOVERY_PRODUCTION_MAINTENANCE_ADAPTER
                    and data_environment(paths.data_root).is_production
                )
                else paths.data_root,
                "DATABASE_RECOVERY_ARTIFACT_INVALID",
            )
    database_path = Path(str(authority.get("database_path") or ""))
    if not database_path.is_absolute():
        raise DatabaseMaintenanceAuthorityError("DATABASE_DESCRIPTOR_PATH_INVALID")
    _contained(
        database_path,
        expected_site_root
        if database_kind == "mesh_derived"
        or (
            authority_mode == STARTUP_RECOVERY_PRODUCTION_MAINTENANCE_ADAPTER
            and data_environment(paths.data_root).is_production
        )
        else paths.data_root,
        "DATABASE_DESCRIPTOR_PATH_INVALID",
    )
    active_path = Path(str(artifacts.get("active_path") or ""))
    if active_path.resolve() != database_path.resolve():
        raise DatabaseMaintenanceAuthorityError("DATABASE_RECOVERY_ARTIFACT_MISMATCH")
    return dict(authority)


def _require_operation(paths: PathResolver, task_type: str, authorization_token: str) -> tuple[str, str]:
    try:
        operation, capability = _OPERATION_BY_TASK[str(task_type)]
    except KeyError as exc:
        raise DatabaseMaintenanceAuthorityError("DATABASE_TASK_TYPE_UNSUPPORTED") from exc
    if not data_environment(paths.data_root).is_production:
        return operation, capability
    try:
        require_data_root_write_allowed(
            paths.data_root,
            f"DATABASE_{operation}",
            allow_production_write=production_write_allowed(),
        )
    except Exception as exc:
        raise DatabaseMaintenanceAuthorityError("DATABASE_PRODUCTION_WRITE_NOT_ALLOWED") from exc
    if capability and str(authorization_token or "") != capability:
        raise DatabaseMaintenanceAuthorityError("DATABASE_OPERATION_AUTHORIZATION_REQUIRED")
    return operation, capability


def _profile_descriptor(paths: PathResolver, site_directory_name: str, profile_id: str) -> dict[str, str]:
    profile_key = str(profile_id or "").strip()
    if not profile_key:
        raise DatabaseMaintenanceAuthorityError("DATABASE_PROFILE_REQUIRED")
    catalog_path = paths.mesh_catalog_path(site_directory_name).resolve(strict=False)
    if not catalog_path.is_file() or _is_reparse(catalog_path):
        raise DatabaseMaintenanceAuthorityError("DATABASE_PROFILE_NOT_FOUND")
    try:
        profiles = MeshAnalysisQueryService(paths).list_profiles(site_directory_name)
    except Exception as exc:
        raise DatabaseMaintenanceAuthorityError("DATABASE_PROFILE_NOT_FOUND") from exc
    matches = [profile for profile in profiles if str(profile.mr_id or "") == profile_key]
    if len(matches) != 1:
        raise DatabaseMaintenanceAuthorityError("DATABASE_PROFILE_NOT_FOUND")
    profile = matches[0]
    safe_name = str(profile.safe_folder_name or "").strip()
    if not safe_name or Path(safe_name).name != safe_name or safe_name in {".", ".."}:
        raise DatabaseMaintenanceAuthorityError("DATABASE_PROFILE_DESCRIPTOR_INVALID")
    return {
        "mr_id": str(profile.mr_id or ""),
        "display_name": str(profile.display_name or ""),
        "safe_folder_name": safe_name,
    }


def _stat(path: Path) -> dict[str, int | bool]:
    try:
        info = path.stat()
    except OSError:
        return {"exists": False, "size_bytes": 0, "mtime_ns": 0}
    return {"exists": True, "size_bytes": int(info.st_size), "mtime_ns": int(info.st_mtime_ns)}


def _database_observation(path: Path, *, include_hash: bool = False) -> dict[str, Any]:
    resolved = path.resolve(strict=False)
    wal = resolved.with_name(resolved.name + "-wal")
    result = {
        "identity_format": "sqlite-observation-v1",
        "path": str(resolved),
        "file": _stat(resolved),
        "wal": _stat(wal),
    }
    if include_hash and bool(result["file"]["exists"]):
        result["sha256"] = _sha256(resolved)
    return result


def _database_identity(path: Path, *, cancel_check: Callable[[], None] | None = None) -> dict[str, Any]:
    if cancel_check is not None:
        cancel_check()
    observation = _database_observation(path, include_hash=True)
    if not bool(observation["file"]["exists"]):
        return {"exists": False, "size_bytes": 0, "sha256": "", "identity_format": "sqlite-v1"}
    validation = validate_sqlite(path)
    if not validation.get("valid"):
        raise DatabaseMaintenanceAuthorityError("DATABASE_TARGET_UNREADABLE")
    if cancel_check is not None:
        cancel_check()
    return {
        "exists": True,
        "size_bytes": int(observation["file"]["size_bytes"]),
        "sha256": str(observation.get("sha256") or ""),
        "schema_version": str(validation.get("schema_version") or "unknown"),
        "identity_format": "sqlite-v1",
    }


def _profile_scope(
    paths: PathResolver,
    site: Mapping[str, Any],
    profile_id: str,
    *,
    include_identity: bool,
    cancel_check: Callable[[], None] | None = None,
) -> dict[str, Any]:
    if cancel_check is not None:
        cancel_check()
    descriptor = _profile_descriptor(paths, str(site["site_directory_name"]), profile_id)
    database_path = paths.mesh_mr_db_path(
        str(site["site_directory_name"]),
        descriptor["safe_folder_name"],
    ).resolve()
    _contained(database_path, Path(str(site["site_root"])), "DATABASE_DESCRIPTOR_PATH_INVALID")
    observation = _database_observation(database_path)
    identity = _database_identity(database_path, cancel_check=cancel_check) if include_identity else {"deferred": True}
    body = {
        "canonical_site_id": str(site["canonical_site_id"]),
        "site_directory_name": str(site["site_directory_name"]),
        "profile_id": str(profile_id),
        "safe_folder_name": descriptor["safe_folder_name"],
        "database_kind": "mesh_derived",
        "scope_type": "site_profile",
        "scope_id": f"{site['site_directory_name']}:{descriptor['safe_folder_name']}",
        "database_path": str(database_path),
        "current_schema_version": str(
            MeshDerivedDataMaintenanceService._schema_version(database_path)
        ),
        "target_schema_version": MESH_SCHEMA_VERSION,
        "database_observation": observation,
        "database_identity": identity,
    }
    return {**body, "scope_digest": _digest(body)}


def _backup_binding(
    paths: PathResolver,
    site: Mapping[str, Any],
    backup_id: str,
    *,
    operation: str,
    include_identity: bool,
    backup_items: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    backup_key = str(backup_id or "").strip()
    if not backup_key:
        raise DatabaseMaintenanceAuthorityError("DATABASE_BACKUP_REQUIRED")
    store = DatabaseBackupStore(paths)
    try:
        item = dict(backup_items[backup_key]) if backup_items is not None and backup_key in backup_items else store.read(backup_key)
    except FileNotFoundError as exc:
        raise DatabaseMaintenanceAuthorityError("BACKUP_NOT_FOUND") from exc
    if str(item.get("database_kind") or "") != "mesh_derived":
        raise DatabaseMaintenanceAuthorityError("UNSUPPORTED_DATABASE_KIND")
    scope_type = str(item.get("scope_type") or "")
    scope_id = str(item.get("scope_id") or "")
    prefix = f"{site['site_directory_name']}:"
    if scope_type != "site_profile" or not scope_id.startswith(prefix):
        raise DatabaseMaintenanceAuthorityError("BACKUP_SITE_MISMATCH")
    safe_profile = scope_id[len(prefix) :]
    if not safe_profile or Path(safe_profile).name != safe_profile or "/" in safe_profile or "\\" in safe_profile:
        raise DatabaseMaintenanceAuthorityError("BACKUP_SCOPE_INVALID")
    backup_dir = _contained(Path(str(item.get("path") or "")), store.root, "BACKUP_PATH_INVALID")
    manifest_path = backup_dir / "manifest.json"
    database_path = backup_dir / "database.sqlite"
    if not manifest_path.is_file() or _is_reparse(manifest_path):
        raise DatabaseMaintenanceAuthorityError("BACKUP_MANIFEST_INVALID")
    declared_database_path = str(item.get("backup_database_path") or "").strip()
    if not declared_database_path or Path(declared_database_path).resolve() != database_path.resolve():
        raise DatabaseMaintenanceAuthorityError("BACKUP_PATH_INVALID")
    target_raw = str(item.get("original_database_path") or "").strip()
    if not target_raw:
        raise DatabaseMaintenanceAuthorityError("BACKUP_TARGET_INVALID")
    if operation == "DATABASE_BACKUP_RESTORE":
        target_path = _contained(Path(target_raw), Path(str(site["site_root"])), "BACKUP_TARGET_INVALID")
    else:
        target_path = Path(target_raw).expanduser().resolve(strict=False)
        if not target_path.is_absolute():
            raise DatabaseMaintenanceAuthorityError("BACKUP_TARGET_INVALID")
    expected_profile_path = paths.mesh_mr_db_path(str(site["site_directory_name"]), safe_profile).resolve()
    try:
        known_profile = _profile_descriptor(paths, str(site["site_directory_name"]), safe_profile)
    except DatabaseMaintenanceAuthorityError:
        known_profile = None
    if known_profile is not None and target_path != expected_profile_path and operation == "DATABASE_BACKUP_RESTORE":
        raise DatabaseMaintenanceAuthorityError("BACKUP_TARGET_MISMATCH")
    database_observation = _database_observation(database_path, include_hash=include_identity)
    declared_identity = {
        "size_bytes": int(item.get("database_size") or 0),
        "sha256": str(item.get("database_sha256") or ""),
    }
    observed_identity = {
        "size_bytes": int(database_observation["file"]["size_bytes"]),
        "sha256": str(database_observation.get("sha256") or ""),
    }
    body = {
        "backup_id": backup_key,
        "operation": operation,
        "canonical_site_id": str(site["canonical_site_id"]),
        "site_directory_name": str(site["site_directory_name"]),
        "database_kind": "mesh_derived",
        "scope_type": scope_type,
        "scope_id": scope_id,
        "profile_id": safe_profile,
        "backup_relative_path": backup_dir.relative_to(store.root).as_posix(),
        "target_database_relative_path": (
            target_path.relative_to(Path(str(site["site_root"])).resolve()).as_posix()
            if target_path.is_relative_to(Path(str(site["site_root"])).resolve())
            else ""
        ),
        "backup_database_path": str(database_path.resolve()),
        "database_observation": database_observation,
        "manifest_binding": _manifest_binding(item),
        "declared_identity": declared_identity,
        "observed_identity": observed_identity,
        "database_sha256": str(item.get("database_sha256") or ""),
        "database_size": int(item.get("database_size") or 0),
        "result_status": str(item.get("result_status") or ""),
        "authority_status": str(item.get("authority_status") or ""),
    }
    return {**body, "backup_digest": _digest(body)}


def build_database_task_authority(
    paths: PathResolver,
    *,
    task_type: str,
    site_ref: str,
    profile_ids: Iterable[str] = (),
    backup_ids: Iterable[str] = (),
    database_kind: str = "mesh_derived",
    authorization_token: str = "",
    defer_identity: bool = False,
    cancel_check: Callable[[], None] | None = None,
) -> dict[str, Any]:
    if str(database_kind or "") != "mesh_derived":
        raise DatabaseMaintenanceAuthorityError("UNSUPPORTED_DATABASE_KIND")
    operation, capability = _require_operation(paths, task_type, authorization_token)
    site = _site_binding(paths, site_ref)
    scopes: list[dict[str, Any]] = []
    if str(task_type) in _PROFILE_TASKS:
        selected = list(dict.fromkeys(str(value).strip() for value in profile_ids if str(value).strip()))
        if not selected:
            raise DatabaseMaintenanceAuthorityError("DATABASE_PROFILE_REQUIRED")
        scopes = [
            _profile_scope(
                paths,
                site,
                profile_id,
                include_identity=not defer_identity,
                cancel_check=cancel_check,
            )
            for profile_id in selected
        ]
    backups: list[dict[str, Any]] = []
    if str(task_type) in _BACKUP_TASKS:
        selected_backups = list(dict.fromkeys(str(value).strip() for value in backup_ids if str(value).strip()))
        if not selected_backups:
            raise DatabaseMaintenanceAuthorityError("DATABASE_BACKUP_REQUIRED")
        index = {
            str(item.get("backup_id") or ""): item
            for item in DatabaseBackupStore(paths).list(database_kind="mesh_derived")
            if str(item.get("backup_id") or "")
        }
        for backup_key in selected_backups:
            try:
                backups.append(
                    _backup_binding(
                        paths,
                        site,
                        backup_key,
                        operation=operation,
                        include_identity=not defer_identity,
                        backup_items=index,
                    )
                )
            except DatabaseMaintenanceAuthorityError as exc:
                # Batch deletion keeps the existing partial-result contract for
                # already-missing ids; an absent item cannot be mutated.
                if str(task_type) == "database_backup_batch_delete" and exc.code == "BACKUP_NOT_FOUND":
                    continue
                raise
    body = {
        "schema_version": AUTHORITY_SCHEMA_VERSION,
        "task_type": str(task_type),
        "operation": operation,
        "operation_authority": capability,
        "database_kind": "mesh_derived",
        "canonical_site_id": str(site["canonical_site_id"]),
        "site_directory_name": str(site["site_directory_name"]),
        "site_root_relative_path": Path(str(site["site_root"])).relative_to(paths.data_root.resolve()).as_posix(),
        "is_production": bool(site["is_production"]),
        "scope_kind": "profile" if scopes else "backup" if backups else "site",
        "requested_profile_ids": selected if str(task_type) in _PROFILE_TASKS else [],
        "requested_backup_ids": selected_backups if str(task_type) in _BACKUP_TASKS else [],
        "scopes": scopes,
        "backups": backups,
        "identity_deferred": bool(defer_identity),
    }
    return {**body, "authority_digest": _digest(body)}


def _validate_digest(authority: Mapping[str, Any]) -> None:
    unsigned = {key: value for key, value in authority.items() if key != "authority_digest"}
    if str(authority.get("authority_digest") or "") != _digest(unsigned):
        raise DatabaseMaintenanceAuthorityError("DATABASE_AUTHORITY_INVALID")


def _compare(code: str, expected: Mapping[str, Any], actual: Mapping[str, Any], keys: Iterable[str]) -> None:
    for key in keys:
        if expected.get(key) != actual.get(key):
            raise DatabaseMaintenanceAuthorityError(code)


def materialize_database_task_authority(
    paths: PathResolver,
    authority: Mapping[str, Any],
    *,
    profile_ids: Iterable[str] | None = None,
    authorization_token: str = "",
    backup_ids: Iterable[str] | None = None,
    cancel_check: Callable[[], None] | None = None,
) -> dict[str, Any]:
    if not isinstance(authority, Mapping):
        raise DatabaseMaintenanceAuthorityError("DATABASE_AUTHORITY_INVALID")
    _validate_digest(authority)
    if not bool(authority.get("identity_deferred")):
        return dict(authority)
    if cancel_check is not None:
        cancel_check()
    task_type = str(authority.get("task_type") or "")
    original_profiles = [
        str(value)
        for value in authority.get("requested_profile_ids")
        or [str(item.get("profile_id") or "") for item in authority.get("scopes") or ()]
    ]
    original_backups = [
        str(value)
        for value in authority.get("requested_backup_ids")
        or [str(item.get("backup_id") or "") for item in authority.get("backups") or ()]
    ]
    materialized = build_database_task_authority(
        paths,
        task_type=task_type,
        site_ref=str(authority.get("site_directory_name") or ""),
        profile_ids=original_profiles if profile_ids is None else profile_ids,
        backup_ids=original_backups if backup_ids is None else backup_ids,
        database_kind=str(authority.get("database_kind") or ""),
        authorization_token=authorization_token,
        defer_identity=False,
        cancel_check=cancel_check,
    )
    expected_scopes = {str(item.get("profile_id") or ""): item for item in authority.get("scopes") or ()}
    actual_scopes = {str(item.get("profile_id") or ""): item for item in materialized.get("scopes") or ()}
    if set(expected_scopes) != set(actual_scopes):
        raise DatabaseMaintenanceAuthorityError("DATABASE_TARGET_STALE")
    for key, expected in expected_scopes.items():
        _compare(
            "DATABASE_TARGET_STALE",
            expected,
            actual_scopes[key],
            ("canonical_site_id", "site_directory_name", "profile_id", "safe_folder_name", "database_path", "database_observation"),
        )
    if authority.get("requested_profile_ids") != materialized.get("requested_profile_ids"):
        raise DatabaseMaintenanceAuthorityError("DATABASE_TARGET_STALE")
    expected_backups = {str(item.get("backup_id") or ""): item for item in authority.get("backups") or ()}
    actual_backups = {str(item.get("backup_id") or ""): item for item in materialized.get("backups") or ()}
    if task_type == "database_backup_batch_delete":
        unauthorized = set(actual_backups) - set(expected_backups)
        if unauthorized:
            raise DatabaseMaintenanceAuthorityError("DATABASE_BACKUP_UNAUTHORIZED")
    elif set(expected_backups) != set(actual_backups):
        raise DatabaseMaintenanceAuthorityError("DATABASE_BACKUP_STALE")
    for key, expected in expected_backups.items():
        if task_type == "database_backup_batch_delete" and key not in actual_backups:
            continue
        _compare(
            "DATABASE_BACKUP_STALE",
            expected,
            actual_backups[key],
            (
                "backup_id",
                "canonical_site_id",
                "site_directory_name",
                "scope_id",
                "backup_relative_path",
                "target_database_relative_path",
                "backup_database_path",
                "manifest_binding",
                "declared_identity",
            ),
        )
    if authority.get("requested_backup_ids") != materialized.get("requested_backup_ids"):
        raise DatabaseMaintenanceAuthorityError("DATABASE_BACKUP_STALE")
    return materialized


def _request_site_ref(params: Mapping[str, Any]) -> str:
    refs = [
        str(params.get(key) or "").strip()
        for key in ("site_id", "site_name")
        if str(params.get(key) or "").strip()
    ]
    if not refs or len(set(refs)) != 1:
        raise DatabaseMaintenanceAuthorityError("DATABASE_SITE_SCOPE_STALE")
    return refs[0]


def _normalized_ids(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def revalidate_database_task_authority(
    paths: PathResolver,
    task_type: str,
    params: Mapping[str, Any],
    *,
    profile_ids: Iterable[str] | None = None,
    backup_ids: Iterable[str] | None = None,
    validate_profile_targets: bool = True,
    validate_requested_profile_list: bool = True,
    validate_requested_backup_list: bool = True,
    allow_deferred_identity: bool = False,
    cancel_check: Callable[[], None] | None = None,
) -> dict[str, Any]:
    authority = params.get("database_authority")
    if not isinstance(authority, Mapping):
        raise DatabaseMaintenanceAuthorityError("DATABASE_AUTHORITY_REQUIRED")
    _validate_digest(authority)
    if str(authority.get("task_type") or "") != str(task_type):
        raise DatabaseMaintenanceAuthorityError("DATABASE_TASK_TYPE_MISMATCH")
    if bool(authority.get("identity_deferred")):
        if not allow_deferred_identity:
            raise DatabaseMaintenanceAuthorityError("DATABASE_AUTHORITY_NOT_MATERIALIZED")
        return dict(authority)
    actual_site_ref = _request_site_ref(params)
    selected_profiles = list(profile_ids) if profile_ids is not None else None
    selected_backups = list(backup_ids) if backup_ids is not None else None
    expected_profiles = _normalized_ids(
        authority.get("requested_profile_ids")
        or [str(item.get("profile_id") or "") for item in authority.get("scopes") or ()]
    )
    expected_backups = _normalized_ids(
        authority.get("requested_backup_ids")
        or [str(item.get("backup_id") or "") for item in authority.get("backups") or ()]
    )
    if (
        selected_profiles is not None
        and str(task_type) in _PROFILE_TASKS
        and validate_requested_profile_list
    ):
        if set(_normalized_ids(selected_profiles)) != set(expected_profiles):
            raise DatabaseMaintenanceAuthorityError("DATABASE_TARGET_STALE")
    if selected_backups is not None and str(task_type) in _BACKUP_TASKS and validate_requested_backup_list:
        if set(_normalized_ids(selected_backups)) != set(expected_backups):
            raise DatabaseMaintenanceAuthorityError("DATABASE_BACKUP_TARGET_STALE")
    current = build_database_task_authority(
        paths,
        task_type=task_type,
        site_ref=actual_site_ref,
        profile_ids=selected_profiles
        if selected_profiles is not None
        else [str(item.get("profile_id") or "") for item in authority.get("scopes") or ()],
        backup_ids=selected_backups
        if selected_backups is not None
        else [str(item.get("backup_id") or "") for item in authority.get("backups") or ()],
        database_kind=str(authority.get("database_kind") or params.get("database_kind") or ""),
        authorization_token=str(params.get("authorization_token") or ""),
        defer_identity=False,
        cancel_check=cancel_check,
    )
    for key in (
        "schema_version",
        "task_type",
        "operation",
        "operation_authority",
        "database_kind",
        "canonical_site_id",
        "site_directory_name",
        "is_production",
    ):
        if authority.get(key) != current.get(key):
            raise DatabaseMaintenanceAuthorityError("DATABASE_SITE_SCOPE_STALE")
    if validate_profile_targets:
        expected = {str(item.get("profile_id") or ""): item for item in authority.get("scopes") or ()}
        actual = {str(item.get("profile_id") or ""): item for item in current.get("scopes") or ()}
        for key in selected_profiles or expected:
            if str(key) not in expected or str(key) not in actual:
                raise DatabaseMaintenanceAuthorityError("DATABASE_TARGET_STALE")
            _compare("DATABASE_TARGET_STALE", expected[str(key)], actual[str(key)], ("profile_id", "safe_folder_name", "database_path", "database_observation"))
    if backup_ids is not None or current.get("backups"):
        expected = {str(item.get("backup_id") or ""): item for item in authority.get("backups") or ()}
        actual = {str(item.get("backup_id") or ""): item for item in current.get("backups") or ()}
        if str(task_type) == "database_backup_batch_delete":
            unauthorized = set(actual) - set(expected)
            if unauthorized:
                raise DatabaseMaintenanceAuthorityError("DATABASE_BACKUP_UNAUTHORIZED")
            keys = set(selected_backups or expected)
        else:
            keys = set(selected_backups or expected)
        for key in keys:
            if str(key) not in expected or str(key) not in actual:
                if str(task_type) == "database_backup_batch_delete":
                    continue
                raise DatabaseMaintenanceAuthorityError("DATABASE_BACKUP_STALE")
            _compare(
                "DATABASE_BACKUP_STALE",
                expected[str(key)],
                actual[str(key)],
                (
                    "backup_id",
                    "canonical_site_id",
                    "site_directory_name",
                    "scope_id",
                    "backup_relative_path",
                    "target_database_relative_path",
                    "backup_database_path",
                    "manifest_binding",
                    "declared_identity",
                    "database_observation",
                ),
            )
    return dict(current)


__all__ = [
    "AUTHORITY_SCHEMA_VERSION",
    "DATABASE_BACKUP_CREATE_AUTHORIZED",
    "DATABASE_BACKUP_DELETE_AUTHORIZED",
    "DATABASE_BACKUP_RESTORE_AUTHORIZED",
    "DATABASE_UPGRADE_AUTHORIZED",
    "DatabaseMaintenanceAuthorityCancelled",
    "DatabaseMaintenanceAuthorityError",
    "LEGACY_DATABASE_ARCHIVE_MIGRATION_AUTHORIZED",
    "READ_ONLY_VALIDATION",
    "STARTUP_RECOVERY_AUTHORITY",
    "STARTUP_RECOVERY_PRODUCTION_MAINTENANCE_ADAPTER",
    "build_startup_recovery_authority",
    "build_database_task_authority",
    "materialize_database_task_authority",
    "revalidate_database_task_authority",
    "validate_startup_recovery_authority",
]
