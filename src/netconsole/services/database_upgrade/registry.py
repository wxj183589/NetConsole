from __future__ import annotations

from pathlib import Path
from threading import RLock

from netconsole.services.database_upgrade.models import DatabaseDescriptor


class DatabaseUpgradeRegistry:
    """数据库升级描述注册表；不持有 SQLite connection。"""

    def __init__(self) -> None:
        self._items: dict[tuple[str, str, str], DatabaseDescriptor] = {}
        self._lock = RLock()

    def register(self, descriptor: DatabaseDescriptor) -> DatabaseDescriptor:
        key = self.key(descriptor.database_kind, descriptor.scope_type, descriptor.scope_id)
        with self._lock:
            existing = self._items.get(key)
            if existing is not None and existing.database_path != descriptor.database_path:
                raise ValueError(f"数据库升级描述重复：{key}")
            self._items[key] = descriptor
        return descriptor

    def unregister(self, database_kind: str, scope_type: str, scope_id: str) -> None:
        with self._lock:
            self._items.pop(self.key(database_kind, scope_type, scope_id), None)

    def get(self, database_kind: str, scope_type: str, scope_id: str) -> DatabaseDescriptor | None:
        with self._lock:
            return self._items.get(self.key(database_kind, scope_type, scope_id))

    def list(self) -> tuple[DatabaseDescriptor, ...]:
        with self._lock:
            return tuple(self._items.values())

    @staticmethod
    def key(database_kind: str, scope_type: str, scope_id: str) -> tuple[str, str, str]:
        return (str(database_kind), str(scope_type), str(scope_id))


GLOBAL_DATABASE_UPGRADE_REGISTRY = DatabaseUpgradeRegistry()
_ROOT_REGISTRIES: dict[str, DatabaseUpgradeRegistry] = {}
_ROOT_REGISTRIES_LOCK = RLock()


def database_upgrade_registry_for(data_root: Path) -> DatabaseUpgradeRegistry:
    key = str(Path(data_root).resolve()).casefold()
    with _ROOT_REGISTRIES_LOCK:
        return _ROOT_REGISTRIES.setdefault(key, DatabaseUpgradeRegistry())


__all__ = [
    "DatabaseUpgradeRegistry",
    "GLOBAL_DATABASE_UPGRADE_REGISTRY",
    "database_upgrade_registry_for",
]
