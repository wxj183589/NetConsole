import sys

from netconsole.core.bootstrap import create_demo_context
from netconsole.core.paths import PathResolver
from netconsole.core.runtime_environment import validate_runtime_write_path


def test_path_resolver_creates_site_dirs(tmp_path):
    paths = PathResolver(tmp_path)
    site = paths.ensure_site_dirs()

    assert site == tmp_path / "data" / "sites" / "demo"
    assert paths.app_root == tmp_path
    assert paths.data_dir == tmp_path / "data"
    assert paths.config_dir == tmp_path / "data" / "config"
    assert paths.app_config_path == tmp_path / "data" / "config" / "app.json"
    assert paths.settings_path == tmp_path / "data" / "config" / "settings.json"
    assert paths.runtime_dir == tmp_path / "runtime"
    assert paths.runtime_cache_dir == tmp_path / "runtime" / "cache"
    assert paths.offline_ap_cache_path == tmp_path / "runtime" / "cache" / "offline_ap_cache.json"
    assert paths.logs_dir == tmp_path / "runtime" / "logs"
    assert paths.app_log_path == tmp_path / "runtime" / "logs" / "app.log"
    assert paths.sites_dir == tmp_path / "data" / "sites"
    assert paths.site_dir() == site
    assert paths.site_db_path() == site / "db" / "devices.db"
    assert paths.site_metrics_dir() == site / "metrics"
    for dirname in ("db", "parsed", "reports", "backups", "tasks", "metrics"):
        assert (site / dirname).is_dir()
    assert not (site / "raw").exists()


def test_path_resolver_creates_project_dirs(tmp_path):
    paths = PathResolver(tmp_path)
    paths.ensure_project_dirs()

    assert paths.data_dir.is_dir()
    assert paths.config_dir.is_dir()
    assert paths.logs_dir.is_dir()
    assert paths.sites_dir.is_dir()
    assert not (tmp_path / "docs").exists()
    assert not (tmp_path / "tests").exists()
    assert not (tmp_path / "project").exists()


def test_path_resolver_uses_exe_dir_when_frozen(tmp_path, monkeypatch):
    exe_path = tmp_path / "NetConsole.exe"
    exe_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_path))

    paths = PathResolver()

    assert paths.app_root == tmp_path
    assert paths.data_dir == tmp_path / "data"
    assert paths.site_db_path() == tmp_path / "data" / "sites" / "demo" / "db" / "devices.db"


def test_path_resolver_uses_exe_dir_when_nuitka_compiled(tmp_path, monkeypatch):
    exe_path = tmp_path / "NetConsole.exe"
    exe_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "executable", str(exe_path))
    monkeypatch.setattr(sys.modules["__main__"], "__compiled__", object(), raising=False)

    paths = PathResolver()
    paths.ensure_project_dirs()

    assert paths.app_root == tmp_path
    assert paths.data_dir == tmp_path / "data"
    assert paths.runtime_dir == tmp_path / "runtime"
    assert not (tmp_path / "docs").exists()
    assert not (tmp_path / "tests").exists()
    assert not (tmp_path / "project").exists()


def test_path_resolver_does_not_create_development_dirs_when_frozen(tmp_path, monkeypatch):
    exe_path = tmp_path / "NetConsole.exe"
    exe_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_path))

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

    context = create_demo_context()

    assert context.paths.app_root == tmp_path
    assert context.paths.data_dir.is_dir()
    assert context.paths.runtime_dir.is_dir()
    assert context.paths.logs_dir.is_dir()
    assert not (tmp_path / "docs").exists()
    assert not (tmp_path / "tests").exists()
    assert not (tmp_path / "project").exists()
