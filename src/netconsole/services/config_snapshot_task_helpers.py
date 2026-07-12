from __future__ import annotations

from netconsole.repositories.config_snapshot_repository import ConfigSnapshot
from netconsole.services.config_lifecycle_service import ConfigDiffResult, ConfigLifecycleService


def load_snapshot_content(service: ConfigLifecycleService, snapshot: ConfigSnapshot) -> str:
    return service.snapshot_text(snapshot)


def compare_snapshot_pair(service: ConfigLifecycleService, left: ConfigSnapshot, right: ConfigSnapshot) -> ConfigDiffResult:
    return service.compare_snapshots(left, right)
