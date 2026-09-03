import sqlite3

from netconsole.core.database import Database
from netconsole.models.device import Device
from netconsole.repositories.device_group_repository import (
    DEVICE_DEFAULT_GROUP_ORDER,
    DeviceGroupRepository,
    DuplicateGroupName,
    canonical_device_group_name,
)
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.device_group_service import group_filter_to_repository_value


def make_repository(tmp_path):
    db = Database(tmp_path / "devices.db")
    db.initialize()
    return DeviceRepository(db)


def test_device_repository_crud_search_and_filters(tmp_path):
    repository = make_repository(tmp_path)
    created = repository.create(Device(name="Core-SW", ip_address="10.0.0.1", station="Room-A", remark="core"))

    assert created.id is not None
    assert Device.is_valid_uuid(created.device_uuid)
    assert created.device_vendor == "H3C"

    original_uuid = created.device_uuid
    created.device_uuid = Device.new_uuid()
    created.remark = "updated"
    updated = repository.update(created)
    assert updated.remark == "updated"
    assert updated.device_uuid == original_uuid

    assert repository.list(search="Core")[0].id == created.id
    assert repository.list(search="10.0.0.1")[0].id == created.id
    assert repository.list(vendor="H3C")[0].id == created.id
    assert repository.list(device_type="SW")[0].id == created.id
    assert repository.get_by_uuid(str(original_uuid)).id == created.id
    assert repository.get_by_uuid(Device.new_uuid()) is None

    repository.delete(created.id)
    assert repository.list() == []


def test_device_repository_backup_is_consistent(tmp_path):
    repository = make_repository(tmp_path)
    created = repository.create(
        Device(name="Core-SW", primary_address="10.0.0.1")
    )
    backup_path = tmp_path / "backups" / "devices.sqlite"
    backup_path.parent.mkdir()

    repository.backup_to(backup_path)

    backup = DeviceRepository(Database(backup_path))
    restored = backup.get_by_uuid(str(created.device_uuid))
    assert restored is not None
    assert restored.name == "Core-SW"
    with Database(backup_path).connect() as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
    assert integrity is not None
    assert str(integrity[0]).casefold() == "ok"


def test_delete_many_by_uuid_is_all_or_nothing(tmp_path):
    repository = make_repository(tmp_path)
    first = repository.create(Device(name="SW1", primary_address="10.0.0.1"))
    second = repository.create(Device(name="SW2", primary_address="10.0.0.2"))

    try:
        repository.delete_many_by_uuid([str(first.device_uuid), Device.new_uuid()])
    except KeyError:
        pass
    else:
        raise AssertionError("missing UUID should abort the full batch")

    assert repository.get_by_uuid(str(first.device_uuid)) is not None
    assert repository.get_by_uuid(str(second.device_uuid)) is not None

    deleted = repository.delete_many_by_uuid([str(first.device_uuid), str(second.device_uuid)])

    assert deleted == [str(first.device_uuid), str(second.device_uuid)]
    assert repository.list() == []


def test_device_repository_list_uses_name_natural_order(tmp_path):
    repository = make_repository(tmp_path)
    repository.create(Device(name="LC10", primary_address="10.0.0.10"))
    repository.create(Device(name="LC2", primary_address="10.0.0.2"))
    repository.create(Device(name="LC1", primary_address="10.0.0.1"))

    assert [device.name for device in repository.list()] == ["LC1", "LC2", "LC10"]


def test_device_repository_natural_order_handles_padded_numeric_prefixes(tmp_path):
    repository = make_repository(tmp_path)
    for index, name in enumerate(
        ("02xxx", "01.xxx", "02.xxx", "01-xxx", "02-xxx", "01xxx"),
        start=1,
    ):
        repository.create(Device(name=name, primary_address=f"10.0.0.{index}"))

    ordered_names = [device.name for device in repository.list()]

    assert [int(name[:2]) for name in ordered_names] == [1, 1, 1, 2, 2, 2]


def test_device_repository_search_includes_group_and_device_type(tmp_path):
    database = Database(tmp_path / "devices.db")
    database.initialize()
    repository = DeviceRepository(database)
    groups = DeviceGroupRepository(database, "demo")
    onboard = groups.create("车载-MR")
    station = groups.create("车站")
    mr = repository.create(Device(name="MR2", primary_address="192.0.2.10", group_id=onboard.id, device_type="AC"))
    sw = repository.create(Device(name="SW1", primary_address="192.0.2.20", group_id=station.id, device_type="SW"))

    assert [device.id for device in repository.list(search="车载-MR")] == [mr.id]
    assert [device.id for device in repository.list(search="SW")] == [sw.id]


def test_device_uuid_must_be_unique(tmp_path):
    repository = make_repository(tmp_path)
    device_uuid = Device.new_uuid()

    repository.create(Device(name="SW1", ip_address="10.0.0.1", device_uuid=device_uuid))

    try:
        repository.create(Device(name="SW2", ip_address="10.0.0.2", device_uuid=device_uuid))
    except Exception as exc:
        assert "UNIQUE" in str(exc).upper()
    else:
        raise AssertionError("duplicate device_uuid should fail")


def test_telnet_can_be_enabled_with_ssh(tmp_path):
    repository = make_repository(tmp_path)

    created = repository.create(
        Device(
            name="Dual Protocol",
            ip_address="10.0.0.3",
            ssh_enabled=1,
            ssh_port=22,
            telnet_enabled=1,
            telnet_port=23,
        )
    )

    assert created.ssh_enabled == 1
    assert created.telnet_enabled == 1
    assert created.telnet_port == 23


