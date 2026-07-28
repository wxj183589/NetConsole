from __future__ import annotations

import csv
from pathlib import Path

import pytest

from netconsole.core.database import (
    CURRENT_SCHEMA_VERSION,
    Database,
    DeviceAddressMigrationError,
)
from netconsole.models.device import Device
from netconsole.models.device_address import (
    DevicePrimaryAddressConflictError,
    InvalidDeviceAddressError,
    normalize_ip_address,
)
from netconsole.repositories.device_group_repository import DeviceGroupRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.device_import_export import (
    TEMPLATE_FIELDS,
    DeviceImportExportService,
)


def _service(path: Path, site_name: str = "site-a"):
    database = Database(path)
    database.initialize()
    repository = DeviceRepository(database)
    groups = DeviceGroupRepository(database, site_name)
    groups.ensure_default_groups()
    return database, repository, DeviceImportExportService(repository, groups)


def _write_csv(path: Path, *rows: dict[str, object]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=TEMPLATE_FIELDS)
        writer.writeheader()
        for source in rows:
            row = {field: "" for field in TEMPLATE_FIELDS}
            row.update(
                {
                    "协议": "SSH",
                    "端口": "22",
                    "厂商": "H3C",
                    "设备类型": "SW",
                    "SNMP启用": "是",
                    "SNMPv1": "否",
                    "SNMPv2c": "是",
                    "SNMP端口": "161",
                    "SNMP超时毫秒": "2000",
                    "SNMP重试": "1",
                }
            )
            row.update(source)
            writer.writerow(row)


def test_ip_normalizer_uses_standard_ipv4_and_ipv6_forms() -> None:
    assert normalize_ip_address(" 192.0.2.1 ") == "192.0.2.1"
    assert normalize_ip_address("2001:0db8:0:0:0:0:0:1") == "2001:db8::1"
    assert normalize_ip_address("   ") is None
    with pytest.raises(InvalidDeviceAddressError):
        normalize_ip_address("192.0.2.999")


def test_repository_enforces_primary_address_per_site_database(tmp_path: Path) -> None:
    _db_a, repository_a, _ = _service(tmp_path / "site-a" / "db" / "devices.db")
    _db_b, repository_b, _ = _service(tmp_path / "site-b" / "db" / "devices.db")

    first = repository_a.create(
        Device(name="A", primary_address=" 2001:0db8:0:0:0:0:0:1 ")
    )
    second_site = repository_b.create(
        Device(name="B", primary_address="2001:db8::1")
    )

    assert first.primary_address == "2001:db8::1"
    assert second_site.primary_address == "2001:db8::1"
    with pytest.raises(DevicePrimaryAddressConflictError) as exc_info:
        repository_a.create(Device(name="A2", primary_address="2001:db8::1"))
    assert exc_info.value.code == "DEVICE_PRIMARY_IP_CONFLICT"
    assert exc_info.value.details["conflict_device_id"] == first.id


def test_database_migration_backfills_address_and_is_idempotent(
    tmp_path: Path,
) -> None:
    database, repository, _ = _service(tmp_path / "site-a" / "db" / "devices.db")
    device = repository.create(Device(name="A", primary_address="2001:db8::1"))
    with database.connect() as conn:
        conn.execute("DROP INDEX uq_devices_normalized_primary_address")
        conn.execute(
            """
            UPDATE devices
            SET primary_address = ' 2001:0db8:0:0:0:0:0:1 ',
                normalized_primary_address = NULL
            WHERE id = ?
            """,
            (device.id,),
        )
        conn.execute(
            "UPDATE schema_metadata SET value = 'legacy' WHERE key = 'schema_version'"
        )
        conn.commit()

    database.initialize()
    database.initialize()

    with database.connect() as conn:
        row = conn.execute(
            """
            SELECT id, primary_address, normalized_primary_address
            FROM devices
            WHERE id = ?
            """,
            (device.id,),
        ).fetchone()
        assert dict(row) == {
            "id": device.id,
            "primary_address": "2001:db8::1",
            "normalized_primary_address": "2001:db8::1",
        }
        assert (
            conn.execute(
                "SELECT value FROM schema_metadata WHERE key = 'schema_version'"
            ).fetchone()[0]
            == CURRENT_SCHEMA_VERSION
        )
        assert (
            conn.execute(
                """
                SELECT 1
                FROM sqlite_master
                WHERE type = 'index'
                  AND name = 'uq_devices_normalized_primary_address'
                """
            ).fetchone()
            is not None
        )
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    backups = list(
        (tmp_path / "site-a" / "files" / "backups" / "database-migrations").glob(
            "*.sqlite"
        )
    )
    assert len(backups) == 1


