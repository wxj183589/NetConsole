from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from netconsole.core.paths import PathResolver


@dataclass(frozen=True)
class Site:
    name: str
    root_path: Path
    database_path: Path


class SiteManager:
    def __init__(self, paths: PathResolver) -> None:
        self.paths = paths

    def ensure_site(self, site_name: str) -> Site:
        root_path = self.paths.ensure_site_dirs(site_name)
        return Site(
            name=site_name,
            root_path=root_path,
            database_path=self.paths.site_db_path(site_name),
        )

    def ensure_demo_site(self) -> Site:
        return self.ensure_site("demo")

    def ensure_default_site(self) -> Site:
        return self.ensure_demo_site()
