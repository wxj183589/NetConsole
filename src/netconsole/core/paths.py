from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from netconsole.core.runtime_environment import app_root as default_app_root
from netconsole.core.runtime_environment import data_root as default_data_root
from netconsole.core.runtime_environment import ensure_runtime_dir
from netconsole.core.runtime_environment import validate_runtime_write_path


SITE_MIN_DIRS = ("db",)


def _default_app_root() -> Path:
    return default_app_root()


@dataclass(frozen=True)
class PathResolver:
    app_root: Path | None = None
    data_root: Path | None = None

    def __post_init__(self) -> None:
        configured_app_root = self.app_root
        configured_data_root = self.data_root
        resolved_app_root = Path(configured_app_root or _default_app_root()).resolve()
        object.__setattr__(self, "app_root", resolved_app_root)
        if configured_data_root is not None:
            resolved_data_root = Path(configured_data_root).resolve()
        else:
            resolved_data_root = default_data_root()
        object.__setattr__(self, "data_root", resolved_data_root)

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
    def bootstrap_dir(self) -> Path:
        return self.data_root / "bootstrap"

    @property
    def temp_dir(self) -> Path:
        return self.data_root / "temp"

    @property
    def archive_dir(self) -> Path:
        return self.data_root / "archive"

    @property
    def migrations_dir(self) -> Path:
        return self.data_root / "migrations"

    @property
    def app_log_path(self) -> Path:
        return self.logs_dir / "app.log"

    def site_dir(self, site_name: str = "demo") -> Path:
        return self.sites_dir / site_name

    def get_site_root(self, site_name: str = "demo") -> Path:
        return self.site_dir(site_name)

    def site_db_path(self, site_name: str = "demo") -> Path:
        return self.site_dir(site_name) / "db" / "devices.db"

    def site_tasks_db_path(self, site_name: str = "demo") -> Path:
        return self.site_dir(site_name) / "db" / "tasks.db"

    def site_agents_db_path(self, site_name: str = "demo") -> Path:
        return self.site_dir(site_name) / "db" / "agents.db"

    def site_files_dir(self, site_name: str = "demo") -> Path:
        return self.site_dir(site_name) / "files"

    def site_cache_dir(self, site_name: str = "demo") -> Path:
        return self.site_dir(site_name) / "cache"

    def site_metrics_dir(self, site_name: str = "demo") -> Path:
        return self.site_cache_dir(site_name) / "metrics"

    def site_backups_dir(self, site_name: str = "demo") -> Path:
        return self.site_files_dir(site_name) / "backups"

    def site_sync_dir(self, site_name: str = "demo") -> Path:
        return self.site_dir(site_name) / "sync"

    def site_imports_dir(self, site_name: str = "demo") -> Path:
        return self.site_files_dir(site_name) / "imports"

    def config_center_root(self, site_name: str = "demo") -> Path:
        return self.site_files_dir(site_name) / "config_center"

    def config_center_raw_logs_root(self, site_name: str = "demo") -> Path:
        return self.config_center_root(site_name) / "raw_logs"

    def config_center_raw_logs_dir(self, site_name: str, date_name: str, safe_device_name: str) -> Path:
        return self.config_center_raw_logs_root(site_name) / date_name / safe_device_name

    def config_center_snapshots_root(self, site_name: str = "demo") -> Path:
        return self.config_center_root(site_name) / "snapshots"

    def config_center_device_snapshots_dir(self, site_name: str, safe_device_name: str) -> Path:
        return self.config_center_snapshots_root(site_name) / safe_device_name

    def config_center_outputs_dir(self, site_name: str = "demo") -> Path:
        return self.config_center_root(site_name) / "outputs"

    def site_downloads_root(self, site_name: str = "demo") -> Path:
        return self.site_files_dir(site_name) / "file_manager" / "downloads"

    def file_downloads_root(self, site_name: str = "demo") -> Path:
        return self.site_downloads_root(site_name)

    def device_file_download_dir(self, site_name: str, safe_device_name: str) -> Path:
        return self.file_downloads_root(site_name) / safe_device_name

    def rail_transit_root(self, site_name: str = "demo") -> Path:
        return self.site_files_dir(site_name) / "rail_transit"

    def site_mesh_root(self, site_name: str = "demo") -> Path:
        return self.rail_transit_root(site_name) / "mr_raw_mesh"

    def mesh_catalog_path(self, site_name: str = "demo") -> Path:
        return self.site_mesh_root(site_name) / "catalog.sqlite"

    def mesh_mr_root(self, site_name: str, safe_mr_name: str) -> Path:
        return self.site_mesh_root(site_name) / safe_mr_name

    def mesh_mr_db_path(self, site_name: str, safe_mr_name: str) -> Path:
        return self.mesh_mr_root(site_name, safe_mr_name) / "mesh.sqlite"

    def mesh_mr_raw_dir(self, site_name: str, safe_mr_name: str) -> Path:
        return self.mesh_mr_root(site_name, safe_mr_name) / "raw"

    def mesh_mr_parsed_dir(self, site_name: str, safe_mr_name: str) -> Path:
        return self.mesh_mr_root(site_name, safe_mr_name) / "parsed"

    def mesh_mr_export_dir(self, site_name: str, safe_mr_name: str) -> Path:
        return self.mesh_mr_root(site_name, safe_mr_name) / "outputs"

    def mesh_mr_online_sessions_root(self, site_name: str, safe_mr_name: str) -> Path:
        return self.online_mr_sessions_root(site_name, safe_mr_name)

    def mesh_mr_online_session_dir(self, site_name: str, safe_mr_name: str, session_id: str) -> Path:
        return self.mesh_mr_online_sessions_root(site_name, safe_mr_name) / session_id

    def online_mr_root(self, site_name: str = "demo") -> Path:
        return self.rail_transit_root(site_name) / "online_mr"

    def online_mr_sessions_root(self, site_name: str, safe_mr_name: str) -> Path:
        return self.online_mr_root(site_name) / safe_mr_name / "sessions"

    def online_mr_session_dir(self, site_name: str, safe_mr_name: str, session_id: str) -> Path:
        return self.online_mr_sessions_root(site_name, safe_mr_name) / session_id

    def ac_mesh_link_root(self, site_name: str = "demo") -> Path:
        return self.rail_transit_root(site_name) / "ac_mesh_link"

    def ac_mesh_link_snapshots_root(self, site_name: str = "demo") -> Path:
        return self.ac_mesh_link_root(site_name) / "snapshots"

    def ac_mesh_link_snapshot_dir(self, site_name: str, session_id: str) -> Path:
        return self.ac_mesh_link_snapshots_root(site_name) / session_id

    def ac_mesh_link_staging_root(self, site_name: str = "demo") -> Path:
        return self.ac_mesh_link_root(site_name) / ".staging"

    def ac_mesh_link_failures_root(self, site_name: str = "demo") -> Path:
        return self.ac_mesh_link_root(site_name) / "failures"

    def rail_transit_base_data_import_root(self, site_name: str = "demo") -> Path:
        return self.rail_transit_root(site_name) / "base_data_import"

    def rail_transit_base_data_import_backups_dir(self, site_name: str = "demo") -> Path:
        return self.rail_transit_base_data_import_root(site_name) / "backups"

    def rail_transit_base_data_import_operations_dir(self, site_name: str = "demo") -> Path:
        return self.rail_transit_base_data_import_root(site_name) / "operations"

    def rail_transit_base_data_preview_root(self) -> Path:
        return self.runtime_dir / "base_data_import_previews"

    def ground_unattended_root(self, site_name: str = "demo") -> Path:
        return self.rail_transit_root(site_name) / "ground_unattended"

    def ground_unattended_active_root(self, site_name: str = "demo") -> Path:
        return self.ground_unattended_root(site_name) / "active"

    def ground_unattended_active_dir(self, site_name: str, run_date: str) -> Path:
        value = str(run_date or "").strip()
        if not value or Path(value).name != value or "/" in value or "\\" in value:
            raise ValueError("invalid ground unattended run date")
        return self.ground_unattended_active_root(site_name) / value

    def ground_unattended_archives_dir(self, site_name: str = "demo") -> Path:
        return self.ground_unattended_root(site_name) / "archives"

    def ground_unattended_db_path(self, site_name: str = "demo") -> Path:
        return self.ground_unattended_root(site_name) / "index.sqlite"

    def trackside_ap_root(self, site_name: str = "demo") -> Path:
        return self.rail_transit_root(site_name) / "trackside_ap"

    def trackside_ap_raw_dir(self, site_name: str = "demo") -> Path:
        return self.trackside_ap_root(site_name) / "raw"

    def trackside_ap_parsed_dir(self, site_name: str = "demo") -> Path:
        return self.trackside_ap_root(site_name) / "parsed"

    def trackside_ap_outputs_dir(self, site_name: str = "demo") -> Path:
        return self.trackside_ap_root(site_name) / "outputs"

    def trackside_ap_optical_sessions_root(self, site_name: str = "demo") -> Path:
        return self.trackside_ap_raw_dir(site_name) / "optical_sessions"

    def trackside_ap_optical_session_dir(self, site_name: str, session_id: str) -> Path:
        return self.trackside_ap_optical_sessions_root(site_name) / session_id

    def trackside_ap_update_sessions_root(self, site_name: str = "demo") -> Path:
        return self.trackside_ap_raw_dir(site_name) / "update_sessions"

    def trackside_ap_update_session_dir(self, site_name: str, session_id: str) -> Path:
        return self.trackside_ap_update_sessions_root(site_name) / session_id

    def trackside_ap_update_parsed_session_dir(self, site_name: str, session_id: str) -> Path:
        return self.trackside_ap_parsed_dir(site_name) / "update_sessions" / session_id

    def trackside_ap_update_outputs_session_dir(self, site_name: str, session_id: str) -> Path:
        return self.trackside_ap_outputs_dir(site_name) / "update_sessions" / session_id

    def network_tools_root(self, site_name: str = "demo") -> Path:
        return self.site_files_dir(site_name) / "network_tools"

    def toolbox_root(self, site_name: str = "demo") -> Path:
        return self.network_tools_root(site_name) / "toolbox"

    def toolbox_outputs_dir(self, site_name: str = "demo") -> Path:
        return self.toolbox_root(site_name) / "outputs"

    def iperf_root(self, site_name: str = "demo") -> Path:
        return self.network_tools_root(site_name) / "iperf"

    def iperf_server_dir(self, site_name: str = "demo") -> Path:
        return self.iperf_root(site_name) / "raw" / "server"

    def iperf_client_dir(self, site_name: str = "demo") -> Path:
        return self.iperf_root(site_name) / "raw" / "client"

    def iperf_db_path(self, site_name: str = "demo") -> Path:
        return self.iperf_root(site_name) / "parsed" / "iperf_results.sqlite"

    def iperf_outputs_dir(self, site_name: str = "demo") -> Path:
        return self.iperf_root(site_name) / "outputs"

    def traffic_root(self, site_name: str = "demo") -> Path:
        return self.network_tools_root(site_name) / "traffic"

    def traffic_runs_root(self, site_name: str = "demo") -> Path:
        return self.traffic_root(site_name) / "runs"

    def traffic_run_dir(self, site_name: str, traffic_run_id: str) -> Path:
        value = str(traffic_run_id or "").strip()
        if not value or value in {".", ".."} or Path(value).name != value or "/" in value or "\\" in value:
            raise ValueError("invalid traffic_run_id")
        return self.traffic_runs_root(site_name) / value

    def traffic_runs_db_path(self, site_name: str = "demo") -> Path:
        return self.traffic_root(site_name) / "parsed" / "traffic_runs.sqlite"

    def traffic_run_events_path(self, site_name: str, traffic_run_id: str) -> Path:
        return self.traffic_run_dir(site_name, traffic_run_id) / "events.jsonl"

    def traffic_run_summary_path(self, site_name: str, traffic_run_id: str) -> Path:
        return self.traffic_run_dir(site_name, traffic_run_id) / "summary.json"

    def traffic_run_remote_result_path(self, site_name: str, traffic_run_id: str) -> Path:
        return self.traffic_run_dir(site_name, traffic_run_id) / "remote_result.json"

    def wireless_scan_root(self, site_name: str = "demo") -> Path:
        return self.network_tools_root(site_name) / "wireless_scan"

    def wireless_scan_db_path(self, site_name: str = "demo") -> Path:
        return self.wireless_scan_root(site_name) / "parsed" / "wireless_scan.sqlite"

    def wireless_scan_raw_dir(self, site_name: str = "demo") -> Path:
        return self.wireless_scan_root(site_name) / "raw"

    def wireless_scan_export_dir(self, site_name: str = "demo") -> Path:
        return self.wireless_scan_root(site_name) / "outputs"

    def wireless_scan_projects_dir(self, site_name: str = "demo") -> Path:
        return self.wireless_scan_root(site_name) / "projects"

    def car_network_diagnostic_root(self, site_name: str = "demo") -> Path:
        return self.rail_transit_root(site_name) / "car_network_diagnostic"

    def car_network_diagnostic_raw_dir(self, site_name: str = "demo") -> Path:
        return self.car_network_diagnostic_root(site_name) / "raw"

    def car_network_diagnostic_parsed_dir(self, site_name: str = "demo") -> Path:
        return self.car_network_diagnostic_root(site_name) / "parsed"

    def car_network_diagnostic_outputs_dir(self, site_name: str = "demo") -> Path:
        return self.car_network_diagnostic_root(site_name) / "outputs"

    @property
    def shared_runtime_dir(self) -> Path:
        return self.data_dir / "runtime"

    @property
    def network_profiles_path(self) -> Path:
        return self.shared_runtime_dir / "network_profiles.json"

    @property
    def route_profiles_path(self) -> Path:
        return self.shared_runtime_dir / "route_profiles.json"

    @property
    def global_security_dir(self) -> Path:
        """跨局点安全材料目录；不随单个局点包导出。"""

        return self.data_dir / "global" / "security"

    @property
    def global_known_hosts_path(self) -> Path:
        return self.global_security_dir / "known_hosts"

    def ensure_site_dirs(self, site_name: str = "demo") -> Path:
        site_path = self.site_dir(site_name)
        ensure_runtime_dir(site_path)
        for dirname in SITE_MIN_DIRS:
            ensure_runtime_dir(site_path / dirname)
        return site_path

    def ensure_site_files_dir(self, site_name: str = "demo") -> Path:
        path = self.site_files_dir(site_name)
        ensure_runtime_dir(path)
        return path

    def ensure_site_cache_dir(self, site_name: str = "demo") -> Path:
        path = self.site_cache_dir(site_name)
        ensure_runtime_dir(path)
        return path

    def ensure_project_dirs(self) -> None:
        runtime_paths = (
            self.runtime_dir,
            self.runtime_cache_dir,
            self.data_dir,
            self.shared_runtime_dir,
            self.config_dir,
            self.sites_dir,
            self.logs_dir,
            self.bootstrap_dir,
            self.temp_dir,
            self.archive_dir,
            self.migrations_dir,
        )
        for path in runtime_paths:
            ensure_runtime_dir(path)

    def validate_runtime_write_path(self, path: Path) -> Path:
        return validate_runtime_write_path(path)
