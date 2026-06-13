import json

import pytest

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.core.sites import SiteManager
from netconsole.models.device import Device
from netconsole.repositories.device_repository import DeviceRepository


def test_site_manager_creates_demo_and_chinese_site(tmp_path):
    manager = SiteManager(PathResolver(tmp_path))

    demo = manager.ensure_demo_site()
    legacy_method_demo = manager.ensure_default_site()
    chinese_site_name = "\u534e\u4e1c\u7ad9\u70b9"
    chinese = manager.create_site(chinese_site_name)

    assert demo.name == "demo"
    assert legacy_method_demo.name == "demo"
    assert demo.database_path == tmp_path / "data" / "sites" / "demo" / "db" / "devices.db"
    assert chinese.root_path.is_dir()
    assert chinese.database_path == tmp_path / "data" / "sites" / chinese_site_name / "db" / "devices.db"


def test_demo_site_has_demo_data_and_new_site_is_empty(tmp_path):
    manager = SiteManager(PathResolver(tmp_path))

    manager.ensure_demo_site()
    empty_site = manager.create_site("空站点")

    demo_repo = DeviceRepository(Database(tmp_path / "data" / "sites" / "demo" / "db" / "devices.db"))
    empty_repo = DeviceRepository(Database(empty_site.database_path))
    assert len(demo_repo.list()) == 8
    assert empty_repo.list() == []


@pytest.mark.parametrize("name", ["", "bad/name", "bad\\name", "bad:name", "bad*name", ".", ".."])
def test_invalid_site_names_are_rejected(tmp_path, name):
    manager = SiteManager(PathResolver(tmp_path))

    with pytest.raises(ValueError):
        manager.create_site(name)


def test_duplicate_site_name_is_rejected(tmp_path):
    manager = SiteManager(PathResolver(tmp_path))
    manager.create_site("A")

    with pytest.raises(ValueError):
        manager.create_site("A")


def test_switch_site_updates_app_json_current_site(tmp_path):
    paths = PathResolver(tmp_path)
    manager = SiteManager(paths)
    manager.create_site("A")

    manager.switch_site("demo")

    config = json.loads(paths.app_config_path.read_text(encoding="utf-8"))
    assert config["current_site"] == "demo"
    assert config["recent_sites"][0] == "demo"


def test_new_site_repository_reads_its_own_database(tmp_path):
    paths = PathResolver(tmp_path)
    manager = SiteManager(paths)
    site_a = manager.create_site("A")
    site_b = manager.create_site("B")
    repo_a = DeviceRepository(Database(site_a.database_path))
    repo_b = DeviceRepository(Database(site_b.database_path))

    repo_a.create(Device(name="A-SW", ip_address="10.0.0.1"))
    repo_b.create(Device(name="B-SW", ip_address="10.0.0.2"))

    assert [device.name for device in repo_a.list()] == ["A-SW"]
    assert [device.name for device in repo_b.list()] == ["B-SW"]


def test_missing_current_site_falls_back_to_demo(tmp_path):
    paths = PathResolver(tmp_path)
    manager = SiteManager(paths)
    manager.ensure_app_config()
    paths.app_config_path.write_text(json.dumps({"current_site": "missing", "recent_sites": ["missing"]}), encoding="utf-8")

    assert manager.get_current_site() == "demo"
    config = json.loads(paths.app_config_path.read_text(encoding="utf-8"))
    assert config["current_site"] == "demo"
