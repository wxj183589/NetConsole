"""Production write capabilities for HTTP site/data-root operations."""

from __future__ import annotations

from pathlib import Path

from netconsole.services.storage_production_authority import (
    StorageAuthorityError,
    resolve_storage_root_authority,
)


SITE_TRASH_AUTHORIZED = "SITE_TRASH_AUTHORIZED"
SITE_CREATE_AUTHORIZED = "SITE_CREATE_AUTHORIZED"
SITE_UPDATE_AUTHORIZED = "SITE_UPDATE_AUTHORIZED"
SITE_ACTIVATE_AUTHORIZED = "SITE_ACTIVATE_AUTHORIZED"
SITE_RETENTION_APPLY_AUTHORIZED = "SITE_RETENTION_APPLY_AUTHORIZED"
SITE_CLEANUP_APPLY_AUTHORIZED = "SITE_CLEANUP_APPLY_AUTHORIZED"
SITE_CLEANUP_RESTORE_AUTHORIZED = "SITE_CLEANUP_RESTORE_AUTHORIZED"
SITE_IMPORT_AUTHORIZED = "SITE_IMPORT_AUTHORIZED"
SITE_MIGRATE_AUTHORIZED = "SITE_MIGRATE_AUTHORIZED"
DATA_ROOT_HTTP_MIGRATION_AUTHORIZED = "DATA_ROOT_HTTP_MIGRATION_AUTHORIZED"

_OPERATION_TOKENS = {
    "SITE_TRASH": SITE_TRASH_AUTHORIZED,
    "SITE_CREATE": SITE_CREATE_AUTHORIZED,
    "SITE_UPDATE": SITE_UPDATE_AUTHORIZED,
    "SITE_ACTIVATE": SITE_ACTIVATE_AUTHORIZED,
    "SITE_RETENTION_APPLY": SITE_RETENTION_APPLY_AUTHORIZED,
    "SITE_CLEANUP_APPLY": SITE_CLEANUP_APPLY_AUTHORIZED,
    "SITE_CLEANUP_RESTORE": SITE_CLEANUP_RESTORE_AUTHORIZED,
    "SITE_IMPORT": SITE_IMPORT_AUTHORIZED,
    "SITE_MIGRATE": SITE_MIGRATE_AUTHORIZED,
    "DATA_ROOT_HTTP_MIGRATION": DATA_ROOT_HTTP_MIGRATION_AUTHORIZED,
}


def require_site_operation(
    data_root: str | Path,
    operation: str,
    authorization_token: str = "",
) -> None:
    """Require an operation-specific token when the root is Production.

    Development/test roots intentionally remain usable by existing local APIs;
    a Production root must prove its manifest/registry identity before any
    destructive task is queued or executed.
    """

    expected = _OPERATION_TOKENS.get(str(operation))
    if expected is None:
        raise StorageAuthorityError("SITE_OPERATION_NOT_AUTHORIZED")
    root = Path(data_root).expanduser()
    if not root.exists():
        # A unit-isolated test/service may construct PathResolver before the
        # data root is materialized; it cannot be a marked Production root.
        return
    authority = resolve_storage_root_authority(root)
    if not authority.is_production:
        return
    if str(authorization_token or "") != expected:
        raise StorageAuthorityError("SITE_OPERATION_AUTHORIZATION_REQUIRED")


__all__ = [
    "DATA_ROOT_HTTP_MIGRATION_AUTHORIZED",
    "SITE_ACTIVATE_AUTHORIZED",
    "SITE_CLEANUP_APPLY_AUTHORIZED",
    "SITE_CLEANUP_RESTORE_AUTHORIZED",
    "SITE_CREATE_AUTHORIZED",
    "SITE_IMPORT_AUTHORIZED",
    "SITE_MIGRATE_AUTHORIZED",
    "SITE_RETENTION_APPLY_AUTHORIZED",
    "SITE_TRASH_AUTHORIZED",
    "SITE_UPDATE_AUTHORIZED",
    "require_site_operation",
]