def test_database_migration_reports_duplicates_and_rolls_back(
    tmp_path: Path,
) -> None:
    database, repository, _ = _service(tmp_path / "site-a" / "db" / "devices.db")
    first = repository.create(Device(name="A", primary_address="192.0.2.1"))
    second = repository.create(Device(name="B", primary_address="192.0.2.2"))
    with database.connect() as conn:
        conn.execute("DROP INDEX uq_devices_normalized_primary_address")
        conn.execute(
            """
            UPDATE devices
            SET primary_address = ' 192.0.2.1 ',
                normalized_primary_address = '192.0.2.2'
            WHERE id = ?
            """,
            (second.id,),
        )
        conn.execute(
            "UPDATE schema_metadata SET value = 'legacy' WHERE key = 'schema_version'"
        )
        conn.commit()

    with pytest.raises(DeviceAddressMigrationError) as exc_info:
        database.initialize()

    message = str(exc_info.value)
    assert "局点=site-a" in message
    assert f"设备ID={first.id}" in message
    assert f"设备ID={second.id}" in message
    with database.connect() as conn:
        row = conn.execute(
            """
            SELECT primary_address, normalized_primary_address
            FROM devices
            WHERE id = ?
            """,
            (second.id,),
        ).fetchone()
        assert tuple(row) == (" 192.0.2.1 ", "192.0.2.2")
        assert (
            conn.execute(
                """
                SELECT 1
                FROM sqlite_master
                WHERE type = 'index'
                  AND name = 'uq_devices_normalized_primary_address'
                """
            ).fetchone()
            is None
        )
        assert (
            conn.execute(
                "SELECT value FROM schema_metadata WHERE key = 'schema_version'"
            ).fetchone()[0]
            == "legacy"
        )
    backup = next(
        (tmp_path / "site-a" / "files" / "backups" / "database-migrations").glob(
            "*.sqlite"
        )
    )
    with Database(backup).connect() as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_site_primary_ip_bulk_update_preserves_identity_and_blank_credentials(
    tmp_path: Path,
) -> None:
    _database, repository, service = _service(
        tmp_path / "site-a" / "db" / "devices.db"
    )
    existing = repository.create(
        Device(
            name="Old",
            primary_address="192.0.2.10",
            ssh_username="admin",
            ssh_password="secret",
        )
    )
    source = tmp_path / "update.csv"
    _write_csv(
        source,
        {
            "设备名称": "New",
            "主用地址": "192.0.2.20",
            "原主用地址": "192.0.2.10",
            "密码": "",
        },
    )

    preview = service.preview_csv(
        source,
        match_strategy="SITE_PRIMARY_IP",
        write_mode="UPDATE_ONLY",
    )
    assert preview.update_count == 1
    assert preview.has_hard_errors is False
    assert preview.row_results[0].device_id == existing.id

    result = service.import_csv_atomic(
        source,
        match_strategy="SITE_PRIMARY_IP",
        write_mode="UPDATE_ONLY",
    )
    saved = repository.get(int(existing.id))
    assert result.updated == 1
    assert saved.id == existing.id
    assert saved.device_uuid == existing.device_uuid
    assert saved.name == "New"
    assert saved.primary_address == "192.0.2.20"
    assert saved.ssh_password == "secret"


