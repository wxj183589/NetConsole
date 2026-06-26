from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from netconsole.core.runtime_environment import app_root as default_app_root
from netconsole.core.runtime_environment import ensure_runtime_dir
from netconsole.core.runtime_environment import validate_runtime_write_path


SITE_DIRS = ("db", "parsed", "reports", "backups", "tasks", "metrics")


def _default_app_root() -> Path:
    return default_app_root()


@dataclass(frozen=True)
class PathResolver:
    app_root: Path | None = None
    data_root: Path | None = None

    def __post_init__(self) -> None:
        resolved_app_root = Path(self.app_root or _default_app_root()).resolve()
        object.__setattr__(self, "app_root", resolved_app_root)
        object.__setattr__(self, "data_root", Path(self.data_root).resolve() if self.data_root else resolved_app_root)

    @property
    def data_dir(self) -> Path:
        return self.data_root / "data"

    @property
    def runtime_dir(self) -> Path:
        return self.data_root / "runtime"

    @property
    def runtime_cache_dir(self) -> Path:
        return self.runtime_dir / "cache"

    @property
    def offline_ap_cache_path(self) -> Path:
        return self.runtime_cache_dir / "offline_ap_cache.json"

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
        return self.runtime_dir / "logs"

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

    def mesh_mr_online_sessions_root(self, site_name: str, safe_mr_name: str) -> Path:
        return self.mesh_mr_root(site_name, safe_mr_name) / "online_sessions"

    def mesh_mr_online_session_dir(self, site_name: str, safe_mr_name: str, session_id: str) -> Path:
        return self.mesh_mr_online_sessions_root(site_name, safe_mr_name) / session_id

    def online_mr_root(self, site_name: str = "demo") -> Path:
        return self.site_dir(site_name) / "rail_transit" / "online_mr"

    def online_mr_sessions_root(self, site_name: str, safe_mr_name: str) -> Path:
        return self.online_mr_root(site_name) / safe_mr_name / "sessions"

    def online_mr_session_dir(self, site_name: str, safe_mr_name: str, session_id: str) -> Path:
        return self.online_mr_sessions_root(site_name, safe_mr_name) / session_id

    def trackside_ap_root(self, site_name: str = "demo") -> Path:
        return self.site_dir(site_name) / "rail_transit" / "trackside_ap"

    def trackside_ap_optical_sessions_root(self, site_name: str = "demo") -> Path:
        return self.trackside_ap_root(site_name) / "optical_sessions"

    def trackside_ap_optical_session_dir(self, site_name: str, session_id: str) -> Path:
        return self.trackside_ap_optical_sessions_root(site_name) / session_id

    def trackside_ap_update_sessions_root(self, site_name: str = "demo") -> Path:
        return self.trackside_ap_root(site_name) / "update_sessions"

    def trackside_ap_update_session_dir(self, site_name: str, session_id: str) -> Path:
        return self.trackside_ap_update_sessions_root(site_name) / session_id

    def network_tools_root(self, site_name: str = "demo") -> Path:
        return self.site_dir(site_name) / "network_tools"

    def iperf_root(self, site_name: str = "demo") -> Path:
        return self.network_tools_root(site_name) / "iperf"

    def iperf_server_dir(self, site_name: str = "demo") -> Path:
        return self.iperf_root(site_name) / "server"

    def iperf_client_dir(self, site_name: str = "demo") -> Path:
        return self.iperf_root(site_name) / "client"

    def iperf_db_path(self, site_name: str = "demo") -> Path:
        return self.iperf_root(site_name) / "iperf_results.sqlite"

    def wireless_scan_root(self, site_name: str = "demo") -> Path:
        return self.network_tools_root(site_name) / "wireless_scan"

    def wireless_scan_db_path(self, site_name: str = "demo") -> Path:
        return self.wireless_scan_root(site_name) / "wireless_scan.sqlite"

    def wireless_scan_raw_dir(self, site_name: str = "demo") -> Path:
        return self.wireless_scan_root(site_name) / "raw"

    def wireless_scan_export_dir(self, site_name: str = "demo") -> Path:
        return self.wireless_scan_root(site_name) / "exports"

    @property
    def shared_runtime_dir(self) -> Path:
        return self.data_dir / "runtime"

    @property
    def network_profiles_path(self) -> Path:
        return self.shared_runtime_dir / "network_profiles.json"

    @property
    def route_profiles_path(self) -> Path:
        return self.shared_runtime_dir / "route_profiles.json"

    def ensure_site_dirs(self, site_name: str = "demo") -> Path:
        site_path = self.site_dir(site_name)
        for dirname in SITE_DIRS:
            ensure_runtime_dir(site_path / dirname)
        ensure_runtime_dir(self.site_mesh_root(site_name))
        ensure_runtime_dir(self.trackside_ap_optical_sessions_root(site_name))
        ensure_runtime_dir(self.trackside_ap_update_sessions_root(site_name))
        return site_path

    def ensure_project_dirs(self) -> None:
        runtime_paths = (
            self.runtime_dir,
            self.runtime_cache_dir,
            self.data_dir,
            self.shared_runtime_dir,
            self.config_dir,
            self.sites_dir,
            self.logs_dir,
        )
        for path in runtime_paths:
            ensure_runtime_dir(path)

    def validate_runtime_write_path(self, path: Path) -> Path:
        return validate_runtime_write_path(path)
