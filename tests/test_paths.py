import os
import sys
from pathlib import Path

from netconsole.core.bootstrap import create_demo_context
from netconsole.core.paths import PathResolver
from netconsole.core import runtime_environment
from netconsole.core.runtime_environment import validate_runtime_write_path


def test_pytest_data_root_is_isolated_from_project_local_data() -> None:
    paths = PathResolver()
    project_local = Path(__file__).resolve().parents[1] / ".local"

    assert paths.data_root == Path(os.environ["NETCONSOLE_DATA_ROOT"]).resolve()
    assert paths.data_root != project_local.resolve()


def test_path_resolver_creates_site_dirs(tmp_path):
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    site = paths.ensure_site_dirs()

    assert site == tmp_path / "sites" / "demo"
    assert paths.app_root == tmp_path
    assert paths.data_dir == tmp_path
    assert paths.config_dir == tmp_path / "config"
    assert paths.app_config_path == tmp_path / "config" / "application.json"
    assert paths.settings_path == tmp_path / "config" / "settings.json"
    assert paths.runtime_dir == tmp_path / "runtime"
    assert paths.runtime_cache_dir == tmp_path / "runtime" / "cache"
    assert paths.offline_ap_cache_path == tmp_path / "runtime" / "cache" / "offline_ap_cache.json"
    assert paths.logs_dir == tmp_path / "runtime" / "logs"
    assert paths.app_log_path == tmp_path / "runtime" / "logs" / "app.log"
    assert paths.sites_dir == tmp_path / "sites"
    assert paths.site_dir() == site
    assert paths.site_db_path() == site / "db" / "devices.db"
    assert paths.site_metrics_dir() == site / "cache" / "metrics"
    assert (site / "db").is_dir()
    for dirname in ("raw", "parsed", "reports", "downloads", "tasks", "metrics", "rail_transit", "network_tools", "backups"):
        assert not (site / dirname).exists()
    assert not (site / "files").exists()
    assert not (site / "cache").exists()


def test_path_resolver_site_paths_use_files_and_cache_layout(tmp_path):
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    site = paths.site_dir("demo")

    assert paths.config_center_raw_logs_root("demo") == site / "files" / "config_center" / "raw_logs"
    assert paths.config_center_device_snapshots_dir("demo", "SW1") == site / "files" / "config_center" / "snapshots" / "SW1"
    assert paths.config_center_outputs_dir("demo") == site / "files" / "config_center" / "outputs"
    assert paths.device_file_download_dir("demo", "SW1") == site / "files" / "file_manager" / "downloads" / "SW1"
    assert paths.mesh_mr_raw_dir("demo", "MR1") == site / "files" / "rail_transit" / "mr_raw_mesh" / "MR1" / "raw"
    assert paths.online_mr_session_dir("demo", "MR1", "s1") == site / "files" / "rail_transit" / "online_mr" / "MR1" / "sessions" / "s1"
    assert paths.trackside_ap_raw_dir("demo") == site / "files" / "rail_transit" / "trackside_ap" / "raw"
    assert paths.car_network_diagnostic_outputs_dir("demo") == site / "files" / "rail_transit" / "car_network_diagnostic" / "outputs"
    assert paths.iperf_db_path("demo") == site / "files" / "network_tools" / "iperf" / "parsed" / "iperf_results.sqlite"
    assert paths.wireless_scan_raw_dir("demo") == site / "files" / "network_tools" / "wireless_scan" / "raw"
    assert paths.site_backups_dir("demo") == site / "files" / "backups"
    assert paths.site_metrics_dir("demo") == site / "cache" / "metrics"


def test_path_resolver_creates_project_dirs(tmp_path):
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    paths.ensure_project_dirs()

    assert paths.data_dir.is_dir()
    assert paths.config_dir.is_dir()
    assert paths.logs_dir.is_dir()
    assert paths.sites_dir.is_dir()
    assert not (tmp_path / "docs").exists()
    assert not (tmp_path / "tests").exists()
    assert not (tmp_path / "project").exists()


def test_path_resolver_does_not_derive_data_root_from_app_root(tmp_path):
    app = tmp_path / "application"
    configured = Path(os.environ["NETCONSOLE_DATA_ROOT"]).resolve()

    paths = PathResolver(app_root=app)

    assert paths.app_root == app.resolve()
    assert paths.data_root == configured
    assert paths.data_root != paths.app_root


def test_development_data_root_defaults_to_unified_d_drive_root(tmp_path, monkeypatch):
    source_root = tmp_path / "source"
    monkeypatch.delenv("NETCONSOLE_DATA_ROOT", raising=False)
    monkeypatch.setenv("NETCONSOLE_RUNTIME_MODE", "desktop-development")
    monkeypatch.setattr(runtime_environment, "is_packaged_runtime", lambda: False)
    monkeypatch.setattr(runtime_environment, "_source_project_root", lambda: source_root)

    assert runtime_environment.data_root() == Path(r"D:\NetConsoleData")


def test_test_mode_requires_explicit_isolated_data_root(monkeypatch):
    monkeypatch.delenv("NETCONSOLE_DATA_ROOT", raising=False)
    monkeypatch.setenv("NETCONSOLE_RUNTIME_MODE", "test")

    try:
        runtime_environment.data_root()
    except RuntimeError as exc:
        assert "必须显式设置" in str(exc)
    else:
        raise AssertionError("expected missing test data root rejection")


def test_test_mode_rejects_real_data_root(monkeypatch):
    monkeypatch.setenv("NETCONSOLE_DATA_ROOT", r"D:\NetConsoleData")
    monkeypatch.setenv("NETCONSOLE_RUNTIME_MODE", "test")

    try:
        runtime_environment.data_root()
    except RuntimeError as exc:
        assert "NetConsoleTestData" in str(exc)
    else:
        raise AssertionError("expected production data root rejection in tests")


