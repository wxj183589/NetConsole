import csv
from datetime import datetime

from netconsole.core.database import Database
from netconsole.models.device import Device
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.device_import_export import (
    EXPORT_FIELDS,
    SNMPV3_AUTH_PROTOCOLS,
    SNMPV3_PRIV_PROTOCOLS,
    SNMPV3_SECURITY_LEVELS,
    TEMPLATE_EXAMPLE_ROW,
    TEMPLATE_FIELDS,
    DeviceImportExportService,
    make_device_export_filename,
)


def make_service(tmp_path):
    db = Database(tmp_path / "devices.db")
    db.initialize()
    repository = DeviceRepository(db)
    return repository, DeviceImportExportService(repository)


def read_csv(path):
    with path.open("r", newline="", encoding="utf-8-sig") as file:
        return list(csv.reader(file))


def write_rows(path, rows):
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        csv.writer(file).writerows(rows)


def write_dict_rows(path, rows):
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=EXPORT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def test_export_template_csv_has_connection_and_snmp_fields(tmp_path):
    repository, service = make_service(tmp_path)
    path = tmp_path / "template.csv"

    service.export_template_csv(path)
    rows = read_csv(path)
    result = service.import_csv(path)
    imported = repository.list()[0]

    assert rows == [TEMPLATE_FIELDS, TEMPLATE_EXAMPLE_ROW]
    for field in ("SSH启用", "SSH端口", "Telnet启用", "Telnet端口", "SNMPv1", "SNMPv2c", "SNMPv3"):
        assert field in rows[0]
    assert result.created == 1
    assert imported.ssh_enabled == 1
    assert imported.telnet_enabled == 0
    assert imported.snmp_v2c_enabled == 1


def test_simplified_template_import_defaults(tmp_path):
    repository, service = make_service(tmp_path)
    csv_path = tmp_path / "devices.csv"
    write_rows(
        csv_path,
        [
            TEMPLATE_FIELDS,
            ["Core", "192.168.1.1", "", "OCC", "", "", "", "", "", "admin", "pwd", "enable", "", "", "", "", "", "", "core", "remark"],
        ],
    )

    result = service.import_csv(csv_path)
    imported = repository.list()[0]

    assert result.created == 1
    assert imported.device_vendor == "H3C"
    assert imported.device_type == "SW"
    assert imported.ssh_enabled == 1
    assert imported.ssh_port == 22
    assert imported.telnet_enabled == 0
    assert imported.telnet_port == 23
    assert imported.snmp_v1_enabled == 0
    assert imported.snmp_v2c_enabled == 1
    assert imported.snmp_v3_enabled == 0
    assert imported.snmp_port == 161


def test_simplified_template_import_snmpv3_yes_sets_v3_defaults(tmp_path):
    repository, service = make_service(tmp_path)
    csv_path = tmp_path / "snmpv3_template.csv"
    write_rows(
        csv_path,
        [
            TEMPLATE_FIELDS,
            ["Core", "192.168.1.1", "", "OCC", "", "", "", "", "", "admin", "pwd", "", "", "", "是", "", "", "", "core", "remark"],
        ],
    )

    result = service.import_csv(csv_path)
    imported = repository.list()[0]

    assert result.created == 1
    assert imported.snmp_v3_enabled == 1
    assert imported.snmpv3_security_level == "noAuthNoPriv"
    assert imported.snmpv3_auth_protocol == "SHA"
    assert imported.snmpv3_priv_protocol == "AES128"


def test_full_export_contains_new_fields_and_not_removed_fields(tmp_path):
    repository, service = make_service(tmp_path)
    device = repository.create(Device(name="Core", ip_address="192.168.1.1", ssh_enabled=1, telnet_enabled=1))
    export_path = tmp_path / "export.csv"

    service.export_csv(export_path)
    rows = read_csv(export_path)

    assert rows[0] == EXPORT_FIELDS
    for field in ("ssh_enabled", "ssh_port", "telnet_enabled", "telnet_port", "snmp_v1_enabled", "snmp_v2c_enabled", "snmp_v3_enabled"):
        assert field in rows[0]
    for removed in ("protocol", "port", "serial_port", "baudrate", "data_bits", "parity", "stop_bits", "snmp_version"):
        assert removed not in rows[0]
    assert rows[1][0] == str(device.id)
    assert rows[1][1] == device.device_uuid


def test_full_csv_import_supports_new_fields(tmp_path):
    repository, service = make_service(tmp_path)
    csv_path = tmp_path / "full.csv"
    write_dict_rows(
        csv_path,
        [
            {
                "name": "Imported",
                "ip_address": "192.168.1.20",
                "ssh_enabled": "1",
                "ssh_port": "2022",
                "telnet_enabled": "1",
                "telnet_port": "2323",
                "snmp_v1_enabled": "1",
                "snmp_v2c_enabled": "1",
                "snmp_v3_enabled": "1",
                "snmpv3_security_level": "AuthPriv",
                "snmpv3_auth_protocol": "SHA",
                "snmpv3_auth_password": "authpass",
                "snmpv3_priv_protocol": "AES",
                "snmpv3_priv_password": "privpass",
            }
        ],
    )

    result = service.import_csv(csv_path)
    imported = repository.list()[0]

    assert result.created == 1
    assert imported.ssh_port == 2022
    assert imported.telnet_enabled == 1
    assert imported.telnet_port == 2323
    assert imported.snmp_v1_enabled == 1
    assert imported.snmp_v2c_enabled == 1
    assert imported.snmp_v3_enabled == 1
    assert imported.snmpv3_auth_password == "authpass"
    assert imported.snmpv3_priv_protocol == "AES128"
    assert imported.snmpv3_priv_password == "privpass"


