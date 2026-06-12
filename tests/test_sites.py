from netconsole.core.paths import PathResolver
from netconsole.core.sites import SiteManager


def test_site_manager_creates_demo_and_chinese_site(tmp_path):
    manager = SiteManager(PathResolver(tmp_path))

    demo = manager.ensure_demo_site()
    legacy_method_demo = manager.ensure_default_site()
    chinese_site_name = "\u534e\u4e1c\u7ad9\u70b9"
    chinese = manager.ensure_site(chinese_site_name)

    assert demo.name == "demo"
    assert legacy_method_demo.name == "demo"
    assert demo.database_path == tmp_path / "data" / "sites" / "demo" / "db" / "devices.db"
    assert chinese.root_path.is_dir()
    assert chinese.database_path == tmp_path / "data" / "sites" / chinese_site_name / "db" / "devices.db"
