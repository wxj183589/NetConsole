from __future__ import annotations

from dataclasses import dataclass

from netconsole.core.database import Database
from netconsole.core import app_logger
from netconsole.core.paths import PathResolver
from netconsole.core.sites import Site, SiteManager
from netconsole.repositories.device_repository import DeviceRepository


@dataclass(frozen=True)
class AppContext:
    paths: PathResolver
    site: Site
    database: Database
    repository: DeviceRepository
    demo_inserted: bool


def create_demo_context(paths: PathResolver | None = None) -> AppContext:
    paths = paths or PathResolver()
    paths.ensure_project_dirs()
    app_logger.configure_path_resolver(paths)
    manager = SiteManager(paths)
    demo_inserted = not paths.site_db_path("demo").exists()
    manager.ensure_app_config()
    site = manager.ensure_site(manager.get_current_site())
    database = Database(site.database_path)
    repository = DeviceRepository(database)
    return AppContext(
        paths=paths,
        site=site,
        database=database,
        repository=repository,
        demo_inserted=demo_inserted,
    )
