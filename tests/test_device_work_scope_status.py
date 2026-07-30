import csv
from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest

from netconsole.core import app_logger
from netconsole.core.database import Database, DatabaseSchemaMismatchError
from netconsole.models.device import (
    Device,
    is_device_eligible_for_automatic_collection,
    legacy_operation_status_to_work_scope_status,
    normalize_project_phase,
    normalize_work_scope_status,
)
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.device_import_export import (
    DEVICE_CSV_COLUMNS,
    IDENTITY_TEMPLATE_FIELDS,
    OPERATION_STATUS_TEMPLATE_FIELDS,
    DeviceImportExportService,
)


def _repository(tmp_path) -> DeviceRepository:
    database = Database(tmp_path / "devices.sqlite")
    database.initialize()
    return DeviceRepository(database)


def _replace_with_legacy_operation_schema(
    database: Database,
    statuses: dict[str, str],
    *,
    constrained: bool = True,
) -> None:
    definition = (
        "TEXT NOT NULL DEFAULT 'in_service' "
        "CHECK(operation_status IN "
        "('in_service', 'not_integrated', 'commissioning', 'suspended', 'retired'))"
        if constrained
        else "TEXT NOT NULL DEFAULT 'in_service'"
    )
    with database.connect() as connection:
        connection.execute("DROP INDEX IF EXISTS idx_devices_work_scope_status")
        for column in (
            "work_scope_updated_by",
            "work_scope_updated_at",
            "work_scope_reason",
            "work_scope_status",
        ):
            connection.execute(f"ALTER TABLE devices DROP COLUMN {column}")
        connection.execute(
            f"ALTER TABLE devices ADD COLUMN operation_status {definition}"
        )
        connection.execute(
            "ALTER TABLE devices ADD COLUMN operation_status_reason TEXT"
        )
        connection.execute(
            "ALTER TABLE devices ADD COLUMN operation_status_updated_at TEXT"
        )
        connection.execute(
            "ALTER TABLE devices ADD COLUMN operation_status_updated_by TEXT"
        )
        connection.execute(
            "CREATE INDEX idx_devices_operation_status ON devices(operation_status)"
        )
        for name, status in statuses.items():
            connection.execute(
                """
                UPDATE devices
                SET operation_status = ?,
                    operation_status_reason = ?,
                    operation_status_updated_at = '2026-07-29T10:00:00',
                    operation_status_updated_by = 'legacy_user'
                WHERE name = ?
                """,
                (status, f"旧状态：{status}", name),
            )
        connection.execute(
            "UPDATE schema_metadata SET value = ? WHERE key = 'schema_version'",
            ("2026.07.29.zte_optical_ap_vlan_device_address_and_operation_status",),
        )
        connection.commit()


def _drop_work_scope_schema(
    database: Database,
    *,
    columns: tuple[str, ...] = (
        "work_scope_updated_by",
        "work_scope_updated_at",
        "work_scope_reason",
        "work_scope_status",
    ),
) -> None:
    with database.connect() as connection:
        connection.execute("DROP INDEX IF EXISTS idx_devices_work_scope_status")
        connection.execute("DROP INDEX IF EXISTS idx_devices_project_phase")
        for column in columns:
            connection.execute(f"ALTER TABLE devices DROP COLUMN {column}")
        connection.execute(
            "UPDATE schema_metadata SET value = ? WHERE key = 'schema_version'",
            ("2026.07.30.trackside_ap_station_plan",),
        )
        connection.commit()


def _migration_backups(database: Database) -> list:
    return list(
        (database.path.parent / "backups" / "database-migrations").glob(
            "devices-site-*-before-work-scope-status-*.sqlite"
        )
    )


def test_work_scope_enums_accept_stable_and_chinese_values():
    assert normalize_project_phase("phase_2") == "phase_2"
    assert normalize_project_phase("二期") == "phase_2"
    assert normalize_work_scope_status("included") == "included"
    assert normalize_work_scope_status("参与当前调试") == "included"
    assert normalize_work_scope_status("暂不参与") == "excluded"
    with pytest.raises(ValueError, match="不支持的当前工作状态"):
        normalize_work_scope_status("retired")


