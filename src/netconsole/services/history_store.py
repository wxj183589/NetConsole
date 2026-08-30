"""Task Center archive facade; Legacy external HistoryStore has no service API."""

from netconsole.repositories.history_store import TaskHistoryStore

__all__ = ["TaskHistoryStore"]
