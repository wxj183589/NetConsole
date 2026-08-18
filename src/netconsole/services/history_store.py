"""Compatibility facade for the repository-owned History Storage V2 implementation."""

from typing import Any

from netconsole.repositories import history_store as _implementation
from netconsole.repositories.history_store import (
    HistoryDrainResult,
    HistoryMigrationCheckpoint,
    HistoryRetentionPolicy,
    HistoryStore,
    TaskHistoryStore,
    fingerprint,
    verify_task_result_row,
)

__all__ = [
    "HistoryDrainResult",
    "HistoryMigrationCheckpoint",
    "HistoryRetentionPolicy",
    "HistoryStore",
    "TaskHistoryStore",
    "verify_task_result_row",
    "fingerprint",
]


def __getattr__(name: str) -> Any:
    """Keep the legacy module surface while repository ownership converges."""

    return getattr(_implementation, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_implementation)))
