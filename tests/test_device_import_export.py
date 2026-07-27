import csv
import sqlite3
from datetime import datetime

import pytest

from netconsole.core.database import Database
from netconsole.models.device import Device, normalize_device_vendor
from netconsole.repositories.device_group_repository import DeviceGroupRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.device_import_export import (
    CSV_ENCODING_ERROR,
    DEVICE_CSV_COLUMNS,
    EXPORT_FIELDS,
    LEGACY_TEMPLATE_FIELDS,
    TEMPLATE_EXAMPLE_ROWS,
    TEMPLATE_FIELDS,
    DeviceImportExportService,
    make_device_export_filename,
)
from netconsole.services.export.common_exporters import export_device_csv


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


def sanitized_mixed_vendor_rows():
    rows = []
    for index in range(34):
        vendor = "H3C" if index < 18 else "ZTE"
        device_type = "AC" if index < 3 else "SW"
        address = (
            f"198.51.100.{index + 1}"
            if index < 18
            else f"203.0.113.{index - 17}"
        )
        values = {field: "" for field in LEGACY_TEMPLATE_FIELDS}
        values.update(
            {
                "设备名称": f"{vendor}-TEST-{index + 1:02d}",
                "主用地址": address,
                "协议": "SSH",
                "端口": "22",
                "用户名": "test-admin",
                "密码": "TEST_PASSWORD",
                "厂商": vendor,
                "设备类型": device_type,
                "分组": "车站",
                "归属站点": "测试站",
                "是否启用SSH隧道": "否",
                "备注": "脱敏测试数据",
            }
        )
        rows.append([values[field] for field in LEGACY_TEMPLATE_FIELDS])
    return rows


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


def test_template_csv_is_header_only_and_round_trips_as_empty_import(tmp_path):
    repository, service = make_service(tmp_path)
    path = tmp_path / "template.csv"

    service.export_template_csv(path)
    rows = read_csv(path)
    preview = service.preview_csv(path)
    result = service.import_csv(path)
    devices = repository.list()

    assert path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert rows == [TEMPLATE_FIELDS]
    assert preview.total_rows == 0
    assert preview.valid_rows == 0
    assert preview.invalid_rows == 0
    assert preview.columns == tuple(TEMPLATE_FIELDS)
    assert "归属站点" in TEMPLATE_FIELDS
    assert {"SNMP启用", "SNMPv1", "SNMPv2c", "SNMP端口", "SNMP只读团体字", "SNMP超时毫秒", "SNMP重试"}.issubset(TEMPLATE_FIELDS)
    hidden = {
        "系统名称",
        "站点/位置",
        "SNMP版本",
        "只读团体字",
        "读写团体字",
        "隧道主机1本地端口",
        "隧道主机2本地端口",
        "主机地址",
        "IP",
        "host",
        "address",
        "ip_address",
    }
    assert hidden.isdisjoint(TEMPLATE_FIELDS)
    assert len(TEMPLATE_FIELDS) == len(TEMPLATE_EXAMPLE_ROWS[0])
    assert result.created == 0
    assert devices == []


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


def test_previous_device_template_remains_importable_with_v2c_defaults(tmp_path):
    repository, service = make_service(tmp_path)
    csv_path = tmp_path / "legacy-template.csv"
    row = {field: "" for field in LEGACY_TEMPLATE_FIELDS}
    row.update(
        {
            "设备名称": "Previous Export",
            "主用地址": "192.0.2.60",
            "协议": "SSH",
            "端口": "22",
            "厂商": "H3C",
            "设备类型": "SW",
        }
    )
    write_rows(csv_path, [LEGACY_TEMPLATE_FIELDS, [row[field] for field in LEGACY_TEMPLATE_FIELDS]])

    result = service.import_csv(csv_path)
    imported = repository.list()[0]

    assert result.created == 1
    assert imported.snmp_enabled == 1
    assert imported.snmp_v1_enabled == 0
    assert imported.snmp_v2c_enabled == 1
    assert imported.snmp_port == 161
    assert imported.snmp_timeout_ms == 2000
    assert imported.snmp_retries == 1