@pytest.mark.parametrize(
    ("legacy", "expected"),
    [
        ("in_service", "included"),
        ("not_integrated", "excluded"),
        ("commissioning", "excluded"),
        ("suspended", "excluded"),
        ("retired", "excluded"),
    ],
)
def test_legacy_operation_status_mapping_is_explicit(legacy, expected):
    assert legacy_operation_status_to_work_scope_status(legacy) == expected


def test_additive_migration_maps_legacy_statuses_and_preserves_data(
    tmp_path, monkeypatch
):
    database = Database(tmp_path / "legacy.sqlite")
    database.initialize()
    repository = DeviceRepository(database)
    statuses = {
        "在用": "in_service",
        "未并网": "not_integrated",
        "调试中": "commissioning",
        "暂停": "suspended",
        "退役": "retired",
    }
    created = {
        name: repository.create(
            Device(
                name=name,
                primary_address=f"192.0.2.{index}",
                ssh_username="admin",
                ssh_password=f"secret-{index}",
            )
        )
        for index, name in enumerate(statuses, start=1)
    }
    _replace_with_legacy_operation_schema(database, statuses)
    log_rows: list[tuple[str, str]] = []
    monkeypatch.setattr(
        app_logger,
        "log_info",
        lambda event, detail="", **_kwargs: log_rows.append((event, detail)),
    )

    database.initialize()

    migrated = {device.name: device for device in DeviceRepository(database).list()}
    assert migrated["在用"].work_scope_status == "included"
    for name in ("未并网", "调试中", "暂停", "退役"):
        assert migrated[name].work_scope_status == "excluded"
    for index, (name, original) in enumerate(created.items(), start=1):
        assert migrated[name].id == original.id
        assert migrated[name].device_uuid == original.device_uuid
        assert migrated[name].ssh_password == f"secret-{index}"
        assert migrated[name].work_scope_reason == f"旧状态：{statuses[name]}"
        assert migrated[name].work_scope_updated_at == "2026-07-29T10:00:00"
    with database.connect() as connection:
        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(devices)")
        }
    assert "operation_status" in columns
    assert "work_scope_status" in columns
    assert len(_migration_backups(database)) == 1
    assert any(
        event == "DATABASE_MIGRATION_COMPLETED"
        and "classification_migration=True" in detail
        and '"in_service": 1' in detail
        and '"retired": 1' in detail
        for event, detail in log_rows
    )

    database.initialize()
    assert len(_migration_backups(database)) == 1


def test_unknown_legacy_status_blocks_migration_and_preserves_original(tmp_path):
    database = Database(tmp_path / "unknown.sqlite")
    database.initialize()
    created = DeviceRepository(database).create(
        Device(
            name="未知旧状态",
            primary_address="198.51.100.41",
            ssh_password="preserved",
        )
    )
    _replace_with_legacy_operation_schema(
        database, {"未知旧状态": "mystery"}, constrained=False
    )

    with pytest.raises(DatabaseSchemaMismatchError, match="无法安全映射"):
        database.initialize()

    with database.connect() as connection:
        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(devices)")
        }
        row = connection.execute(
            "SELECT operation_status, ssh_password FROM devices WHERE id = ?",
            (created.id,),
        ).fetchone()
    assert "work_scope_status" not in columns
    assert tuple(row) == ("mystery", "preserved")
    assert len(_migration_backups(database)) == 1


def test_repository_filters_and_atomic_classification_update(tmp_path):
    repository = _repository(tmp_path)
    phase_one = repository.create(
        Device(
            name="一期",
            primary_address="10.92.250.1",
            project_phase="phase_1",
            ssh_password="credential",
        )
    )
    phase_two = repository.create(
        Device(
            name="二期",
            primary_address="10.92.250.15",
            project_phase="phase_2",
        )
    )

    updated = repository.update_classification_many(
        [str(phase_one.device_uuid)],
        work_scope_status="excluded",
        reason="既有一期设备，不纳入二三期调试范围",
    )
    assert updated == 1
    assert [
        item.name for item in repository.list(work_scope_status="included")
    ] == ["二期"]
    assert [
        item.name
        for item in repository.list(
            project_phase="phase_1", work_scope_status="excluded"
        )
    ] == ["一期"]
    reread = repository.get(int(phase_one.id or 0))
    assert reread.id == phase_one.id
    assert reread.device_uuid == phase_one.device_uuid
    assert reread.ssh_password == "credential"
    assert reread.work_scope_reason == "既有一期设备，不纳入二三期调试范围"

    with pytest.raises(KeyError):
        repository.update_classification_many(
            [str(phase_two.device_uuid), Device.new_uuid()],
            project_phase="other",
        )
    assert repository.get(int(phase_two.id or 0)).project_phase == "phase_2"


