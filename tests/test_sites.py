import json

import pytest

from netconsole.core.database import Database, DatabaseSchemaMismatchError
from netconsole.core.paths import PathResolver
from netconsole.core.sites import SiteManager
from netconsole.models.device import Device
from netconsole.repositories.device_group_repository import DEFAULT_DEVICE_GROUPS, DeviceGroupRepository
from netconsole.repositories.device_repository import DeviceRepository


def test_site_manager_creates_demo_and_chinese_site(tmp_path):
    manager = SiteManager(PathResolver(tmp_path))

    demo = manager.ensure_demo_site()
    legacy_method_demo = manager.ensure_default_site()
    chinese_site_name = "\u534e\u4e1c\u7ad9\u70b9"
    chinese = manager.create_site(chinese_site_name)

    assert demo.name == "demo"
    assert legacy_method_demo.name == "demo"
    assert demo.database_path == tmp_path / "sites" / "demo" / "db" / "devices.db"
    assert chinese.root_path.is_dir()
    assert chinese.database_path == tmp_path / "sites" / chinese_site_name / "db" / "devices.db"


def test_new_site_root_has_only_minimal_layout(tmp_path):
    paths = PathResolver(tmp_path)
    manager = SiteManager(paths)

    site = manager.create_site("A")

    root_names = {path.name for path in site.root_path.iterdir()}
    assert {"db", "site_meta.json"}.issubset(root_names)
    assert not {"raw", "parsed", "reports", "downloads", "tasks", "metrics", "rail_transit", "network_tools", "backups"} & root_names
    assert "files" not in root_names
    assert "cache" not in root_names


def test_demo_site_has_demo_data_and_new_site_is_empty(tmp_path):
    manager = SiteManager(PathResolver(tmp_path))

    manager.ensure_demo_site()
    empty_site = manager.create_site("空站点")

    demo_repo = DeviceRepository(Database(tmp_path / "sites" / "demo" / "db" / "devices.db"))
    empty_repo = DeviceRepository(Database(empty_site.database_path))
    assert len(demo_repo.list()) == 8
    assert empty_repo.list() == []


def test_site_database_ensures_default_device_groups(tmp_path):
    manager = SiteManager(PathResolver(tmp_path))
    site = manager.create_site("A")
    database = Database(site.database_path)
    groups = DeviceGroupRepository(database, "A")

    assert [(group.name, group.sort_order) for group in groups.list()] == list(DEFAULT_DEVICE_GROUPS)

    manager.ensure_site("A")

    assert [group.name for group in groups.list()] == [name for name, _sort_order in DEFAULT_DEVICE_GROUPS]


def test_default_device_groups_do_not_create_custom_group(tmp_path):
    site = SiteManager(PathResolver(tmp_path)).create_site("A")
    groups = DeviceGroupRepository(Database(site.database_path), "A")

    assert [group.name for group in groups.list()] == [name for name, _sort_order in DEFAULT_DEVICE_GROUPS]


def test_empty_legacy_custom_group_is_removed_on_site_init(tmp_path):
    paths = PathResolver(tmp_path)
    manager = SiteManager(paths)
    site = manager.create_site("legacy")
    database = Database(site.database_path)
    groups = DeviceGroupRepository(database, "legacy")
    groups.create("自定义")

    manager.ensure_site("legacy")

    assert "自定义" not in [group.name for group in groups.list()]


def test_legacy_custom_group_with_devices_is_kept_as_user_group(tmp_path):
    paths = PathResolver(tmp_path)
    manager = SiteManager(paths)
    site = manager.create_site("legacy")
    database = Database(site.database_path)
    groups = DeviceGroupRepository(database, "legacy")
    custom = groups.create("自定义")
    DeviceRepository(database).create(Device(name="CustomDevice", ip_address="10.0.0.1", group_id=custom.id))

    manager.ensure_site("legacy")

    assert [group.name for group in groups.list()] == [name for name, _sort_order in DEFAULT_DEVICE_GROUPS] + ["自定义"]


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


def test_site_metadata_supports_line_system_and_network_domain(tmp_path):
    manager = SiteManager(PathResolver(tmp_path))

    site = manager.create_site(
        "杭州4号线-信号A网",
        line_name="杭州4号线",
        system_type="信号",
        network_domain="A网",
        remark="信号 A 网局点",
    )
    loaded = manager.ensure_site("杭州4号线-信号A网")

    assert site.display_name == "杭州4号线-信号A网"
    assert loaded.line_name == "杭州4号线"
    assert loaded.system_type == "信号"
    assert loaded.network_domain == "A网"
    assert loaded.remark == "信号 A 网局点"


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


def test_existing_site_database_without_metadata_still_requires_rebuild(tmp_path):
    paths = PathResolver(tmp_path)
    site_root = paths.ensure_site_dirs("legacy")
    db = Database(site_root / "db" / "devices.db")
    with db.connect() as conn:
        conn.execute(
            """
            CREATE TABLE devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_uuid TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                ip_address TEXT NOT NULL,
                device_vendor TEXT NOT NULL DEFAULT 'H3C',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO devices (device_uuid, name, ip_address, created_at, updated_at)
            VALUES ('legacy-uuid', 'AC-OLD', '10.122.100.10', '2026-06-19T10:00:00', '2026-06-19T10:00:00')
            """
        )
        conn.commit()

    with pytest.raises(DatabaseSchemaMismatchError):
        SiteManager(paths).ensure_site("legacy")

    with Database(site_root / "db" / "devices.db").connect() as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(devices)").fetchall()}
        count = conn.execute("SELECT COUNT(*) AS count FROM devices").fetchone()["count"]

    assert "https_port" not in columns
    assert count == 1


def test_missing_current_site_falls_back_to_demo(tmp_path):
    paths = PathResolver(tmp_path)
    manager = SiteManager(paths)
    manager.ensure_app_config()
    paths.app_config_path.write_text(json.dumps({"current_site": "missing", "recent_sites": ["missing"]}), encoding="utf-8")

    assert manager.get_current_site() == "demo"
    config = json.loads(paths.app_config_path.read_text(encoding="utf-8"))
    assert config["current_site"] == "demo"


def test_missing_current_site_selects_the_only_existing_site(tmp_path):
    paths = PathResolver(tmp_path)
    manager = SiteManager(paths)
    manager.ensure_site("line-a")
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.app_config_path.write_text(
        json.dumps({"current_site": "missing"}),
        encoding="utf-8",
    )

    assert manager.get_current_site() == "line-a"


def test_persistent_storage_refuses_to_guess_between_existing_sites(tmp_path):
    paths = PathResolver(tmp_path)
    manager = SiteManager(paths)
    manager.ensure_site("line-a")
    manager.ensure_site("line-b")
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.app_config_path.write_text(
        json.dumps({"current_site": "missing"}),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="多个局点"):
        manager.get_current_site()

    assert "demo" not in manager.list_sites()
