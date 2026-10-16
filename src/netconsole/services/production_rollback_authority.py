"""Canonical authority for production AC/base-data rollback operations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from netconsole.core.paths import PathResolver
from netconsole.core.runtime_environment import (
    data_environment,
    production_write_allowed,
    require_data_root_write_allowed,
)
from netconsole.core.sites import SiteManager
from netconsole.services.production_database_maintenance import (
    ProductionMaintenanceError,
    resolve_production_site_scope,
    resolve_production_site_scope_by_directory,
)


AC_EXTENSION_ROLLBACK_AUTHORIZED = "AC_EXTENSION_ROLLBACK_AUTHORIZED"
BASE_DATA_ROLLBACK_AUTHORIZED = "BASE_DATA_ROLLBACK_AUTHORIZED"

_TOKENS = {
    "AC_EXTENSION_ROLLBACK": AC_EXTENSION_ROLLBACK_AUTHORIZED,
    "BASE_DATA_ROLLBACK": BASE_DATA_ROLLBACK_AUTHORIZED,
}


class ProductionRollbackAuthorityError(RuntimeError):
    def __init__(self, code: str, message: str = "") -> None:
        self.code = str(code)
        super().__init__(message or self.code)


@dataclass(frozen=True)
class RollbackSiteScope:
    canonical_site_id: str
    directory_name: str
    site_root: Path
    is_production: bool


def resolve_rollback_site_scope(paths: PathResolver, site_ref: str) -> RollbackSiteScope:
    environment = data_environment(paths.data_root)
    if not environment.is_production:
        try:
            site = SiteManager(paths).validate_site_name(site_ref)
            root = paths.site_dir(site).resolve()
        except (OSError, ValueError) as exc:
            raise ProductionRollbackAuthorityError("ROLLBACK_SITE_NOT_CANONICAL") from exc
        if not root.is_dir():
            raise ProductionRollbackAuthorityError("ROLLBACK_SITE_NOT_CANONICAL")
        return RollbackSiteScope(site, root.name, root, False)

    try:
        canonical, root = resolve_production_site_scope(paths, site_ref)
    except ProductionMaintenanceError:
        try:
            canonical, root = resolve_production_site_scope_by_directory(paths, site_ref)
        except ProductionMaintenanceError as by_directory_error:
            raise ProductionRollbackAuthorityError("ROLLBACK_SITE_NOT_CANONICAL") from by_directory_error
    return RollbackSiteScope(canonical, root.resolve().name, root.resolve(), True)


def require_rollback_authority(
    paths: PathResolver,
    *,
    site_ref: str,
    operation: str,
    authorization_token: str = "",
    audit_site_id: str = "",
) -> RollbackSiteScope:
    try:
        expected = _TOKENS[str(operation)]
    except KeyError as exc:
        raise ProductionRollbackAuthorityError("ROLLBACK_OPERATION_NOT_ALLOWLISTED") from exc
    scope = resolve_rollback_site_scope(paths, site_ref)
    if audit_site_id and str(audit_site_id) != scope.directory_name:
        raise ProductionRollbackAuthorityError("ROLLBACK_AUDIT_SITE_MISMATCH")
    if not scope.is_production:
        return scope
    try:
        require_data_root_write_allowed(
            paths.data_root,
            str(operation),
            allow_production_write=production_write_allowed(),
        )
    except Exception as exc:
        raise ProductionRollbackAuthorityError("ROLLBACK_PRODUCTION_WRITE_NOT_ALLOWED") from exc
    if str(authorization_token or "") != expected:
        raise ProductionRollbackAuthorityError("ROLLBACK_OPERATION_AUTHORIZATION_REQUIRED")
    return scope


__all__ = [
    "AC_EXTENSION_ROLLBACK_AUTHORIZED",
    "BASE_DATA_ROLLBACK_AUTHORIZED",
    "ProductionRollbackAuthorityError",
    "RollbackSiteScope",
    "require_rollback_authority",
    "resolve_rollback_site_scope",
]
