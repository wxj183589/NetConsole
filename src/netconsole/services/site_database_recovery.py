from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from time import sleep
from typing import Callable

from netconsole.core.paths import PathResolver


class SiteDatabaseRecoveryService:
    def __init__(
        self,
        paths: PathResolver,
        *,
        now: Callable[[], datetime] = datetime.now,
        retry_delay_seconds: float = 0.2,
    ) -> None:
        self.paths = paths
        self._now = now
        self._retry_delay_seconds = max(float(retry_delay_seconds), 0.0)

    def list_databases(self) -> list[Path]:
        sites_dir = self.paths.sites_dir.resolve()
        if not sites_dir.exists():
            return []
        return sorted(
            path.resolve()
            for path in sites_dir.glob("*/db/*.db")
            if path.is_file() and path.resolve().is_relative_to(sites_dir)
        )

    def backup_databases(self) -> list[Path]:
        return self._backup_databases(self.list_databases())

    def _backup_databases(self, databases: list[Path]) -> list[Path]:
        timestamp = self._now().strftime("%Y%m%d_%H%M%S")
        backups: list[Path] = []
        for database_path in databases:
            site_name = database_path.parents[1].name
            backup_dir = self.paths.site_backups_dir(site_name).resolve() / "db"
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup_path = backup_dir / f"{database_path.stem}_{timestamp}{database_path.suffix}"
            shutil.copy2(database_path, backup_path)
            backups.append(backup_path)
        return backups

    def backup_and_remove_databases(self) -> list[Path]:
        databases = self.list_databases()
        backups = self._backup_databases(databases)
        if len(backups) != len(databases):
            raise RuntimeError("局点数据库备份不完整，已取消重建")
        self.remove_databases(databases)
        return backups

    def remove_databases(self, databases: list[Path] | None = None) -> None:
        sites_dir = self.paths.sites_dir.resolve()
        for database_path in databases if databases is not None else self.list_databases():
            resolved = database_path.resolve()
            if not resolved.is_relative_to(sites_dir) or resolved.parent.name != "db" or resolved.suffix.casefold() != ".db":
                raise ValueError("拒绝删除局点数据库目录之外的文件")
            for attempt in range(3):
                try:
                    resolved.unlink(missing_ok=True)
                    break
                except PermissionError:
                    if attempt == 2:
                        raise
                    sleep(self._retry_delay_seconds)