def test_repository_saves_ssh_and_telnet_credentials_without_shared_flag(tmp_path):
    repository = make_repository(tmp_path)

    created = repository.create(
        Device(
            name="Credentials",
            ip_address="10.0.0.4",
            ssh_username="ssh",
            ssh_password="ssh-pwd",
            telnet_username="",
            telnet_password="tel-pwd",
        )
    )

    assert not hasattr(created, "credential_shared")
    assert created.ssh_username == "ssh"
    assert created.ssh_password == "ssh-pwd"
    assert created.telnet_username == ""
    assert created.telnet_password == "tel-pwd"


def test_repository_allows_blank_ssh_username_and_password(tmp_path):
    repository = make_repository(tmp_path)

    created = repository.create(
        Device(
            name="Blank SSH Credentials",
            ip_address="10.0.0.6",
            ssh_username="",
            ssh_password="",
        )
    )

    assert created.ssh_username == ""
    assert created.ssh_password == ""


def test_database_initialization_repairs_only_stale_reentry_markers_with_real_secrets(
    tmp_path,
):
    database = Database(tmp_path / "devices.db")
    database.initialize()
    repository = DeviceRepository(database)
    recoverable = repository.create(
        Device(
            name="Recoverable",
            ip_address="10.0.0.7",
            ssh_username="admin",
            ssh_password="still-present",
        )
    )
    missing = repository.create(
        Device(name="Missing", ip_address="10.0.0.8", ssh_username="admin")
    )
    connection = sqlite3.connect(database.path)
    try:
        for device_uuid in (recoverable.device_uuid, missing.device_uuid):
            connection.execute(
                "INSERT OR REPLACE INTO device_credential_states "
                "(device_uuid, credential_field, status, source, error_code, updated_at) "
                "VALUES (?, 'ssh_password', 'needs_reentry', 'imported_reference', "
                "'CREDENTIAL_REENTRY_REQUIRED', datetime('now'))",
                (device_uuid,),
            )
        connection.commit()
    finally:
        connection.close()

    database.initialize()

    connection = sqlite3.connect(database.path)
    try:
        states = dict(
            connection.execute(
                "SELECT device_uuid, status FROM device_credential_states "
                "WHERE credential_field = 'ssh_password'"
            ).fetchall()
        )
    finally:
        connection.close()
    assert states[str(recoverable.device_uuid)] == "available"
    assert states[str(missing.device_uuid)] == "needs_reentry"


def test_device_groups_are_site_scoped_and_filter_devices(tmp_path):
    db = Database(tmp_path / "devices.db")
    db.initialize()
    repository = DeviceRepository(db)
    groups = DeviceGroupRepository(db, "demo")

    core = groups.create(" 控制中心 ")
    other_site_group = DeviceGroupRepository(db, "other").create("控制中心")
    grouped = repository.create(Device(name="Core", ip_address="10.0.0.10", group_id=core.id))
    ungrouped = repository.create(Device(name="Edge", ip_address="10.0.0.11"))

    assert groups.list()[0].name == "控制中心"
    assert other_site_group.name == "控制中心"
    assert [device.id for device in repository.list(group_filter=core.id)] == [grouped.id]
    assert [device.id for device in repository.list(group_filter="__ungrouped__")] == [ungrouped.id]

    try:
        groups.create("控制中心")
    except DuplicateGroupName:
        pass
    else:
        raise AssertionError("duplicate group name should fail within a site")

    groups.delete(int(core.id))

    assert repository.get(int(grouped.id)).group_id is None


def test_device_group_list_uses_fixed_business_order_and_natural_others(tmp_path):
    db = Database(tmp_path / "devices.db")
    db.initialize()
    groups = DeviceGroupRepository(db, "demo")
    for name in ("10组", "车载-3SW", "车载 MR", "车站", "bOcc", "cocc", "2组"):
        groups.create(name)

    names = [group.name for group in groups.list()]

    assert names[:5] == ["cocc", "bOcc", "车站", "车载 MR", "车载-3SW"]
    assert names[5:] == ["2组", "10组"]
    assert DEVICE_DEFAULT_GROUP_ORDER == ("COCC", "BOCC", "车站", "车载-MR", "车载-SW")
    assert canonical_device_group_name(" 车载-3SW ") == "车载-SW"


def test_group_filter_value_keeps_group_id_for_repository_filter(tmp_path):
    db = Database(tmp_path / "devices.db")
    db.initialize()
    repository = DeviceRepository(db)
    groups = DeviceGroupRepository(db, "demo")
    target_group = groups.create("Onboard")
    other_group = groups.create("Station")
    target = repository.create(Device(name="MR-A", ip_address="10.0.0.1", group_id=target_group.id))
    repository.create(Device(name="SW-A", ip_address="10.0.0.2", group_id=other_group.id))

    group_filter = group_filter_to_repository_value(target_group.id)

    assert isinstance(group_filter, int)
    assert [device.id for device in repository.list(group_filter=group_filter)] == [target.id]


def test_repository_updates_https_port(tmp_path):
    repository = make_repository(tmp_path)
    created = repository.create(Device(name="AC", ip_address="10.0.0.51", device_type="AC"))

    updated = repository.update_https_port(int(created.id), 8443)

    assert updated.https_port == 8443
    assert repository.get(int(created.id)).https_port == 8443

    try:
        repository.update_https_port(int(created.id), 70000)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid HTTPS port should fail")
