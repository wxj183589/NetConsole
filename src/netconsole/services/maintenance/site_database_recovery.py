"""Explicitly authorized site database recovery entry.

This module is never used during ordinary backend startup.  It exposes the
existing backup-and-remove behavior only after the caller supplies the exact
maintenance authorization token; path validation and backup-before-delete
checks remain owned by the legacy-compatible service.
"""

from __future__ import annotations

from pathlib import Path

from netconsole.core.paths import PathResolver
from netconsole.services.site_database_recovery import (
    SITE_DATABASE_RECOVERY_AUTHORIZATION,
    SiteDatabaseRecoveryService,
)


class SiteDatabaseRecoveryMaintenance(SiteDatabaseRecoveryService):
    """Maintenance facade requiring explicit authorization per destructive call."""

    def backup_and_remove_databases(self, *, authorization: str = "") -> list[Path]:
        return super().backup_and_remove_databases(authorization=authorization)


def run_authorized_site_database_recovery(
    paths: PathResolver,
    *,
    authorization: str,
) -> list[Path]:
    """Back up and remove site databases only for an explicit maintenance run."""

    return SiteDatabaseRecoveryMaintenance(paths).backup_and_remove_databases(
        authorization=authorization
    )


__all__ = [
    "SITE_DATABASE_RECOVERY_AUTHORIZATION",
    "SiteDatabaseRecoveryMaintenance",
    "run_authorized_site_database_recovery",
]