def test_template_import_rejects_old_headers(tmp_path):
    aliases = ["主机地址", "IP", "host", "address", "ip_address", "站点/位置"]
    for alias in aliases:
        repository, service = make_service(tmp_path / alias)
        csv_path = tmp_path / alias / "devices.csv"
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        headers = list(TEMPLATE_FIELDS)
        headers[1] = alias
        write_rows(
            csv_path,
            [
                headers,
                template_row(
                    **{
                        TEMPLATE_FIELDS[0]: f"SW-{alias}",
                        TEMPLATE_FIELDS[1]: "192.168.10.1",
                    }
                ),
            ],
        )

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
            template_row(
                **{TEMPLATE_FIELDS[0]: "Vehicle AP", TEMPLATE_FIELDS[9]: "Vehicle"}
            ),
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
        write_rows(
            csv_path,
            [TEMPLATE_FIELDS, template_row(**{TEMPLATE_FIELDS[0]: f"SW-{encoding}"})],
            encoding,
        )

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
            snmp_enabled=1,
            snmp_v1_enabled=1,
            snmp_v2c_enabled=0,
            snmp_port=1161,
            snmp_ro_community="readonly",
            snmp_timeout_ms=3500,
            snmp_retries=2,
        )
    )
    export_path = tmp_path / "export.csv"

    service.export_csv(export_path)
    rows = read_csv(export_path)

    assert rows[0] == EXPORT_FIELDS
    for field in (
        "设备名称",
        "主用地址",
        "备用地址",
        "是否启用SSH隧道",
        "隧道主机1地址",
        "分组",
        "SNMP启用",
        "SNMPv1",
        "SNMPv2c",
        "SNMP端口",
        "SNMP只读团体字",
        "SNMP超时毫秒",
        "SNMP重试",
    ):
        assert field in rows[0]
    for removed in (
        "系统名称",
        "只读团体字",
        "读写团体字",
        "隧道主机1本地端口",
        "隧道主机2本地端口",
        "ip_address",
        "sysname",
        "host",
        "主机地址",
    ):
        assert removed not in rows[0]
    assert rows[1][rows[0].index("设备名称")] == device.name
    assert rows[1][rows[0].index("主用地址")] == "192.168.1.1"
    assert rows[1][rows[0].index("分组")] == "Vehicle"
    assert rows[1][rows[0].index("SNMPv1")] == "是"
    assert rows[1][rows[0].index("SNMPv2c")] == "否"
    assert rows[1][rows[0].index("SNMP端口")] == "1161"
    assert rows[1][rows[0].index("SNMP只读团体字")] == "readonly"
    assert rows[1][rows[0].index("SNMP超时毫秒")] == "3500"
    assert rows[1][rows[0].index("SNMP重试")] == "2"


def test_device_snmp_v1_v2c_fields_round_trip_through_csv(tmp_path):
    source_repository, _groups, source = make_group_service(tmp_path / "source")
    source_repository.create(
        Device(
            name="SNMP Device",
            primary_address="192.0.2.50",
            snmp_enabled=1,
            snmp_v1_enabled=1,
            snmp_v2c_enabled=0,
            snmp_port=2161,
            snmp_ro_community="readonly-only",
            snmp_timeout_ms=4500,
            snmp_retries=3,
        )
    )
    csv_path = tmp_path / "device-snmp.csv"
    source.export_csv(csv_path, include_sensitive=True)

    target_repository, target = make_service(tmp_path / "target")
    result = target.import_csv(csv_path)
    imported = target_repository.list()[0]

    assert result.created == 1
    assert imported.snmp_enabled == 1
    assert imported.snmp_v1_enabled == 1
    assert imported.snmp_v2c_enabled == 0
    assert imported.snmp_port == 2161
    assert imported.snmp_ro_community == "readonly-only"
    assert imported.snmp_timeout_ms == 4500
    assert imported.snmp_retries == 3


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


def test_csv_import_accepts_mobile_router_device_type(tmp_path):
    repository, service = make_service(tmp_path)
    csv_path = tmp_path / "mr.csv"
    write_dict_rows(
        csv_path,
        EXPORT_FIELDS,
        [
            {
                "设备名称": "列车01-MR-CT",
                "主用地址": "10.122.1.249",
                "备用地址": "10.122.89.101",
                "协议": "SSH",
                "厂商": "H3C",
                "设备类型": "MR",
            }
        ],
    )

    result = service.import_csv(csv_path)
    imported = repository.list()[0]

    assert result.created == 1
    assert imported.device_type == "MR"
    assert imported.backup_address == "10.122.89.101"


