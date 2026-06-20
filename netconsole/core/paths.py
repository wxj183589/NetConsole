from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path


SITE_DIRS = ("db", "raw", "parsed", "reports", "backups", "tasks", "metrics")


def _default_app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd().resolve()


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


@dataclass(frozen=True)
class PathResolver:
    app_root: Path | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "app_root", Path(self.app_root or _default_app_root()).resolve())

    @property
    def docs_dir(self) -> Path:
        return self.app_root / "docs"

    @property
    def data_dir(self) -> Path:
        return self.app_root / "data"

    @property
    def tests_dir(self) -> Path:
        return self.app_root / "tests"

    @property
    def project_dir(self) -> Path:
        return self.app_root / "project"

    @property
    def build_dir(self) -> Path:
        return self.project_dir / "build"

    @property
    def dist_dir(self) -> Path:
        return self.project_dir / "dist"

    @property
    def scripts_dir(self) -> Path:
        return self.project_dir / "scripts"

    @property
    def resources_dir(self) -> Path:
        return self.project_dir / "resources"

    @property
    def templates_dir(self) -> Path:
        return self.resources_dir / "templates"

    @property
    def icons_dir(self) -> Path:
        return self.resources_dir / "icons"

    @property
    def sites_dir(self) -> Path:
        return self.data_dir / "sites"

    @property
    def config_dir(self) -> Path:
        return self.data_dir / "config"

    @property
    def app_config_path(self) -> Path:
        return self.config_dir / "app.json"

    @property
    def settings_path(self) -> Path:
        return self.config_dir / "settings.json"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def app_log_path(self) -> Path:
        return self.logs_dir / "app.log"

    def site_dir(self, site_name: str = "demo") -> Path:
        return self.sites_dir / site_name

    def get_site_root(self, site_name: str = "demo") -> Path:
        return self.site_dir(site_name)

    def site_db_path(self, site_name: str = "demo") -> Path:
        return self.site_dir(site_name) / "db" / "devices.db"

    def site_metrics_dir(self, site_name: str = "demo") -> Path:
        return self.site_dir(site_name) / "metrics"

    def site_mesh_root(self, site_name: str = "demo") -> Path:
        return self.site_dir(site_name) / "rail_transit" / "mesh"

    def mesh_catalog_path(self, site_name: str = "demo") -> Path:
        return self.site_mesh_root(site_name) / "catalog.sqlite"

    def mesh_mr_root(self, site_name: str, safe_mr_name: str) -> Path:
        return self.site_mesh_root(site_name) / safe_mr_name

    def mesh_mr_db_path(self, site_name: str, safe_mr_name: str) -> Path:
        return self.mesh_mr_root(site_name, safe_mr_name) / "mesh.sqlite"

    def mesh_mr_raw_dir(self, site_name: str, safe_mr_name: str) -> Path:
        return self.mesh_mr_root(site_name, safe_mr_name) / "raw"

    def mesh_mr_export_dir(self, site_name: str, safe_mr_name: str) -> Path:
        return self.mesh_mr_root(site_name, safe_mr_name) / "exports"

    def ensure_site_dirs(self, site_name: str = "demo") -> Path:
        site_path = self.site_dir(site_name)
        for dirname in SITE_DIRS:
            (site_path / dirname).mkdir(parents=True, exist_ok=True)
        (site_path / "raw" / "collect").mkdir(parents=True, exist_ok=True)
        self.site_mesh_root(site_name).mkdir(parents=True, exist_ok=True)
        return site_path

    def ensure_project_dirs(self) -> None:
        runtime_paths = (
            self.data_dir,
            self.config_dir,
            self.sites_dir,
            self.logs_dir,
        )
        development_paths = (
            self.docs_dir,
            self.tests_dir,
            self.project_dir,
            self.build_dir,
            self.dist_dir,
            self.scripts_dir,
            self.resources_dir,
            self.icons_dir,
            self.templates_dir,
        )
        paths = runtime_paths if _is_frozen() else (*runtime_paths, *development_paths)
        for path in paths:
            path.mkdir(parents=True, exist_ok=True)