def test_snmpv3_dropdown_options_do_not_include_blank_items():
    assert SNMPV3_SECURITY_LEVELS == ("noAuthNoPriv", "AuthNoPriv", "AuthPriv")
    assert SNMPV3_AUTH_PROTOCOLS == ("MD5", "SHA")
    assert SNMPV3_PRIV_PROTOCOLS == ("DES56", "3DES", "AES128", "AES192", "AES256")
    assert "" not in SNMPV3_SECURITY_LEVELS
    assert "" not in SNMPV3_AUTH_PROTOCOLS
    assert "" not in SNMPV3_PRIV_PROTOCOLS


def test_full_csv_authpriv_blank_priv_protocol_defaults_to_aes128(tmp_path):
    repository, service = make_service(tmp_path)
    csv_path = tmp_path / "blank_priv.csv"
    write_dict_rows(
        csv_path,
        [
            {
                "name": "AuthPrivBlankPriv",
                "ip_address": "192.168.1.40",
                "snmp_v3_enabled": "1",
                "snmpv3_security_level": "AuthPriv",
                "snmpv3_auth_protocol": "",
                "snmpv3_priv_protocol": "",
            }
        ],
    )

    result = service.import_csv(csv_path)
    imported = repository.list()[0]

    assert result.created == 1
    assert imported.snmpv3_auth_protocol == "SHA"
    assert imported.snmpv3_priv_protocol == "AES128"


def test_import_maps_legacy_snmpv3_priv_protocol_values(tmp_path):
    repository, service = make_service(tmp_path)
    csv_path = tmp_path / "legacy_snmp.csv"
    write_dict_rows(
        csv_path,
        [
            {
                "name": "OldDES",
                "ip_address": "192.168.1.41",
                "snmp_v3_enabled": "1",
                "snmpv3_security_level": "AuthPriv",
                "snmpv3_priv_protocol": "DES",
            },
            {
                "name": "OldAES",
                "ip_address": "192.168.1.42",
                "snmp_v3_enabled": "1",
                "snmpv3_security_level": "AuthPriv",
                "snmpv3_priv_protocol": "AES",
            },
        ],
    )

    result = service.import_csv(csv_path)
    devices = {device.name: device for device in repository.list()}

    assert result.created == 2
    assert devices["OldDES"].snmpv3_priv_protocol == "DES56"
    assert devices["OldAES"].snmpv3_priv_protocol == "AES128"


def test_import_legacy_protocol_port_template(tmp_path):
    repository, service = make_service(tmp_path)
    csv_path = tmp_path / "legacy.csv"
    write_rows(csv_path, [["设备名称", "IP地址", "协议", "端口"], ["LegacyTelnet", "192.168.1.30", "telnet", "2323"]])

    result = service.import_csv(csv_path)
    imported = repository.list()[0]

    assert result.created == 1
    assert imported.ssh_enabled == 0
    assert imported.telnet_enabled == 1
    assert imported.telnet_port == 2323


def test_import_rejects_duplicate_uuid_and_no_connection(tmp_path):
    repository, service = make_service(tmp_path)
    device_uuid = Device.new_uuid()
    repository.create(Device(name="SW0", ip_address="192.168.0.1", device_uuid=device_uuid))
    csv_path = tmp_path / "bad.csv"
    write_dict_rows(
        csv_path,
        [
            {"device_uuid": device_uuid, "name": "Dup", "ip_address": "192.168.1.1"},
            {"name": "NoConn", "ip_address": "192.168.1.2", "ssh_enabled": "0", "telnet_enabled": "0"},
        ],
    )

    result = service.import_csv(csv_path)

    assert result.created == 0
    assert result.skipped == 2
    assert "Duplicate device_uuid" in result.errors[0]
    assert "At least one" in result.errors[1]


def test_full_export_csv_import_preserves_valid_uuid_and_rejects_duplicate(tmp_path):
    source_repository, source_service = make_service(tmp_path / "source")
    source_device = source_repository.create(Device(name="SW1", ip_address="192.168.1.1"))
    export_path = tmp_path / "export.csv"
    source_service.export_csv(export_path)

    target_repository, target_service = make_service(tmp_path / "target")
    first = target_service.import_csv(export_path)
    imported = target_repository.list()[0]
    second = target_service.import_csv(export_path)

    assert first.created == 1
    assert imported.device_uuid == source_device.device_uuid
    assert second.created == 0
    assert second.skipped == 1


def test_make_device_export_filename_formats_site_name_and_local_time():
    now = datetime(2026, 6, 12, 18, 15)

    assert make_device_export_filename("demo", now) == "demo_2026-06-12-1815.csv"
    assert make_device_export_filename("宁波6号线", now) == "宁波6号线_2026-06-12-1815.csv"
    assert make_device_export_filename('bad<>:"/\\|?*name', now) == "bad_________name_2026-06-12-1815.csv"
