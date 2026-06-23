import sys

from netconsole.core.paths import PathResolver


def test_path_resolver_creates_site_dirs(tmp_path):
    paths = PathResolver(tmp_path)
    site = paths.ensure_site_dirs()

    assert site == tmp_path / "data" / "sites" / "demo"
    assert paths.app_root == tmp_path
    assert paths.docs_dir == tmp_path / "docs"
    assert paths.data_dir == tmp_path / "data"
    assert paths.config_dir == tmp_path / "data" / "config"
    assert paths.app_config_path == tmp_path / "data" / "config" / "app.json"
    assert paths.settings_path == tmp_path / "data" / "config" / "settings.json"
    assert paths.runtime_dir == tmp_path / "runtime"
    assert paths.runtime_cache_dir == tmp_path / "runtime" / "cache"
    assert paths.offline_ap_cache_path == tmp_path / "runtime" / "cache" / "offline_ap_cache.json"
    assert paths.logs_dir == tmp_path / "runtime" / "logs"
    assert paths.app_log_path == tmp_path / "runtime" / "logs" / "app.log"
    assert paths.tests_dir == tmp_path / "tests"
    assert paths.project_dir == tmp_path / "project"
    assert paths.build_dir == tmp_path / "project" / "build"
    assert paths.dist_dir == tmp_path / "project" / "dist"
    assert paths.scripts_dir == tmp_path / "project" / "scripts"
    assert paths.resources_dir == tmp_path / "project" / "resources"
    assert paths.templates_dir == tmp_path / "project" / "resources" / "templates"
    assert paths.icons_dir == tmp_path / "project" / "resources" / "icons"
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

    assert paths.docs_dir.is_dir()
    assert paths.data_dir.is_dir()
    assert paths.config_dir.is_dir()
    assert paths.logs_dir.is_dir()
    assert paths.tests_dir.is_dir()
    assert paths.project_dir.is_dir()
    assert paths.sites_dir.is_dir()
    assert paths.build_dir.is_dir()
    assert paths.dist_dir.is_dir()
    assert paths.scripts_dir.is_dir()
    assert paths.resources_dir.is_dir()
    assert paths.icons_dir.is_dir()
    assert paths.templates_dir.is_dir()


def test_path_resolver_uses_exe_dir_when_frozen(tmp_path, monkeypatch):
    exe_path = tmp_path / "NetConsole.exe"
    exe_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_path))

    paths = PathResolver()

    assert paths.app_root == tmp_path
    assert paths.data_dir == tmp_path / "data"
    assert paths.site_db_path() == tmp_path / "data" / "sites" / "demo" / "db" / "devices.db"


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
    assert not paths.docs_dir.exists()
    assert not paths.tests_dir.exists()
    assert not paths.project_dir.exists()
