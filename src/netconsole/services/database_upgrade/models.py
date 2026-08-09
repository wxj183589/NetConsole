from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable, Protocol


ProgressCallback = Callable[[str, int, int, str], None]
CancelCallback = Callable[[], bool]


class DatabaseUpgradeStrategy(StrEnum):
    SCHEMA_MIGRATION = "SCHEMA_MIGRATION"
    REBUILD_FROM_SOURCE = "REBUILD_FROM_SOURCE"
    EMPTY_DATABASE_RECREATE = "EMPTY_DATABASE_RECREATE"
    MANUAL_INTERVENTION_REQUIRED = "MANUAL_INTERVENTION_REQUIRED"


class DatabaseUpgradeAdapter(Protocol):
    def build_shadow(
        self,
        descriptor: "DatabaseDescriptor",
        shadow_path: Path,
        *,
        progress: ProgressCallback | None,
        should_cancel: CancelCallback | None,
    ) -> dict[str, Any]: ...

    def validate(self, path: Path) -> dict[str, Any]: ...

    def switch(
        self,
        descriptor: "DatabaseDescriptor",
        shadow_path: Path,
        rollback_path: Path,
    ) -> None: ...

    def rollback(
        self,
        descriptor: "DatabaseDescriptor",
        rollback_path: Path,
        failed_shadow_path: Path,
        failure_dir: Path,
    ) -> None: ...

    def finalize_success(
        self,
        descriptor: "DatabaseDescriptor",
        rollback_path: Path,
        backup_dir: Path,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class DatabaseDescriptor:
    database_kind: str
    scope_type: str
    scope_id: str
    database_path: Path
    target_version: str
    strategy: DatabaseUpgradeStrategy
    adapter: DatabaseUpgradeAdapter
    current_version: str = "unknown"
    profile_id: str = ""
    profile_name: str = ""
    task_id: str = ""
    maintenance_lock: str = ""
    reason: str = ""
    source_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    close_hook: Callable[[], None] | None = None
    reopen_hook: Callable[[], None] | None = None
    smoke_test: Callable[[Path], dict[str, Any] | None] | None = None
    version_reader: Callable[[Path], str] | None = None


@dataclass(frozen=True)
class DatabaseUpgradeResult:
    operation_id: str
    backup_id: str
    backup_path: str
    database_path: str
    strategy: str
    old_version: str
    target_version: str
    checkpoint_status: str
    backup_validation: dict[str, Any]
    new_validation: dict[str, Any]
    rollback_available: bool
    rollback_performed: bool
    retained_backup_count: int = 0
    status: str = "SUCCESS"
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "backup_id": self.backup_id,
            "backup_path": self.backup_path,
            "database_path": self.database_path,
            "strategy": self.strategy,
            "old_version": self.old_version,
            "target_version": self.target_version,
            "checkpoint_status": self.checkpoint_status,
            "backup_validation": dict(self.backup_validation),
            "new_validation": dict(self.new_validation),
            "rollback_available": self.rollback_available,
            "rollback_performed": self.rollback_performed,
            "retained_backup_count": self.retained_backup_count,
            "status": self.status,
            "diagnostics": dict(self.diagnostics),
        }
