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
            TEMPLATE_FIELDS[1]: "192.168.1.1",
            TEMPLATE_FIELDS[3]: "SSH",
            TEMPLATE_FIELDS[4]: "22",
            TEMPLATE_FIELDS[5]: "admin",
            TEMPLATE_FIELDS[6]: "pwd",
            TEMPLATE_FIELDS[7]: "H3C",
            TEMPLATE_FIELDS[8]: "SW",
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
    assert "归属站点" in TEMPLATE_FIELDS
    hidden = {"系统名称", "站点/位置", "SNMP版本", "SNMP端口", "只读团体字", "读写团体字", "隧道主机1本地端口", "隧道主机2本地端口", "主机地址", "IP", "host", "address", "ip_address"}
    assert hidden.isdisjoint(TEMPLATE_FIELDS)
    assert len(TEMPLATE_FIELDS) == len(TEMPLATE_EXAMPLE_ROWS[0])
    assert result.created == len(TEMPLATE_EXAMPLE_ROWS)
    assert all(device.primary_address for device in devices)
    assert all(device.system_name is None for device in devices)


def test_template_import_maps_primary_backup_and_tunnel_fields(tmp_path):
    repository, service = make_service(tmp_path)
    csv_path = tmp_path / "devices.csv"
    write_rows(
        csv_path,
        [
            TEMPLATE_FIELDS,
            template_row(
                **{
                    TEMPLATE_FIELDS[0]: "AC",
                    TEMPLATE_FIELDS[1]: "10.0.0.1",
                    TEMPLATE_FIELDS[2]: "10.0.0.2",
                    TEMPLATE_FIELDS[11]: "yes",
                    TEMPLATE_FIELDS[12]: "172.16.0.10",
                    TEMPLATE_FIELDS[13]: "2022",
                    TEMPLATE_FIELDS[14]: "jump",
                    TEMPLATE_FIELDS[15]: "jump-pwd",
                }
            ),
        ],
    )

    result = service.import_csv(csv_path)
    imported = repository.list()[0]

    assert result.created == 1
    assert imported.name == "AC"
    assert imported.system_name is None
    assert imported.primary_address == "10.0.0.1"
    assert imported.backup_address == "10.0.0.2"
    assert imported.tunnel_enabled == 1
    assert imported.tunnel1_enabled == 1
    assert imported.tunnel1_host == "172.16.0.10"
    assert imported.tunnel1_port == 2022
    assert imported.tunnel1_username == "jump"
    assert imported.tunnel1_password == "jump-pwd"
    assert imported.tunnel1_local_port is None


def test_template_import_enables_tunnels_from_host_presence(tmp_path):
    repository, service = make_service(tmp_path)
    csv_path = tmp_path / "devices.csv"
    write_dict_rows(
        csv_path,
        EXPORT_FIELDS,
        [
            {
                "设备名称": "AC",
                "主用地址": "10.0.0.1",
                "协议": "SSH",
                "端口": "22",
                "用户名": "admin",
                "密码": "pwd",
                "厂商": "H3C",
                "设备类型": "AC",
                "是否启用SSH隧道": "否",
                "隧道主机1地址": "172.16.0.10",
                "隧道主机2地址": "",
            }
        ],
    )

    result = service.import_csv(csv_path)
    imported = repository.list()[0]

    assert result.created == 1
    assert imported.tunnel_enabled == 1
    assert imported.tunnel1_enabled == 1
    assert imported.tunnel2_enabled == 0


def test_template_import_rejects_old_headers(tmp_path):
    aliases = ["主机地址", "IP", "host", "address", "ip_address", "站点/位置"]
    for alias in aliases:
        repository, service = make_service(tmp_path / alias)
        csv_path = tmp_path / alias / "devices.csv"
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        headers = list(TEMPLATE_FIELDS)
        headers[1] = alias
        write_rows(csv_path, [headers, template_row(**{TEMPLATE_FIELDS[0]: f"SW-{alias}", TEMPLATE_FIELDS[1]: "192.168.10.1"})])

        with pytest.raises(ValueError, match="缺少必要字段"):
            service.import_csv(csv_path)
        assert repository.list() == []


def test_template_import_exports_and_imports_group_column(tmp_path):
    repository, groups, service = make_group_service(tmp_path)
    csv_path = tmp_path / "devices.csv"
    write_rows(
        csv_path,
        [
            TEMPLATE_FIELDS,
            template_row(**{TEMPLATE_FIELDS[0]: "Vehicle AP", TEMPLATE_FIELDS[9]: "Vehicle"}),
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


def test_full_export_contains_only_new_template_fields(tmp_path):
    repository, groups, service = make_group_service(tmp_path)
    group = groups.create("Vehicle")
    device = repository.create(
        Device(
            name="Core",
            system_name="CORE-SYS",
            primary_address="192.168.1.1",
            backup_address="192.168.2.1",
            group_id=group.id,
            tunnel_enabled=1,
            tunnel1_enabled=1,
            tunnel1_host="10.0.0.10",
            tunnel1_local_port=10022,
            snmp_port=1161,
        )
    )
    export_path = tmp_path / "export.csv"

    service.export_csv(export_path)
    rows = read_csv(export_path)

    assert rows[0] == EXPORT_FIELDS
    for field in ("设备名称", "主用地址", "备用地址", "是否启用SSH隧道", "隧道主机1地址", "分组"):
        assert field in rows[0]
    for removed in ("系统名称", "SNMP端口", "只读团体字", "读写团体字", "隧道主机1本地端口", "隧道主机2本地端口", "ip_address", "sysname", "host", "主机地址"):
        assert removed not in rows[0]
    assert rows[1][rows[0].index("设备名称")] == device.name
    assert rows[1][rows[0].index("主用地址")] == "192.168.1.1"
    assert rows[1][rows[0].index("分组")] == "Vehicle"


def test_csv_import_supports_current_template_fields(tmp_path):
    repository, service = make_service(tmp_path)
    csv_path = tmp_path / "full.csv"
    write_dict_rows(
        csv_path,
        EXPORT_FIELDS,
        [
            {
                "设备名称": "Imported",
                "主用地址": "192.168.1.20",
                "协议": "SSH",
                "端口": "2022",
                "用户名": "ssh",
                "密码": "ssh-pwd",
                "厂商": "H3C",
                "设备类型": "SW",
            }
        ],
    )

    result = service.import_csv(csv_path)
    imported = repository.list()[0]

    assert result.created == 1
    assert imported.system_name is None
    assert imported.primary_address == "192.168.1.20"
    assert imported.ssh_port == 2022
    assert imported.ssh_username == "ssh"
    assert imported.ssh_password == "ssh-pwd"


def test_import_rejects_invalid_device_type_without_modifying_data(tmp_path):
    repository, service = make_service(tmp_path)
    csv_path = tmp_path / "bad.csv"
    write_dict_rows(
        csv_path,
        EXPORT_FIELDS,
        [
            {"设备名称": "BadType", "主用地址": "192.168.1.2", "协议": "SSH", "厂商": "H3C", "设备类型": "BAD"},
        ],
    )

    with pytest.raises(ValueError, match="Invalid device_type"):
        service.import_csv(csv_path)

    assert repository.list() == []


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
