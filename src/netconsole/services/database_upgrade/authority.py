"""HTTP database-maintenance authority and immutable worker scope.

This module is deliberately limited to the database-upgrade family.  It uses
the existing canonical MESH site resolver and leaves the upgrade coordinator,
journal, lock and backup transaction machinery as the mutation owners.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from netconsole.core.paths import PathResolver
from netconsole.core.runtime_environment import (
    data_environment,
    production_write_allowed,
    require_data_root_write_allowed,
)
from netconsole.services.database_upgrade.backup_store import DatabaseBackupStore
from netconsole.services.database_upgrade.sqlite_consistency import (
    sqlite_logical_identity,
    validate_sqlite,
)
from netconsole.services.database_upgrade.history import legacy_archive_bindings
from netconsole.services.mesh_derived_data_maintenance_service import (
    MeshDerivedDataMaintenanceService,
)
from netconsole.services.mesh_production_authority import resolve_mesh_production_scope


DATABASE_UPGRADE_AUTHORIZED = "DATABASE_UPGRADE_AUTHORIZED"
DATABASE_BACKUP_CREATE_AUTHORIZED = "DATABASE_BACKUP_CREATE_AUTHORIZED"
DATABASE_BACKUP_RESTORE_AUTHORIZED = "DATABASE_BACKUP_RESTORE_AUTHORIZED"
DATABASE_BACKUP_DELETE_AUTHORIZED = "DATABASE_BACKUP_DELETE_AUTHORIZED"
LEGACY_DATABASE_ARCHIVE_MIGRATION_AUTHORIZED = "LEGACY_DATABASE_ARCHIVE_MIGRATION_AUTHORIZED"

AUTHORITY_SCHEMA_VERSION = 6
READ_ONLY_VALIDATION = "READ_ONLY_VALIDATION"

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
    """A database maintenance scope or operation failed closed."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = str(code)
        super().__init__(message or self.code)


