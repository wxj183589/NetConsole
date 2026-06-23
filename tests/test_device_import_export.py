import csv
from datetime import datetime

import pytest

from netconsole.core.database import Database
from netconsole.models.device import Device
from netconsole.repositories.device_group_repository import DeviceGroupRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.device_import_export import (
    CSV_ENCODING_ERROR,
    EXPORT_FIELDS,
    SNMPV3_AUTH_PROTOCOLS,
    SNMPV3_PRIV_PROTOCOLS,
    SNMPV3_SECURITY_LEVELS,
    TEMPLATE_EXAMPLE_ROWS,
    TEMPLATE_FIELDS,
    DeviceImportExportService,
    make_device_export_filename,
)


def make_service(tmp_path):
    db = Database(tmp_path / "devices.db")
    db.initialize()
    repository = DeviceRepository(db)
    return repository, DeviceImportExportService(repository)


def make_group_service(tmp_path):
    db = Database(tmp_path / "devices.db")
    db.initialize()
    repository = DeviceRepository(db)
    groups = DeviceGroupRepository(db, "demo")
    groups.ensure_default_groups()
    return repository, groups, DeviceImportExportService(repository, groups)


def read_csv(path):
    with path.open("r", newline="", encoding="utf-8-sig") as file:
        return list(csv.reader(file))


def write_rows(path, rows, encoding="utf-8-sig"):
    with path.open("w", newline="", encoding=encoding) as file:
        csv.writer(file).writerows(rows)


def write_dict_rows(path, fieldnames, rows):
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def template_row(**overrides):
    row = {field: "" for field in TEMPLATE_FIELDS}
    row.update(
        {
            TEMPLATE_FIELDS[0]: "Core",
            TEMPLATE_FIELDS[2]: "192.168.1.1",
            TEMPLATE_FIELDS[4]: "SSH",
            TEMPLATE_FIELDS[5]: "22",
            TEMPLATE_FIELDS[6]: "admin",
            TEMPLATE_FIELDS[7]: "pwd",
            TEMPLATE_FIELDS[8]: "H3C",
            TEMPLATE_FIELDS[9]: "SW",
        }
    )
    row.update(overrides)
    return [row[field] for field in TEMPLATE_FIELDS]


def test_template_csv_uses_new_device_model_fields_and_imports_examples(tmp_path):
    repository, service = make_service(tmp_path)
    path = tmp_path / "template.csv"

    service.export_template_csv(path)
    rows = read_csv(path)
    result = service.import_csv(path)
    devices = repository.list()

    assert rows == [TEMPLATE_FIELDS, *TEMPLATE_EXAMPLE_ROWS]
    assert "ip_address" not in TEMPLATE_FIELDS
    assert "sysname" not in TEMPLATE_FIELDS
    assert len(TEMPLATE_FIELDS) == len(TEMPLATE_EXAMPLE_ROWS[0])
    assert result.created == len(TEMPLATE_EXAMPLE_ROWS)
    assert all(device.primary_address for device in devices)
    assert all(hasattr(device, "system_name") for device in devices)


def test_template_import_maps_primary_backup_system_name_and_tunnel_fields(tmp_path):
    repository, service = make_service(tmp_path)
    csv_path = tmp_path / "devices.csv"
    write_rows(
        csv_path,
        [
            TEMPLATE_FIELDS,
            template_row(
                **{
                    TEMPLATE_FIELDS[0]: "AC",
                    TEMPLATE_FIELDS[1]: "AC-SYS",
                    TEMPLATE_FIELDS[2]: "10.0.0.1",
                    TEMPLATE_FIELDS[3]: "10.0.0.2",
                    TEMPLATE_FIELDS[16]: "yes",
                    TEMPLATE_FIELDS[17]: "172.16.0.10",
                    TEMPLATE_FIELDS[18]: "2022",
                    TEMPLATE_FIELDS[19]: "jump",
                    TEMPLATE_FIELDS[20]: "jump-pwd",
                    TEMPLATE_FIELDS[21]: "10022",
                }
            ),
        ],
    )

    result = service.import_csv(csv_path)
    imported = repository.list()[0]

    assert result.created == 1
    assert imported.name == "AC"
    assert imported.system_name == "AC-SYS"
    assert imported.primary_address == "10.0.0.1"
    assert imported.backup_address == "10.0.0.2"
    assert imported.tunnel_enabled == 1
    assert imported.tunnel1_enabled == 1
    assert imported.tunnel1_host == "172.16.0.10"
    assert imported.tunnel1_port == 2022
    assert imported.tunnel1_username == "jump"
    assert imported.tunnel1_password == "jump-pwd"
    assert imported.tunnel1_local_port == 10022


def test_template_import_keeps_excel_header_compatibility_for_old_address_names(tmp_path):
    aliases = ["IP", "host", "address", "ip_address"]
    for alias in aliases:
        repository, service = make_service(tmp_path / alias)
        csv_path = tmp_path / alias / "devices.csv"
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        headers = list(TEMPLATE_FIELDS)
        headers[2] = alias
        write_rows(csv_path, [headers, template_row(**{TEMPLATE_FIELDS[0]: f"SW-{alias}", TEMPLATE_FIELDS[2]: "192.168.10.1"})])

        result = service.import_csv(csv_path)

        assert result.created == 1
        assert repository.list()[0].primary_address == "192.168.10.1"