def test_bulk_update_only_not_found_has_no_writes_and_upsert_can_create(
    tmp_path: Path,
) -> None:
    _database, repository, service = _service(
        tmp_path / "site-a" / "db" / "devices.db"
    )
    source = tmp_path / "new.csv"
    _write_csv(
        source,
        {"设备名称": "New", "主用地址": "192.0.2.30"},
    )

    preview = service.preview_csv(
        source,
        match_strategy="SITE_PRIMARY_IP",
        write_mode="UPDATE_ONLY",
    )
    assert preview.not_found_count == 1
    assert preview.has_hard_errors is True
    with pytest.raises(ValueError, match="未写入任何设备"):
        service.import_csv_atomic(
            source,
            match_strategy="SITE_PRIMARY_IP",
            write_mode="UPDATE_ONLY",
        )
    assert repository.list() == []

    result = service.import_csv_atomic(
        source,
        match_strategy="SITE_PRIMARY_IP",
        write_mode="UPSERT",
    )
    assert result.created == 1
    assert repository.list()[0].primary_address == "192.0.2.30"


def test_bulk_preview_rejects_duplicate_final_ip_and_rolls_back(
    tmp_path: Path,
) -> None:
    _database, repository, service = _service(
        tmp_path / "site-a" / "db" / "devices.db"
    )
    source = tmp_path / "duplicates.csv"
    _write_csv(
        source,
        {"设备名称": "A", "主用地址": "192.0.2.40"},
        {"设备名称": "B", "主用地址": " 192.0.2.40 "},
    )

    preview = service.preview_csv(
        source,
        match_strategy="SITE_PRIMARY_IP",
        write_mode="UPSERT",
    )
    assert preview.conflict_count == 2
    assert preview.has_hard_errors is True
    assert {
        item.error_code for item in preview.row_results
    } == {"DUPLICATE_PRIMARY_IP_IN_FILE"}
    with pytest.raises(ValueError, match="未写入任何设备"):
        service.import_csv_atomic(
            source,
            match_strategy="SITE_PRIMARY_IP",
            write_mode="UPSERT",
        )
    assert repository.list() == []


def test_bulk_device_id_update_swaps_primary_addresses_atomically(
    tmp_path: Path,
) -> None:
    _database, repository, service = _service(
        tmp_path / "site-a" / "db" / "devices.db"
    )
    first = repository.create(Device(name="A", primary_address="192.0.2.51"))
    second = repository.create(Device(name="B", primary_address="192.0.2.52"))
    source = tmp_path / "swap.csv"
    _write_csv(
        source,
        {
            "设备ID": first.id,
            "设备名称": "A",
            "主用地址": "192.0.2.52",
        },
        {
            "设备ID": second.id,
            "设备名称": "B",
            "主用地址": "192.0.2.51",
        },
    )

    preview = service.preview_csv(
        source,
        match_strategy="DEVICE_ID",
        write_mode="UPDATE_ONLY",
    )
    assert preview.update_count == 2
    assert preview.has_hard_errors is False
    result = service.import_csv_atomic(
        source,
        match_strategy="DEVICE_ID",
        write_mode="UPDATE_ONLY",
    )
    assert result.updated == 2
    assert repository.get(int(first.id)).primary_address == "192.0.2.52"
    assert repository.get(int(second.id)).primary_address == "192.0.2.51"


def test_bulk_explicit_clear_marker_clears_credential_only_when_requested(
    tmp_path: Path,
) -> None:
    _database, repository, service = _service(
        tmp_path / "site-a" / "db" / "devices.db"
    )
    device = repository.create(
        Device(
            name="A",
            primary_address="192.0.2.61",
            ssh_username="admin",
            ssh_password="secret",
        )
    )
    source = tmp_path / "clear.csv"
    _write_csv(
        source,
        {
            "设备ID": device.id,
            "设备名称": "A",
            "主用地址": "192.0.2.61",
            "密码": "__CLEAR__",
        },
    )

    service.import_csv_atomic(
        source,
        match_strategy="DEVICE_ID",
        write_mode="UPDATE_ONLY",
    )

    saved = repository.get(int(device.id))
    assert saved.ssh_password is None
