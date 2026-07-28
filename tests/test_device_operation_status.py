import csv
import sqlite3

import pytest

from netconsole.core.database import Database
from netconsole.models.device import (
    Device,
    is_device_available_for_manual_debug,
    is_device_eligible_for_automatic_collection,
    normalize_operation_status,
    normalize_project_phase,
)
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.device_import_export import (
    DEVICE_CSV_COLUMNS,
    IDENTITY_TEMPLATE_FIELDS,
    DeviceImportExportService,
)


def _repository(tmp_path) -> DeviceRepository:
    database = Database(tmp_path / "devices.sqlite")
    database.initialize()
    return DeviceRepository(database)


def test_lifecycle_enums_accept_stable_and_chinese_values():
    assert normalize_project_phase("phase_2") == "phase_2"
    assert normalize_project_phase("二期") == "phase_2"
    assert normalize_operation_status("not_integrated") == "not_integrated"
    assert normalize_operation_status("未并网") == "not_integrated"
    with pytest.raises(ValueError, match="不支持的投运状态"):
        normalize_operation_status("hidden")


def test_additive_migration_preserves_device_and_defaults_to_in_service(tmp_path):
    database = Database(tmp_path / "legacy.sqlite")
    database.initialize()
    repository = DeviceRepository(database)
    created = repository.create(
        Device(
            name="一期现有设备",
            primary_address="10.92.250.1",
            ssh_username="admin",
            ssh_password="secret",
        )
    )
    with database.connect() as connection:
        lifecycle = {
            "project_phase",
            "operation_status",
            "operation_status_reason",
            "operation_status_updated_at",
            "operation_status_updated_by",
        }
        columns = [
            row["name"]
            for row in connection.execute("PRAGMA table_info(devices)")
            if row["name"] not in lifecycle
        ]
        selected = ", ".join(columns)
        connection.execute(f"CREATE TABLE devices_legacy AS SELECT {selected} FROM devices")
        connection.execute("DROP TABLE devices")
        connection.execute("ALTER TABLE devices_legacy RENAME TO devices")
        connection.execute(
            "CREATE UNIQUE INDEX uq_devices_normalized_primary_address "
            "ON devices(normalized_primary_address) "
            "WHERE normalized_primary_address IS NOT NULL "
            "AND normalized_primary_address <> ''"
        )
        connection.execute(
            "UPDATE schema_metadata SET value = ? WHERE key = 'schema_version'",
            ("2026.07.29.device_primary_address_identity",),
        )
        connection.commit()

    database.initialize()
    migrated = DeviceRepository(database).get(int(created.id or 0))
    backups = list(
        (database.path.parent / "backups" / "database-migrations").glob(
            "devices-before-operation-status-*.sqlite"
        )
    )
    assert migrated.id == created.id
    assert migrated.device_uuid == created.device_uuid
    assert migrated.primary_address == "10.92.250.1"
    assert migrated.ssh_password == "secret"
    assert migrated.project_phase == "unspecified"
    assert migrated.operation_status == "in_service"
    assert len(backups) == 1

    database.initialize()
    assert DeviceRepository(database).get(int(created.id or 0)).operation_status == "in_service"
    assert (
        len(
            list(
                (database.path.parent / "backups" / "database-migrations").glob(
                    "devices-before-operation-status-*.sqlite"
                )
            )
        )
        == 1
    )


def test_repository_filters_and_atomic_lifecycle_update(tmp_path):
    repository = _repository(tmp_path)
    first = repository.create(
        Device(name="一期", primary_address="10.92.250.1", project_phase="phase_1")
    )
    second = repository.create(
        Device(name="二期", primary_address="10.92.250.15", project_phase="phase_2")
    )

    updated = repository.update_lifecycle_many(
        [str(second.device_uuid)],
        operation_status="not_integrated",
        reason="二期暂未并网",
    )
    assert updated == 1
    assert [item.name for item in repository.list(operation_status="in_service")] == [
        "一期"
    ]
    assert [item.name for item in repository.list(project_phase="phase_2")] == ["二期"]
    assert repository.get(int(second.id or 0)).operation_status_reason == "二期暂未并网"

    with pytest.raises(KeyError):
        repository.update_lifecycle_many(
            [str(first.device_uuid), Device.new_uuid()],
            project_phase="other",
        )
    assert repository.get(int(first.id or 0)).project_phase == "phase_1"


def test_manual_and_automatic_eligibility_are_independent():
    in_service = Device(name="一期", primary_address="192.0.2.1")
    not_integrated = Device(
        name="二期",
        primary_address="192.0.2.2",
        operation_status="not_integrated",
    )
    retired = Device(
        name="退役",
        primary_address="192.0.2.3",
        operation_status="retired",
    )
    assert is_device_eligible_for_automatic_collection(in_service)
    assert not is_device_eligible_for_automatic_collection(not_integrated)
    assert is_device_available_for_manual_debug(not_integrated)
    assert not is_device_available_for_manual_debug(retired)


def test_csv_lifecycle_round_trip_and_previous_template_compatibility(tmp_path):
    repository = _repository(tmp_path)
    service = DeviceImportExportService(repository)
    repository.create(
        Device(
            name="二期无线控制器",
            primary_address="192.0.2.10",
            device_type="AC",
            project_phase="phase_2",
            operation_status="not_integrated",
            operation_status_reason="二期调试",
        )
    )
    export_path = tmp_path / "devices.csv"
    service.export_csv(export_path)
    with export_path.open("r", newline="", encoding="utf-8-sig") as file:
        rows = list(csv.DictReader(file))
    assert rows[0]["建设阶段"] == "phase_2"
    assert rows[0]["投运状态"] == "not_integrated"
    assert rows[0]["投运状态说明"] == "二期调试"

    old_path = tmp_path / "old-current-template.csv"
    values = {field: "" for field in IDENTITY_TEMPLATE_FIELDS}
    values.update(
        {
            "设备名称": "旧模板设备",
            "主用地址": "192.0.2.20",
            "协议": "SSH",
            "端口": "22",
            "用户名": "admin",
            "密码": "secret",
            "厂商": "H3C",
            "设备类型": "SW",
        }
    )
    with old_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=IDENTITY_TEMPLATE_FIELDS)
        writer.writeheader()
        writer.writerow(values)
    result = service.import_csv_atomic(old_path)
    imported = repository.find_by_primary_address("192.0.2.20")
    assert result.created == 1
    assert imported is not None
    assert imported.project_phase == "unspecified"
    assert imported.operation_status == "in_service"
    assert DEVICE_CSV_COLUMNS[-3:] == ["建设阶段", "投运状态", "投运状态说明"]


def test_database_rejects_unknown_lifecycle_value(tmp_path):
    repository = _repository(tmp_path)
    device = repository.create(Device(name="SW", primary_address="198.51.100.1"))
    with repository.database.connect() as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE devices SET operation_status = ? WHERE id = ?",
                ("hidden", device.id),
            )