def test_template_import_exports_and_imports_group_column(tmp_path):
    repository, groups, service = make_group_service(tmp_path)
    csv_path = tmp_path / "devices.csv"
    write_rows(
        csv_path,
        [
            TEMPLATE_FIELDS,
            template_row(**{TEMPLATE_FIELDS[0]: "Vehicle AP", TEMPLATE_FIELDS[10]: "Vehicle"}),
        ],
    )

    result = service.import_csv(csv_path)
    imported = repository.list()[0]
    group_lookup = {group.name: group.id for group in groups.list()}

    assert result.created == 1
    assert result.groups_created == 1
    assert imported.group_id == group_lookup["Vehicle"]


def test_template_import_supports_gbk_and_utf8_sig_csv(tmp_path):
    for encoding in ("utf-8-sig", "gbk", "gb2312"):
        repository, service = make_service(tmp_path / encoding)
        csv_path = tmp_path / encoding / "devices.csv"
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        write_rows(csv_path, [TEMPLATE_FIELDS, template_row(**{TEMPLATE_FIELDS[0]: f"SW-{encoding}"})], encoding)

        result = service.import_csv(csv_path)

        assert result.created == 1
        assert repository.list()[0].primary_address == "192.168.1.1"


def test_csv_import_encoding_failure_uses_friendly_error(tmp_path):
    _repository, service = make_service(tmp_path)
    csv_path = tmp_path / "bad_encoding.csv"
    csv_path.write_bytes(b"\xff\xff\xff")

    with pytest.raises(ValueError) as exc_info:
        service.import_csv(csv_path)

    assert str(exc_info.value) == CSV_ENCODING_ERROR
    assert "codec" not in str(exc_info.value).lower()


def test_full_export_contains_new_fields_and_not_removed_database_fields(tmp_path):
    repository, service = make_service(tmp_path)
    device = repository.create(
        Device(
            name="Core",
            system_name="CORE-SYS",
            primary_address="192.168.1.1",
            backup_address="192.168.2.1",
            tunnel_enabled=1,
            tunnel1_enabled=1,
            tunnel1_host="10.0.0.10",
        )
    )
    export_path = tmp_path / "export.csv"

    service.export_csv(export_path)
    rows = read_csv(export_path)

    assert rows[0] == EXPORT_FIELDS
    for field in ("system_name", "primary_address", "backup_address", "tunnel_enabled", "tunnel1_host"):
        assert field in rows[0]
    for removed in ("ip_address", "sysname", "host", "主机地址"):
        assert removed not in rows[0]
    assert rows[1][0] == str(device.id)
    assert rows[1][rows[0].index("system_name")] == "CORE-SYS"
    assert rows[1][rows[0].index("primary_address")] == "192.168.1.1"


def test_full_csv_import_supports_current_fields_and_snmp_defaults(tmp_path):
    repository, service = make_service(tmp_path)
    csv_path = tmp_path / "full.csv"
    write_dict_rows(
        csv_path,
        EXPORT_FIELDS,
        [
            {
                "name": "Imported",
                "system_name": "IM-SYS",
                "primary_address": "192.168.1.20",
                "ssh_enabled": "1",
                "ssh_port": "2022",
                "telnet_enabled": "1",
                "telnet_port": "2323",
                "ssh_username": "ssh",
                "ssh_password": "ssh-pwd",
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
    assert imported.system_name == "IM-SYS"
    assert imported.primary_address == "192.168.1.20"
    assert imported.ssh_port == 2022
    assert imported.telnet_enabled == 1
    assert imported.telnet_port == 2323
    assert imported.snmpv3_auth_protocol == "SHA"
    assert imported.snmpv3_priv_protocol == "AES128"


def test_import_rejects_duplicate_uuid_and_no_connection(tmp_path):
    repository, service = make_service(tmp_path)
    device_uuid = Device.new_uuid()
    repository.create(Device(name="SW0", primary_address="192.168.0.1", device_uuid=device_uuid))
    csv_path = tmp_path / "bad.csv"
    write_dict_rows(
        csv_path,
        EXPORT_FIELDS,
        [
            {"device_uuid": device_uuid, "name": "Dup", "primary_address": "192.168.1.1"},
            {"name": "NoConn", "primary_address": "192.168.1.2", "ssh_enabled": "0", "telnet_enabled": "0"},
        ],
    )

    result = service.import_csv(csv_path)

    assert result.created == 0
    assert result.skipped == 2
    assert "Duplicate device_uuid" in result.errors[0]
    assert "At least one" in result.errors[1]


def test_full_export_csv_import_preserves_valid_uuid_and_rejects_duplicate(tmp_path):
    source_repository, source_service = make_service(tmp_path / "source")
    source_device = source_repository.create(Device(name="SW1", primary_address="192.168.1.1"))
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


def test_snmpv3_dropdown_options_do_not_include_blank_items():
    assert SNMPV3_SECURITY_LEVELS == ("noAuthNoPriv", "AuthNoPriv", "AuthPriv")
    assert SNMPV3_AUTH_PROTOCOLS == ("MD5", "SHA")
    assert SNMPV3_PRIV_PROTOCOLS == ("DES56", "3DES", "AES128", "AES192", "AES256")
    assert "" not in SNMPV3_SECURITY_LEVELS
    assert "" not in SNMPV3_AUTH_PROTOCOLS
    assert "" not in SNMPV3_PRIV_PROTOCOLS


def test_make_device_export_filename_formats_site_name_and_local_time():
    now = datetime(2026, 6, 12, 18, 15)

    assert make_device_export_filename("demo", now) == "demo_2026-06-12-1815.csv"
    assert make_device_export_filename("宁波6号线", now) == "宁波6号线_2026-06-12-1815.csv"
    assert make_device_export_filename('bad<>:"/\\|?*name', now) == "bad_________name_2026-06-12-1815.csv"