@dataclass(frozen=True)
class _SiteBinding:
    canonical_site_id: str
    directory_name: str
    site_root: Path
    is_production: bool
    descriptor_revision: str


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_reparse(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        return bool(int(getattr(path.lstat(), "st_file_attributes", 0) or 0) & 0x400)
    except (FileNotFoundError, OSError):
        return False


def _assert_contained(path: Path, root: Path, code: str) -> Path:
    resolved_root = root.resolve()
    raw = Path(path)
    current = raw
    while True:
        if _is_reparse(current):
            raise DatabaseMaintenanceAuthorityError(code)
        if current == resolved_root:
            break
        if current.parent == current:
            raise DatabaseMaintenanceAuthorityError(code)
        current = current.parent
    resolved = raw.resolve(strict=False)
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise DatabaseMaintenanceAuthorityError(code) from exc
    return resolved


def _relative(path: Path, root: Path, code: str) -> str:
    resolved = _assert_contained(path, root, code)
    return resolved.relative_to(root.resolve()).as_posix()


def _site_descriptor_revision(
    paths: PathResolver,
    canonical_site_id: str,
    directory_name: str,
) -> str:
    registry = paths.data_root / "config" / "site_registry.json"
    if not registry.is_file():
        return ""
    try:
        document = json.loads(registry.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    records = document.get("sites") if isinstance(document, Mapping) else None
    if not isinstance(records, list):
        return ""
    wanted_id = str(canonical_site_id or "").casefold()
    wanted_directory = str(directory_name or "").casefold()
    record: Mapping[str, Any] | None = next(
        (
            item
            for item in records
            if isinstance(item, Mapping)
            and str(item.get("site_id") or "").casefold() == wanted_id
        ),
        None,
    )
    if record is None:
        record = next(
            (
                item
                for item in records
                if isinstance(item, Mapping)
                and Path(str(item.get("relative_path") or "")).name.casefold()
                == wanted_directory
            ),
            None,
        )
    if record is None:
        return ""
    return _digest(
        {
            "canonical_site_id": str(canonical_site_id),
            "directory_name": str(directory_name),
            "record": dict(record),
        }
    )


def _site_binding(paths: PathResolver, site_ref: str) -> _SiteBinding:
    try:
        scope = resolve_mesh_production_scope(paths, str(site_ref or ""))
    except Exception as exc:
        raise DatabaseMaintenanceAuthorityError("DATABASE_SITE_NOT_CANONICAL") from exc
    site_root = _assert_contained(scope.site_root, paths.data_root, "DATABASE_SITE_PATH_INVALID")
    derived_root = paths.site_dir(scope.directory_name).resolve()
    if site_root != derived_root:
        raise DatabaseMaintenanceAuthorityError("DATABASE_SITE_DESCRIPTOR_MISMATCH")
    descriptor_revision = _site_descriptor_revision(
        paths,
        str(scope.canonical_site_id),
        str(scope.directory_name),
    )
    return _SiteBinding(
        canonical_site_id=str(scope.canonical_site_id),
        directory_name=str(scope.directory_name),
        site_root=site_root,
        is_production=bool(scope.is_production),
        descriptor_revision=descriptor_revision,
    )


def _require_operation(
    paths: PathResolver,
    task_type: str,
    authorization_token: str,
) -> tuple[str, str]:
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
    if str(authorization_token or "") != capability:
        raise DatabaseMaintenanceAuthorityError("DATABASE_OPERATION_AUTHORIZATION_REQUIRED")
    return operation, capability


def _profile_scope(
    paths: PathResolver,
    site: _SiteBinding,
    profile_id: str,
    *,
    include_database_identity: bool = True,
) -> dict[str, Any]:
    profile_key = str(profile_id or "").strip()
    if not profile_key:
        raise DatabaseMaintenanceAuthorityError("DATABASE_PROFILE_REQUIRED")
    inspection = MeshDerivedDataMaintenanceService(paths).inspect(
        site.directory_name,
        profile_ids=[profile_key],
    )
    matches = [
        dict(item)
        for item in inspection.get("profiles", [])
        if isinstance(item, Mapping) and str(item.get("mr_id") or "") == profile_key
    ]
    if len(matches) != 1:
        raise DatabaseMaintenanceAuthorityError("DATABASE_PROFILE_NOT_FOUND")
    profile = matches[0]
    safe_folder_name = str(profile.get("safe_folder_name") or "").strip()
    if not safe_folder_name or Path(safe_folder_name).name != safe_folder_name:
        raise DatabaseMaintenanceAuthorityError("DATABASE_PROFILE_DESCRIPTOR_INVALID")
    database_path = paths.mesh_mr_db_path(site.directory_name, safe_folder_name)
    database_relative_path = _relative(database_path, site.site_root, "DATABASE_DESCRIPTOR_PATH_INVALID")
    if not database_relative_path.endswith("/mesh.sqlite"):
        raise DatabaseMaintenanceAuthorityError("DATABASE_DESCRIPTOR_PATH_INVALID")
    database_identity = (
        _database_identity(
            database_path,
            str(profile.get("current_version") or "missing"),
            temp_dir=paths.temp_dir,
        )
        if include_database_identity
        else {"deferred": True}
    )
    body = {
        "canonical_site_id": site.canonical_site_id,
        "site_directory_name": site.directory_name,
        "profile_id": profile_key,
        "safe_folder_name": safe_folder_name,
        "database_kind": "mesh_derived",
        "scope_type": "site_profile",
        "scope_id": f"{site.directory_name}:{safe_folder_name}",
        "database_path": str(database_path.resolve()),
        "database_relative_path": database_relative_path,
        "site_descriptor_revision": site.descriptor_revision,
        "database_observation": _database_observation(
            database_path,
            str(profile.get("current_version") or "missing"),
        ),
        "current_schema_version": str(profile.get("current_version") or "missing"),
        "target_schema_version": str(profile.get("required_version") or ""),
        "database_identity": database_identity,
    }
    return {**body, "scope_digest": _digest(body)}


def _database_observation(path: Path, schema_version: str = "") -> dict[str, Any]:
    """Capture a cheap, WAL-aware target observation for queued authorities."""

    resolved = path.resolve(strict=False)

    def stat_pair(candidate: Path) -> tuple[int, int]:
        try:
            info = candidate.stat()
        except OSError:
            return 0, 0
        return int(info.st_size), int(info.st_mtime_ns)

    size_bytes, mtime_ns = stat_pair(resolved)
    wal_size_bytes, wal_mtime_ns = stat_pair(resolved.with_name(resolved.name + "-wal"))
    return {
        "identity_format": "sqlite-observation-v1",
        "exists": bool(size_bytes > 0),
        "size_bytes": size_bytes,
        "mtime_ns": mtime_ns,
        "wal_size_bytes": wal_size_bytes,
        "wal_mtime_ns": wal_mtime_ns,
        "schema_version": str(schema_version or ""),
    }


def _database_identity(
    path: Path,
    schema_version: str = "",
    *,
    temp_dir: Path | None = None,
) -> dict[str, Any]:
    resolved = path.resolve(strict=False)
    if not resolved.is_file():
        return {"exists": False, "size_bytes": 0, "sha256": "", "schema_version": schema_version}
    try:
        validation = validate_sqlite(resolved)
        if not validation.get("valid"):
            raise ValueError(str(validation.get("error") or "SQLite target is invalid"))
        logical = sqlite_logical_identity(
            resolved,
            temp_dir=temp_dir,
        )
    except Exception as exc:
        raise DatabaseMaintenanceAuthorityError("DATABASE_TARGET_UNREADABLE") from exc
    return {
        "exists": True,
        "identity_format": str(logical.get("identity_format") or ""),
        "size_bytes": int(logical.get("size_bytes") or 0),
        "sha256": str(logical.get("sha256") or ""),
        "schema_version": str(validation.get("schema_version") or schema_version),
    }


def _backup_binding(
    paths: PathResolver,
    site: _SiteBinding,
    backup_id: str,
    *,
    operation: str,
    include_target_identity: bool = True,
    include_content_identity: bool = True,
    backup_items: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    backup_key = str(backup_id or "").strip()
    if not backup_key:
        raise DatabaseMaintenanceAuthorityError("DATABASE_BACKUP_REQUIRED")
    store = DatabaseBackupStore(paths)
    if backup_items is None:
        try:
            item = store.read(backup_key)
        except FileNotFoundError as exc:
            raise DatabaseMaintenanceAuthorityError("BACKUP_NOT_FOUND") from exc
    else:
        item = backup_items.get(backup_key)
        if item is None:
            raise DatabaseMaintenanceAuthorityError("BACKUP_NOT_FOUND")
    if str(item.get("database_kind") or "") != "mesh_derived":
        raise DatabaseMaintenanceAuthorityError("UNSUPPORTED_DATABASE_KIND")
    scope_type = str(item.get("scope_type") or "")
    scope_id = str(item.get("scope_id") or "")
    prefix = f"{site.directory_name}:"
    if scope_type != "site_profile" or not scope_id.startswith(prefix):
        raise DatabaseMaintenanceAuthorityError("BACKUP_SITE_MISMATCH")
    backup_dir = _assert_contained(Path(str(item.get("path") or "")), store.root, "BACKUP_PATH_INVALID")
    manifest_path = backup_dir / "manifest.json"
    database_path = backup_dir / "database.sqlite"
    if not manifest_path.is_file():
        raise DatabaseMaintenanceAuthorityError("BACKUP_MANIFEST_INVALID")
    declared = str(item.get("backup_database_path") or "").strip()
    if not declared or Path(declared).resolve() != database_path:
        raise DatabaseMaintenanceAuthorityError("BACKUP_PATH_INVALID")
    database_relative_path = _relative(database_path, store.root, "BACKUP_PATH_INVALID")
    target_raw = str(item.get("original_database_path") or "").strip()
    if not target_raw:
        raise DatabaseMaintenanceAuthorityError("BACKUP_TARGET_INVALID")
    target_path = _assert_contained(Path(target_raw), site.site_root, "BACKUP_TARGET_INVALID")
    target_relative_path = target_path.relative_to(site.site_root).as_posix()
    safe_folder_name = scope_id[len(prefix) :]
    if (
        not safe_folder_name
        or safe_folder_name in {".", ".."}
        or Path(safe_folder_name).name != safe_folder_name
    ):
        raise DatabaseMaintenanceAuthorityError("BACKUP_SCOPE_INVALID")
    expected_target = paths.mesh_mr_db_path(site.directory_name, safe_folder_name).resolve()
    if operation == "DATABASE_BACKUP_RESTORE" and target_path != expected_target:
        raise DatabaseMaintenanceAuthorityError("BACKUP_TARGET_MISMATCH")
    backup_exists = database_path.is_file()
    manifest_stat = manifest_path.stat()
    database_stat = database_path.stat() if backup_exists else None
    backup_size = int(database_path.stat().st_size) if include_content_identity and backup_exists else 0
    backup_sha256 = _sha256(database_path) if include_content_identity and backup_exists else ""
    declared_size = int(item.get("database_size") or 0)
    declared_sha256 = str(item.get("database_sha256") or "")
    declared_identity = {
        "exists": bool(declared_size > 0 and declared_sha256),
        "size_bytes": declared_size,
        "sha256": declared_sha256,
    }
    observed_identity = (
        {
            "exists": backup_exists,
            "size_bytes": backup_size,
            "sha256": backup_sha256,
        }
        if include_content_identity
        else {"deferred": True}
    )
    if (
        include_content_identity
        and operation not in {READ_ONLY_VALIDATION, "DATABASE_BACKUP_DELETE"}
        and observed_identity != declared_identity
    ):
        raise DatabaseMaintenanceAuthorityError("BACKUP_CONTENT_STALE")
    manifest_sha256 = _sha256(manifest_path) if include_content_identity else ""
    body = {
        "backup_id": backup_key,
        "operation": operation,
        "canonical_site_id": site.canonical_site_id,
        "site_directory_name": site.directory_name,
        "database_kind": "mesh_derived",
        "scope_type": scope_type,
        "scope_id": scope_id,
        "profile_id": safe_folder_name,
        "backup_relative_path": database_relative_path.rsplit("/", 1)[0],
        "target_database_relative_path": target_relative_path,
        "manifest_sha256": manifest_sha256,
        "manifest_size_bytes": int(manifest_stat.st_size),
        "manifest_mtime_ns": int(manifest_stat.st_mtime_ns),
        "database_mtime_ns": int(database_stat.st_mtime_ns) if database_stat is not None else 0,
        "database_sha256": str(item.get("database_sha256") or ""),
        "database_size": int(item.get("database_size") or 0),
        "declared_identity": declared_identity,
        "observed_identity": observed_identity,
        "old_schema_version": str(item.get("old_schema_version") or ""),
        "target_schema_version": str(item.get("target_schema_version") or ""),
        "result_status": str(item.get("result_status") or ""),
        "authority_status": str(item.get("authority_status") or ""),
    }
    if operation == "DATABASE_BACKUP_RESTORE" and include_target_identity:
        body["target_identity"] = _database_identity(target_path, temp_dir=paths.temp_dir)
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
) -> dict[str, Any]:
    """Build a JSON-safe immutable authority snapshot before queuing a job."""

    if str(database_kind or "") != "mesh_derived":
        raise DatabaseMaintenanceAuthorityError("UNSUPPORTED_DATABASE_KIND")
    operation, capability = _OPERATION_BY_TASK.get(str(task_type), ("", ""))
    if not operation:
        raise DatabaseMaintenanceAuthorityError("DATABASE_TASK_TYPE_UNSUPPORTED")
    site = _site_binding(paths, site_ref)
    _require_operation(paths, task_type, authorization_token)
    scopes = []
    if str(task_type) in _PROFILE_TASKS:
        selected = list(dict.fromkeys(str(value).strip() for value in profile_ids if str(value).strip()))
        if not selected:
            raise DatabaseMaintenanceAuthorityError("DATABASE_PROFILE_REQUIRED")
        scopes = [
            _profile_scope(paths, site, value, include_database_identity=not defer_identity)
            for value in selected
        ]
    backups = []
    if str(task_type) in _BACKUP_TASKS:
        selected_backups = list(dict.fromkeys(str(value).strip() for value in backup_ids if str(value).strip()))
        if not selected_backups:
            raise DatabaseMaintenanceAuthorityError("DATABASE_BACKUP_REQUIRED")
        backup_index = {
            str(item.get("backup_id") or ""): item
            for item in DatabaseBackupStore(paths).list(database_kind="mesh_derived")
            if str(item.get("backup_id") or "")
        }
        backups = [
            _backup_binding(
                paths,
                site,
                value,
                operation=operation,
                include_target_identity=not defer_identity,
                include_content_identity=not defer_identity,
                backup_items=backup_index,
            )
            for value in selected_backups
        ]
    legacy_archives = (
        []
        if defer_identity
        else legacy_archive_bindings(paths, site.directory_name)
        if str(task_type) == "legacy_database_archive_migration"
        else []
    )
    body: dict[str, Any] = {
        "schema_version": AUTHORITY_SCHEMA_VERSION,
        "task_type": str(task_type),
        "operation": operation,
        "operation_authority": capability,
        "database_kind": "mesh_derived",
        "canonical_site_id": site.canonical_site_id,
        "site_directory_name": site.directory_name,
        "site_root_relative_path": site.site_root.relative_to(paths.data_root.resolve()).as_posix(),
        "site_descriptor_revision": site.descriptor_revision,
        "is_production": site.is_production,
        "scope_kind": "profile" if scopes else "backup" if backups else "site",
        "scopes": scopes,
        "backups": backups,
        "legacy_archives": legacy_archives,
        "legacy_archive_discovery_deferred": bool(
            str(task_type) == "legacy_database_archive_migration" and defer_identity
        ),
        "identity_deferred": bool(defer_identity),
    }
    return {**body, "authority_digest": _digest(body)}


def materialize_database_task_authority(
    paths: PathResolver,
    authority: Mapping[str, Any],
    *,
    profile_ids: Iterable[str] | None = None,
    authorization_token: str = "",
    backup_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Complete a lightweight queued authority inside the Job boundary."""

    if not isinstance(authority, Mapping) or not bool(authority.get("identity_deferred")):
        return dict(authority) if isinstance(authority, Mapping) else {}
    unsigned = {key: value for key, value in authority.items() if str(key) != "authority_digest"}
    if str(authority.get("authority_digest") or "") != _digest(unsigned):
        raise DatabaseMaintenanceAuthorityError("DATABASE_AUTHORITY_INVALID")
    task_type = str(authority.get("task_type") or "")
    profile_scopes = authority.get("scopes") or ()
    backup_bindings = list(authority.get("backups") or ())
    if not all(isinstance(item, Mapping) for item in (*profile_scopes, *backup_bindings)):
        raise DatabaseMaintenanceAuthorityError("DATABASE_AUTHORITY_INVALID")
    selected_profile_ids = list(
        dict.fromkeys(str(value).strip() for value in profile_ids or () if str(value).strip())
    )
    if profile_ids is not None:
        by_profile_id = {str(item.get("profile_id") or ""): item for item in profile_scopes}
        if any(value not in by_profile_id for value in selected_profile_ids):
            raise DatabaseMaintenanceAuthorityError("DATABASE_TARGET_STALE")
        profile_scopes = [by_profile_id[value] for value in selected_profile_ids]
    selected_backup_ids = list(dict.fromkeys(str(value).strip() for value in backup_ids or () if str(value).strip()))
    if backup_ids is not None:
        by_backup_id = {str(item.get("backup_id") or ""): item for item in backup_bindings}
        if any(value not in by_backup_id for value in selected_backup_ids):
            raise DatabaseMaintenanceAuthorityError("DATABASE_BACKUP_STALE")
        backup_bindings = [by_backup_id[value] for value in selected_backup_ids]
    materialized = build_database_task_authority(
        paths,
        task_type=task_type,
        site_ref=str(authority.get("site_directory_name") or ""),
        profile_ids=[str(item.get("profile_id") or "") for item in profile_scopes],
        backup_ids=[str(item.get("backup_id") or "") for item in backup_bindings],
        database_kind=str(authority.get("database_kind") or ""),
        authorization_token=authorization_token,
        defer_identity=False,
    )
    for field in (
        "schema_version",
        "task_type",
        "operation",
        "operation_authority",
        "database_kind",
        "canonical_site_id",
        "site_directory_name",
        "site_root_relative_path",
        "site_descriptor_revision",
        "is_production",
        "scope_kind",
    ):
        if authority.get(field) != materialized.get(field):
            raise DatabaseMaintenanceAuthorityError("DATABASE_SITE_SCOPE_STALE")
    expected_scopes = {str(item.get("profile_id") or ""): item for item in profile_scopes}
    actual_scopes = {str(item.get("profile_id") or ""): item for item in materialized.get("scopes") or ()}
    if set(expected_scopes) != set(actual_scopes):
        raise DatabaseMaintenanceAuthorityError("DATABASE_TARGET_STALE")
    for profile_id, expected in expected_scopes.items():
        _compare(
            "DATABASE_TARGET_STALE",
            expected,
            actual_scopes[profile_id],
            (
                "canonical_site_id",
                "site_directory_name",
                "profile_id",
                "safe_folder_name",
                "database_kind",
                "scope_type",
                "scope_id",
                "database_path",
                "database_relative_path",
                "current_schema_version",
                "database_observation",
                "target_schema_version",
                "site_descriptor_revision",
            ),
        )
    expected_backups = {str(item.get("backup_id") or ""): item for item in backup_bindings}
    actual_backups = {str(item.get("backup_id") or ""): item for item in materialized.get("backups") or ()}
    if set(expected_backups) != set(actual_backups):
        raise DatabaseMaintenanceAuthorityError("DATABASE_BACKUP_STALE")
    for backup_id, expected in expected_backups.items():
        _compare(
            "DATABASE_BACKUP_STALE",
            expected,
            actual_backups[backup_id],
            (
                "backup_id",
                "operation",
                "canonical_site_id",
                "site_directory_name",
                "database_kind",
                "scope_type",
                "scope_id",
                "profile_id",
                "backup_relative_path",
                "target_database_relative_path",
                "database_sha256",
                "database_size",
                "declared_identity",
                "result_status",
                "authority_status",
                "manifest_size_bytes",
                "manifest_mtime_ns",
                "database_mtime_ns",
            ),
        )
    if task_type == "legacy_database_archive_migration":
        expected_archives = list(authority.get("legacy_archives") or ())
        actual_archives = list(materialized.get("legacy_archives") or ())
        if expected_archives:
            if len(expected_archives) != len(actual_archives):
                raise DatabaseMaintenanceAuthorityError("LEGACY_ARCHIVE_STALE")
            for expected, actual in zip(expected_archives, actual_archives, strict=True):
                _compare(
                    "LEGACY_ARCHIVE_STALE",
                    expected,
                    actual,
                    ("source_relative_path", "profile_name", "size_bytes", "modified_ns"),
                )
    return materialized


def _compare(label: str, expected: Mapping[str, Any], actual: Mapping[str, Any], fields: Iterable[str]) -> None:
    for field in fields:
        if expected.get(field) != actual.get(field):
            raise DatabaseMaintenanceAuthorityError(label)


def revalidate_database_task_authority(
    paths: PathResolver,
    task_type: str,
    params: Mapping[str, Any],
    *,
    profile_ids: Iterable[str] | None = None,
    backup_ids: Iterable[str] | None = None,
    validate_profile_targets: bool = True,
    allow_deferred_identity: bool = False,
) -> dict[str, Any]:
    """Re-resolve every target immediately before the worker calls a mutator.

    Batch backup uses ``validate_profile_targets=False`` for its initial
    structural authority check, then revalidates each Profile inside its
    maintenance lock so one stale Profile remains an item-level failure.
    """

    authority = params.get("database_authority")
    if not isinstance(authority, Mapping):
        raise DatabaseMaintenanceAuthorityError("DATABASE_AUTHORITY_INVALID")
    if int(authority.get("schema_version") or 0) != AUTHORITY_SCHEMA_VERSION:
        raise DatabaseMaintenanceAuthorityError("DATABASE_AUTHORITY_INVALID")
    if str(authority.get("task_type") or "") != str(task_type):
        raise DatabaseMaintenanceAuthorityError("DATABASE_AUTHORITY_INVALID")
    operation, capability = _OPERATION_BY_TASK.get(str(task_type), ("", ""))
    if not operation or str(authority.get("operation") or "") != operation:
        raise DatabaseMaintenanceAuthorityError("DATABASE_AUTHORITY_INVALID")
    if str(authority.get("operation_authority") or "") != capability:
        raise DatabaseMaintenanceAuthorityError("DATABASE_AUTHORITY_INVALID")
    identity_deferred = bool(authority.get("identity_deferred"))
    if identity_deferred and not allow_deferred_identity:
        raise DatabaseMaintenanceAuthorityError("DATABASE_AUTHORITY_INVALID")
    if str(params.get("database_kind") or "mesh_derived") != "mesh_derived":
        raise DatabaseMaintenanceAuthorityError("UNSUPPORTED_DATABASE_KIND")
    _require_operation(paths, task_type, str(params.get("authorization_token") or ""))
    unsigned_authority = {
        key: value for key, value in authority.items() if str(key) != "authority_digest"
    }
    if str(authority.get("authority_digest") or "") != _digest(unsigned_authority):
        raise DatabaseMaintenanceAuthorityError("DATABASE_AUTHORITY_INVALID")
    site = _site_binding(paths, str(authority.get("canonical_site_id") or authority.get("site_directory_name") or ""))
    _compare(
        "DATABASE_SITE_SCOPE_STALE",
        authority,
        {
            "canonical_site_id": site.canonical_site_id,
            "site_directory_name": site.directory_name,
            "site_descriptor_revision": site.descriptor_revision,
            "is_production": site.is_production,
            "site_root_relative_path": site.site_root.relative_to(paths.data_root.resolve()).as_posix(),
        },
        (
            "canonical_site_id",
            "site_directory_name",
            "site_descriptor_revision",
            "is_production",
            "site_root_relative_path",
        ),
    )
    if str(authority.get("database_kind") or "") != "mesh_derived":
        raise DatabaseMaintenanceAuthorityError("UNSUPPORTED_DATABASE_KIND")
    if identity_deferred:
        if str(task_type) not in {"database_batch_upgrade", "database_batch_backup"}:
            raise DatabaseMaintenanceAuthorityError("DATABASE_AUTHORITY_INVALID")
        expected_profiles = {
            str(value).strip()
            for value in params.get("profile_ids") or [params.get("profile_id")]
            if str(value).strip()
        }
        actual_profiles = {
            str(item.get("profile_id") or "")
            for item in authority.get("scopes") or ()
            if isinstance(item, Mapping)
        }
        if not expected_profiles or expected_profiles != actual_profiles:
            raise DatabaseMaintenanceAuthorityError("DATABASE_AUTHORITY_INVALID")
        return dict(authority)
    if (
        str(task_type) == "legacy_database_archive_migration"
        and bool(authority.get("legacy_archive_discovery_deferred"))
    ):
        raise DatabaseMaintenanceAuthorityError("DATABASE_AUTHORITY_INVALID")
    if str(task_type) == "legacy_database_archive_migration":
        actual_archives = legacy_archive_bindings(paths, site.directory_name)
        if authority.get("legacy_archives") != actual_archives:
            raise DatabaseMaintenanceAuthorityError("LEGACY_ARCHIVE_STALE")
    if str(task_type) in _PROFILE_TASKS:
        expected_profiles = {
            str(value).strip()
            for value in params.get("profile_ids") or [params.get("profile_id")]
            if str(value).strip()
        }
        actual_profiles = {
            str(item.get("profile_id") or "")
            for item in authority.get("scopes") or ()
            if isinstance(item, Mapping)
        }
        if not expected_profiles or expected_profiles != actual_profiles:
            raise DatabaseMaintenanceAuthorityError("DATABASE_AUTHORITY_INVALID")
        if validate_profile_targets:
            selected_profiles = (
                {str(value).strip() for value in profile_ids if str(value).strip()}
                if profile_ids is not None
                else actual_profiles
            )
            if not selected_profiles or not selected_profiles.issubset(actual_profiles):
                raise DatabaseMaintenanceAuthorityError("DATABASE_AUTHORITY_INVALID")
        else:
            selected_profiles = actual_profiles
    else:
        selected_profiles = set()
    if str(task_type) in _BACKUP_TASKS:
        expected_backups = {
            str(value).strip()
            for value in params.get("backup_ids") or [params.get("backup_id")]
            if str(value).strip()
        }
        actual_backups = {
            str(item.get("backup_id") or "")
            for item in authority.get("backups") or ()
            if isinstance(item, Mapping)
        }
        if not expected_backups or expected_backups != actual_backups:
            raise DatabaseMaintenanceAuthorityError("DATABASE_AUTHORITY_INVALID")
        selected_backups = (
            {str(value).strip() for value in backup_ids if str(value).strip()}
            if backup_ids is not None
            else actual_backups
        )
        if not selected_backups or not selected_backups.issubset(actual_backups):
            raise DatabaseMaintenanceAuthorityError("DATABASE_AUTHORITY_INVALID")
    if validate_profile_targets:
        for expected in authority.get("scopes") or ():
            if not isinstance(expected, Mapping):
                raise DatabaseMaintenanceAuthorityError("DATABASE_AUTHORITY_INVALID")
            if str(task_type) in _PROFILE_TASKS and str(expected.get("profile_id") or "") not in selected_profiles:
                continue
            actual = _profile_scope(paths, site, str(expected.get("profile_id") or ""))
            _compare(
                "DATABASE_TARGET_STALE",
                expected,
                actual,
                (
                    "canonical_site_id",
                    "site_directory_name",
                    "profile_id",
                    "safe_folder_name",
                    "database_relative_path",
                    "database_path",
                    "current_schema_version",
                    "target_schema_version",
                    "database_identity",
                    "scope_digest",
                ),
            )
    for expected in authority.get("backups") or ():
        if not isinstance(expected, Mapping):
            raise DatabaseMaintenanceAuthorityError("DATABASE_AUTHORITY_INVALID")
        if str(task_type) in _BACKUP_TASKS and str(expected.get("backup_id") or "") not in selected_backups:
            continue
        actual = _backup_binding(
            paths,
            site,
            str(expected.get("backup_id") or ""),
            operation=operation,
        )
        _compare(
            "DATABASE_BACKUP_STALE",
            expected,
            actual,
            (
                "canonical_site_id",
                "site_directory_name",
                "backup_id",
                "operation",
                "database_kind",
                "scope_type",
                "scope_id",
                "profile_id",
                "backup_relative_path",
                "target_database_relative_path",
                "manifest_sha256",
                "database_sha256",
                "database_size",
                "declared_identity",
                "observed_identity",
                "result_status",
                "authority_status",
                "backup_digest",
            ),
        )
        if operation == "DATABASE_BACKUP_RESTORE":
            _compare(
                "DATABASE_BACKUP_STALE",
                expected,
                actual,
                ("target_identity",),
            )
        if str(task_type) in {"database_backup_delete", "database_backup_batch_delete"} and (
            str(actual.get("result_status") or "").upper()
            not in {
                "VALID_BACKUP",
                "DUPLICATE_BACKUP",
                "INVALID_DATABASE",
                "ZERO_BYTE_ARCHIVE",
                "NO_EXISTING_DATABASE",
                "CREATION_FAILED",
            }
        ):
            raise DatabaseMaintenanceAuthorityError("BACKUP_UNKNOWN_PROTECTED")
    return dict(authority)


__all__ = [
    "AUTHORITY_SCHEMA_VERSION",
    "DATABASE_BACKUP_CREATE_AUTHORIZED",
    "DATABASE_BACKUP_DELETE_AUTHORIZED",
    "DATABASE_BACKUP_RESTORE_AUTHORIZED",
    "DATABASE_UPGRADE_AUTHORIZED",
    "DatabaseMaintenanceAuthorityError",
    "LEGACY_DATABASE_ARCHIVE_MIGRATION_AUTHORIZED",
    "READ_ONLY_VALIDATION",
    "build_database_task_authority",
    "materialize_database_task_authority",
    "revalidate_database_task_authority",
]
