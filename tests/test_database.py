from netconsole.core.bootstrap import create_demo_context
from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device


def test_database_initializes_devices_table_with_connection_and_snmp_fields(tmp_path):
    db = Database(tmp_path / "devices.db")
    db.initialize()

    with db.connect() as conn:
        columns = [row["name"] for row in conn.execute("PRAGMA table_info(devices)").fetchall()]

    for column in (
        "ssh_enabled",
        "ssh_port",
        "telnet_enabled",
        "telnet_port",
        "ssh_username",
        "ssh_password",
        "telnet_username",
        "telnet_password",
        "snmp_v1_enabled",
        "snmp_v2c_enabled",
        "snmp_v3_enabled",
        "snmpv3_auth_password",
        "snmpv3_priv_password",
    ):
        assert column in columns
    for removed_column in (
        "credential_shared",
        "auth_mode",
        "ssh_auth_mode",
        "telnet_auth_mode",
        "username",
        "password",
        "serial_port",
        "baudrate",
        "data_bits",
        "parity",
        "stop_bits",
        "protocol",
        "port",
        "snmp_version",
    ):
        assert removed_column not in columns


def test_demo_context_creates_demo_data_once_with_connection_and_snmp_examples(tmp_path):
    context = create_demo_context(PathResolver(tmp_path))
    devices = context.repository.list()
    pairs = {(device.device_vendor, device.device_type) for device in devices}
    uuids = {device.device_uuid for device in devices}

    assert context.demo_inserted is True
    assert context.site.name == "demo"
    assert len(devices) == 5
    assert len(uuids) == len(devices)
    assert all(Device.is_valid_uuid(device.device_uuid) for device in devices)
    assert ("H3C", "SW") in pairs
    assert ("H3C", "AC") in pairs
    assert ("Huawei", "SW") in pairs
    assert ("Ruijie", "SW") in pairs
    assert ("H3C", "FW") in pairs
    assert all(not hasattr(device, "credential_shared") for device in devices)
    assert any(device.ssh_enabled and not device.telnet_enabled and device.ssh_username and device.ssh_password for device in devices)
    assert any(device.telnet_enabled and not device.ssh_enabled and not device.telnet_username and device.telnet_password for device in devices)
    assert any(device.ssh_enabled and device.telnet_enabled and device.ssh_username == device.telnet_username and device.ssh_password == device.telnet_password for device in devices)
    assert any(device.ssh_enabled and device.telnet_enabled and device.ssh_username != device.telnet_username for device in devices)
    assert any(
        device.snmp_v3_enabled
        and device.snmpv3_security_level == "AuthPriv"
        and device.snmpv3_auth_protocol == "SHA"
        and device.snmpv3_auth_password == "auth123456"
        and device.snmpv3_priv_protocol == "AES128"
        and device.snmpv3_priv_password == "priv123456"
        for device in devices
    )
    assert all(getattr(device, "device_type") != "Serial" for device in devices)

    second_context = create_demo_context(PathResolver(tmp_path))
    assert second_context.demo_inserted is False
    assert len(second_context.repository.list()) == len(devices)
