from netconsole.core.database import Database
from netconsole.models.device import Device
from netconsole.repositories.device_repository import DeviceRepository


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

    repository.delete(created.id)
    assert repository.list() == []


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