def test_development_data_root_rejects_source_repository(tmp_path, monkeypatch):
    source_root = tmp_path / "source"
    monkeypatch.setenv("NETCONSOLE_DATA_ROOT", str(source_root / ".local"))
    monkeypatch.setattr(runtime_environment, "is_packaged_runtime", lambda: False)
    monkeypatch.setattr(runtime_environment, "_source_project_root", lambda: source_root)

    try:
        runtime_environment.data_root()
    except RuntimeError as exc:
        assert "must not be inside the source repository" in str(exc)
    else:
        raise AssertionError("expected source-tree data root rejection")


def test_path_resolver_uses_exe_dir_when_frozen(tmp_path, monkeypatch):
    exe_path = tmp_path / "NetConsole.exe"
    exe_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_path))
    monkeypatch.setenv("NETCONSOLE_DATA_ROOT", str(tmp_path / "local_data"))

    paths = PathResolver()

    assert paths.app_root == tmp_path
    assert paths.data_dir == tmp_path / "local_data"
    assert paths.site_db_path() == tmp_path / "local_data" / "sites" / "demo" / "db" / "devices.db"


def test_path_resolver_uses_exe_dir_when_nuitka_compiled(tmp_path, monkeypatch):
    exe_path = tmp_path / "NetConsole.exe"
    exe_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "executable", str(exe_path))
    monkeypatch.setattr(sys.modules["__main__"], "__compiled__", object(), raising=False)
    monkeypatch.setenv("NETCONSOLE_DATA_ROOT", str(tmp_path / "local_data"))

    paths = PathResolver()
    paths.ensure_project_dirs()

    assert paths.app_root == tmp_path
    assert paths.data_dir == tmp_path / "local_data"
    assert paths.runtime_dir == tmp_path / "local_data" / "runtime"
    assert not (tmp_path / "docs").exists()
    assert not (tmp_path / "tests").exists()
    assert not (tmp_path / "project").exists()


def test_path_resolver_uses_release_dir_when_exe_has_build_info(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    release_root = tmp_path / "release" / "customer"
    release_root.mkdir(parents=True)
    (release_root / "NetConsole.exe").write_text("", encoding="utf-8")
    (release_root / "runtime").mkdir()
    (release_root / "runtime" / "build_info.json").write_text(
        '{"edition":"customer","feature_profile":"customer"}',
        encoding="utf-8",
    )
    project_root.mkdir()
    monkeypatch.chdir(project_root)
    monkeypatch.setattr(sys, "executable", str(release_root / "NetConsole.exe"))
    monkeypatch.setenv("NETCONSOLE_DATA_ROOT", str(tmp_path / "local_data"))

    paths = PathResolver()

    assert paths.app_root == release_root
    assert paths.runtime_dir == tmp_path / "local_data" / "runtime"


def test_path_resolver_uses_argv_exe_dir_before_unreliable_executable(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    release_root = tmp_path / "release" / "customer"
    temp_root = tmp_path / "temp"
    release_root.mkdir(parents=True)
    temp_root.mkdir()
    (release_root / "NetConsole.exe").write_text("", encoding="utf-8")
    (temp_root / "NetConsole.exe").write_text("", encoding="utf-8")
    (release_root / "runtime").mkdir()
    (release_root / "runtime" / "build_info.json").write_text(
        '{"edition":"customer","feature_profile":"customer"}',
        encoding="utf-8",
    )
    project_root.mkdir()
    monkeypatch.chdir(project_root)
    monkeypatch.setattr(sys, "argv", [str(release_root / "NetConsole.exe")])
    monkeypatch.setattr(sys, "executable", str(temp_root / "NetConsole.exe"))
    monkeypatch.setenv("NETCONSOLE_DATA_ROOT", str(tmp_path / "local_data"))

    paths = PathResolver()

    assert paths.app_root == release_root
    assert paths.runtime_dir == tmp_path / "local_data" / "runtime"


def test_path_resolver_does_not_create_development_dirs_when_frozen(tmp_path, monkeypatch):
    exe_path = tmp_path / "NetConsole.exe"
    exe_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_path))
    monkeypatch.setenv("NETCONSOLE_DATA_ROOT", str(tmp_path / "local_data"))

    paths = PathResolver()
    paths.ensure_project_dirs()

    assert paths.data_dir.is_dir()
    assert paths.config_dir.is_dir()
    assert paths.logs_dir.is_dir()
    assert paths.sites_dir.is_dir()
    assert not (tmp_path / "docs").exists()
    assert not (tmp_path / "tests").exists()
    assert not (tmp_path / "project").exists()


def test_runtime_write_guard_rejects_development_dirs(tmp_path):
    for name in ("docs", "tests", "project"):
        try:
            validate_runtime_write_path(tmp_path / name)
        except RuntimeError as exc:
            assert "invalid runtime write path" in str(exc)
        else:
            raise AssertionError(f"expected runtime guard to reject {name}")


def test_nuitka_startup_context_does_not_create_development_dirs(tmp_path, monkeypatch):
    exe_path = tmp_path / "NetConsole.exe"
    exe_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "executable", str(exe_path))
    monkeypatch.setattr(sys.modules["__main__"], "__compiled__", object(), raising=False)
    monkeypatch.setenv("NETCONSOLE_DATA_ROOT", str(tmp_path / "local_data"))

    context = create_demo_context()

    assert context.paths.app_root == tmp_path
    assert context.paths.data_dir.is_dir()
    assert context.paths.runtime_dir.is_dir()
    assert context.paths.logs_dir.is_dir()
    assert not (tmp_path / "docs").exists()
    assert not (tmp_path / "tests").exists()
    assert not (tmp_path / "project").exists()