def test_import_rejects_invalid_device_type_without_modifying_data(tmp_path):
    repository, service = make_service(tmp_path)
    csv_path = tmp_path / "bad.csv"
    write_dict_rows(
        csv_path,
        EXPORT_FIELDS,
        [
            {
                "设备名称": "BadType",
                "主用地址": "192.168.1.2",
                "协议": "SSH",
                "厂商": "H3C",
                "设备类型": "BAD",
            },
        ],
    )

    with pytest.raises(ValueError, match="不支持的设备类型：BAD"):
        service.import_csv(csv_path)

    assert repository.list() == []


def test_atomic_import_rolls_back_devices_and_groups_on_insert_failure(tmp_path):
    repository, groups, service = make_group_service(tmp_path)
    csv_path = tmp_path / "atomic.csv"
    write_rows(
        csv_path,
        [
            TEMPLATE_FIELDS,
            template_row(
                **{
                    TEMPLATE_FIELDS[0]: "First",
                    TEMPLATE_FIELDS[1]: "192.168.10.1",
                    TEMPLATE_FIELDS[9]: "Atomic Group",
                }
            ),
            template_row(
                **{
                    TEMPLATE_FIELDS[0]: "Fail",
                    TEMPLATE_FIELDS[1]: "192.168.10.2",
                    TEMPLATE_FIELDS[9]: "Atomic Group",
                }
            ),
        ],
    )
    with repository.database.connect() as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_second_atomic_device
            BEFORE INSERT ON devices
            WHEN NEW.name = 'Fail'
            BEGIN
                SELECT RAISE(ABORT, 'forced atomic failure');
            END
            """
        )
        connection.commit()

    with pytest.raises(sqlite3.IntegrityError, match="forced atomic failure"):
        service.import_csv_atomic(csv_path)

    assert repository.list() == []
    assert groups.find_by_name("Atomic Group") is None


def test_atomic_import_applies_explicit_duplicate_address_strategy(tmp_path):
    repository, _groups, service = make_group_service(tmp_path)
    repository.create(Device(name="Existing", primary_address="192.168.30.1"))
    csv_path = tmp_path / "duplicates.csv"
    write_rows(
        csv_path,
        [
            TEMPLATE_FIELDS,
            template_row(
                **{
                    TEMPLATE_FIELDS[0]: "Duplicate",
                    TEMPLATE_FIELDS[1]: "192.168.30.1",
                }
            ),
        ],
    )

    with pytest.raises(ValueError, match="第 2 行主用地址已存在"):
        service.import_csv_atomic(csv_path, duplicate_strategy="reject")
    assert len(repository.list()) == 1

    skipped = service.import_csv_atomic(csv_path, duplicate_strategy="skip")
    assert skipped.created == 0
    assert skipped.skipped == 1
    assert len(repository.list()) == 1

    created = service.import_csv_atomic(csv_path, duplicate_strategy="create_new")
    assert created.created == 1
    assert created.skipped == 0
    assert len(repository.list()) == 2


def test_web_device_csv_export_honors_selection_and_omits_credentials(tmp_path):
    repository, _groups, _service = make_group_service(tmp_path)
    selected = repository.create(
        Device(
            name="Selected",
            primary_address="192.168.20.1",
            password="generic-secret",
            ssh_password="ssh-secret",
            tunnel1_host="192.0.2.10",
            tunnel1_password="jump-secret",
        )
    )
    repository.create(
        Device(
            name="Not Selected",
            primary_address="192.168.20.2",
            password="other-secret",
        )
    )
    export_path = tmp_path / "web-devices.csv"

    row_count = export_device_csv(
        export_path,
        {
            "db_path": str(repository.database.path),
            "site_name": "demo",
            "selected_device_uuids": [str(selected.device_uuid)],
            "omit_credentials": True,
        },
    )
    rows = read_csv(export_path)
    text = export_path.read_text(encoding="utf-8-sig")

    assert row_count == 1
    assert len(rows) == 2
    assert rows[1][rows[0].index("设备名称")] == "Selected"
    assert rows[0] == EXPORT_FIELDS
    assert all(
        rows[1][rows[0].index(field)] == ""
        for field in ("密码", "隧道主机1密码", "隧道主机2密码", "SNMP只读团体字")
    )
    assert "secret" not in text
    assert "Not Selected" not in text
    assert _service.preview_csv(export_path).total_rows == 1


def test_make_device_export_filename_formats_site_name_and_local_time():
    now = datetime(2026, 6, 12, 18, 15)

    assert make_device_export_filename("demo", now) == "demo-设备表-20260612_181500.csv"
    assert (
        make_device_export_filename("宁波6号线", now)
        == "宁波6号线-设备表-20260612_181500.csv"
    )
    assert (
        make_device_export_filename('bad<>:"/\\|?*name', now)
        == "bad_________name-设备表-20260612_181500.csv"
    )


@pytest.mark.parametrize(
    ("source", "expected"),
    (
        ("H3C", "H3C"),
        ("h3c", "H3C"),
        ("新华三", "H3C"),
        ("ZTE", "ZTE"),
        ("zte", "ZTE"),
        ("中兴", "ZTE"),
        ("中兴通讯", "ZTE"),
    ),
)
def test_device_vendor_normalization(source, expected):
    assert normalize_device_vendor(source) == expected


def test_device_vendor_normalization_rejects_unknown():
    with pytest.raises(ValueError, match="不支持的设备厂商：UNKNOWN"):
        normalize_device_vendor("UNKNOWN")


@pytest.mark.parametrize(
    ("encoding", "expected_encoding"),
    (("gb18030", "gb18030"), ("utf-8-sig", "utf-8-sig")),
)
def test_mixed_vendor_34_row_preview_and_atomic_import(
    tmp_path, encoding, expected_encoding
):
    repository, groups, service = make_group_service(tmp_path)
    source = tmp_path / f"mixed-{encoding}.csv"
    write_rows(
        source,
        [LEGACY_TEMPLATE_FIELDS, *sanitized_mixed_vendor_rows()],
        encoding=encoding,
    )

    preview = service.preview_csv(source)
    result = service.import_csv_atomic(source)

    assert preview.total_rows == 34
    assert preview.valid_rows == 34
    assert preview.invalid_rows == 0
    assert preview.vendor_summary == {"H3C": 18, "ZTE": 16}
    assert preview.device_type_summary == {"AC": 3, "SW": 31}
    assert preview.detected_encoding == expected_encoding
    assert result.created == 34
    assert len(repository.list(vendor="ZTE")) == 16
    assert groups.find_by_name("车站") is not None

    exported = tmp_path / f"mixed-{encoding}-exported.csv"
    service.export_csv(exported, include_sensitive=False)
    exported_rows = read_csv(exported)
    roundtrip = service.preview_csv(exported)

    assert exported_rows[0] == DEVICE_CSV_COLUMNS
    assert len(exported_rows[1:]) == 34
    assert [row[TEMPLATE_FIELDS.index("厂商")] for row in exported_rows[1:]].count(
        "H3C"
    ) == 18
    assert [row[TEMPLATE_FIELDS.index("厂商")] for row in exported_rows[1:]].count(
        "ZTE"
    ) == 16
    assert all(
        not row[TEMPLATE_FIELDS.index(field)]
        for row in exported_rows[1:]
        for field in ("密码", "隧道主机1密码", "隧道主机2密码", "SNMP只读团体字")
    )
    assert roundtrip.total_rows == 34
    assert roundtrip.valid_rows == 34
    assert roundtrip.vendor_summary == {"H3C": 18, "ZTE": 16}


def test_zte_ac_is_a_structured_row_error(tmp_path):
    _repository, _groups, service = make_group_service(tmp_path)
    source = tmp_path / "zte-ac.csv"
    rows = sanitized_mixed_vendor_rows()[:1]
    rows[0][LEGACY_TEMPLATE_FIELDS.index("厂商")] = "中兴"
    rows[0][LEGACY_TEMPLATE_FIELDS.index("设备类型")] = "AC"
    write_rows(source, [LEGACY_TEMPLATE_FIELDS, *rows], encoding="gb18030")

    preview = service.preview_csv(source)

    assert preview.total_rows == 1
    assert preview.valid_rows == 0
    assert preview.invalid_rows == 1
    assert preview.vendor_summary == {"ZTE": 1}
    assert preview.errors[0].line == 2
    assert preview.errors[0].field == "设备类型"
    assert preview.errors[0].message == "当前版本尚未适配 ZTE 无线控制器"
