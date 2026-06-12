from __future__ import annotations

from dataclasses import dataclass

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.core.sites import Site, SiteManager
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.demo_data import insert_demo_devices


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
    site = SiteManager(paths).ensure_default_site()
    database = Database(site.database_path)
    first_database = not database.exists()
    if first_database:
        database.initialize()
    repository = DeviceRepository(database)
    if first_database:
        insert_demo_devices(repository)
    return AppContext(
        paths=paths,
        site=site,
        database=database,
        repository=repository,
        demo_inserted=first_database,
    )