def test_partial_migration_repairs_current_version_without_data_loss(tmp_path):
    database = Database(tmp_path / "partial.sqlite")
    database.initialize()
    created = DeviceRepository(database).create(
        Device(
            name="部分迁移设备",
            primary_address="198.51.100.51",
            ssh_password="partial-secret",
        )
    )
    with database.connect() as connection:
        connection.execute("ALTER TABLE devices DROP COLUMN work_scope_updated_by")
        connection.commit()

    database.initialize()

    with database.connect() as connection:
        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(devices)")
        }
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    migrated = DeviceRepository(database).get(int(created.id or 0))
    assert "work_scope_updated_by" in columns
    assert integrity == "ok"
    assert migrated.device_uuid == created.device_uuid
    assert migrated.ssh_password == "partial-secret"
    assert len(_migration_backups(database)) == 1


def test_migration_repairs_missing_indexes_once(tmp_path):
    database = Database(tmp_path / "missing-indexes.sqlite")
    database.initialize()
    with database.connect() as connection:
        connection.execute("DROP INDEX idx_devices_work_scope_status")
        connection.execute("DROP INDEX idx_devices_project_phase")
        connection.commit()

    database.initialize()
    database.initialize()

    with database.connect() as connection:
        indexes = {
            row["name"] for row in connection.execute("PRAGMA index_list(devices)")
        }
    assert {
        "idx_devices_work_scope_status",
        "idx_devices_project_phase",
    }.issubset(indexes)
    assert len(_migration_backups(database)) == 1


def test_migration_failure_rolls_back_and_reuses_verified_backup(
    tmp_path, monkeypatch
):
    database = Database(tmp_path / "rollback.sqlite")
    database.initialize()
    created = DeviceRepository(database).create(
        Device(
            name="回滚设备",
            primary_address="203.0.113.61",
            ssh_password="rollback-secret",
        )
    )
    _drop_work_scope_schema(database)
    log_rows: list[tuple[str, str]] = []
    monkeypatch.setattr(
        app_logger,
        "log_error",
        lambda event, detail="", **_kwargs: log_rows.append((event, detail)),
    )

    def fail_validation(
        _database: Database, _connection: sqlite3.Connection
    ) -> None:
        raise sqlite3.OperationalError("forced classification validation failure")

    monkeypatch.setattr(
        Database, "_validate_device_classification_migration", fail_validation
    )

    for _attempt in range(2):
        with pytest.raises(
            sqlite3.OperationalError,
            match="forced classification validation failure",
        ):
            database.initialize()

    with database.connect() as connection:
        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(devices)")
        }
        row = connection.execute(
            "SELECT device_uuid, primary_address, ssh_password FROM devices WHERE id = ?",
            (created.id,),
        ).fetchone()
    backups = _migration_backups(database)
    with sqlite3.connect(backups[0]) as backup:
        backup_integrity = backup.execute("PRAGMA integrity_check").fetchone()[0]

    assert "work_scope_status" not in columns
    assert tuple(row) == (
        created.device_uuid,
        "203.0.113.61",
        "rollback-secret",
    )
    assert len(backups) == 1
    assert backup_integrity == "ok"
    assert any(
        event == "DATABASE_INITIALIZE_FAILED"
        and "stage=classification_validation" in detail
        and "traceback=" in detail
        for event, detail in log_rows
    )


def test_concurrent_initialization_creates_one_backup(tmp_path):
    database = Database(tmp_path / "concurrent.sqlite")
    database.initialize()
    DeviceRepository(database).create(
        Device(name="并发迁移设备", primary_address="203.0.113.71")
    )
    _drop_work_scope_schema(database)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda _index: Database(database.path).initialize(),
                range(2),
            )
        )

    assert results == [None, None]
    assert len(_migration_backups(database)) == 1
    assert (
        len(DeviceRepository(database).list(work_scope_status="included")) == 1
    )


def test_corrupt_database_is_not_replaced_or_overwritten(tmp_path):
    path = tmp_path / "corrupt.sqlite"
    original = b"not-a-sqlite-database"
    path.write_bytes(original)

    with pytest.raises(sqlite3.DatabaseError):
        Database(path).initialize()

    assert path.read_bytes() == original
    assert not (path.parent / "backups" / "database-migrations").exists()


def test_automatic_eligibility_uses_work_scope_only():
    included = Device(name="二期", primary_address="192.0.2.1")
    excluded = Device(
        name="一期",
        primary_address="192.0.2.2",
        work_scope_status="excluded",
    )
    assert is_device_eligible_for_automatic_collection(included)
    assert not is_device_eligible_for_automatic_collection(excluded)


def test_csv_work_scope_round_trip_and_legacy_template_compatibility(tmp_path):
    repository = _repository(tmp_path)
    service = DeviceImportExportService(repository)
    repository.create(
        Device(
            name="一期无线控制器",
            primary_address="192.0.2.10",
            device_type="AC",
            project_phase="phase_1",
            work_scope_status="excluded",
            work_scope_reason="既有一期设备，不纳入二三期调试范围",
        )
    )
    export_path = tmp_path / "devices.csv"
    service.export_csv(export_path)
    with export_path.open("r", newline="", encoding="utf-8-sig") as file:
        rows = list(csv.DictReader(file))
    assert rows[0]["建设阶段"] == "phase_1"
    assert rows[0]["当前工作状态"] == "excluded"
    assert rows[0]["当前工作状态说明"] == "既有一期设备，不纳入二三期调试范围"

    old_status_path = tmp_path / "old-operation-template.csv"
    old_values = {field: "" for field in OPERATION_STATUS_TEMPLATE_FIELDS}
    old_values.update(
        {
            "设备名称": "旧状态模板设备",
            "主用地址": "192.0.2.20",
            "协议": "SSH",
            "端口": "22",
            "用户名": "admin",
            "密码": "secret",
            "厂商": "H3C",
            "设备类型": "SW",
            "投运状态": "suspended",
            "投运状态说明": "旧模板原因",
        }
    )
    with old_status_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=OPERATION_STATUS_TEMPLATE_FIELDS)
        writer.writeheader()
        writer.writerow(old_values)
    result = service.import_csv_atomic(old_status_path)
    imported = repository.find_by_primary_address("192.0.2.20")
    assert result.created == 1
    assert imported is not None
    assert imported.work_scope_status == "excluded"
    assert imported.work_scope_reason == "旧模板原因"

    identity_path = tmp_path / "identity-template.csv"
    identity_values = {field: "" for field in IDENTITY_TEMPLATE_FIELDS}
    identity_values.update(
        {
            "设备名称": "缺少工作状态设备",
            "主用地址": "192.0.2.30",
            "协议": "SSH",
            "端口": "22",
            "用户名": "admin",
            "密码": "secret",
            "厂商": "H3C",
            "设备类型": "SW",
        }
    )
    with identity_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=IDENTITY_TEMPLATE_FIELDS)
        writer.writeheader()
        writer.writerow(identity_values)
    service.import_csv_atomic(identity_path)
    defaulted = repository.find_by_primary_address("192.0.2.30")
    assert defaulted is not None
    assert defaulted.work_scope_status == "included"
    assert DEVICE_CSV_COLUMNS[-3:] == [
        "建设阶段",
        "当前工作状态",
        "当前工作状态说明",
    ]


def test_database_rejects_unknown_work_scope_value(tmp_path):
    repository = _repository(tmp_path)
    device = repository.create(Device(name="SW", primary_address="198.51.100.1"))
    with repository.database.connect() as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE devices SET work_scope_status = ? WHERE id = ?",
                ("retired", device.id),
            )
