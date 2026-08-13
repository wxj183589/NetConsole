from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tests.support.rail_transit_base_data_write_fixture import build_copy_service, create_plan
from netconsole.services.rail_transit.base_data_import_service import BaseDataImportError


def test_field_rollback_succeeds_and_second_rollback_is_rejected(tmp_path: Path) -> None:
    _paths, _database, service = build_copy_service(tmp_path)
    plan = create_plan(service, "52")
    audit = service.apply_merge_plan(plan, confirmed=True)

    result = service.rollback_import(
        site_id="demo",
        operation_id=audit["operation_id"],
        explicit_confirmation=True,
    )

    assert result["status"] == "ROLLED_BACK"
    assert not any(row["ap_name"] == "AP-Copy-52" for row in service.repository.list_ap_records("demo"))
    with pytest.raises(BaseDataImportError) as error:
        service.rollback_import(
            site_id="demo",
            operation_id=audit["operation_id"],
            explicit_confirmation=True,
        )
    assert error.value.code == "BASE_DATA_ROLLBACK_CONFLICT"


def test_rollback_rejects_later_database_change(tmp_path: Path) -> None:
    _paths, database, service = build_copy_service(tmp_path)
    audit = service.apply_merge_plan(create_plan(service, "53"), confirmed=True)
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE ap_extension_points SET remark = 'later' WHERE id = 1")
        connection.commit()

    with pytest.raises(BaseDataImportError) as error:
        service.rollback_import(
            site_id="demo",
            operation_id=audit["operation_id"],
            explicit_confirmation=True,
        )
    assert error.value.code == "BASE_DATA_ROLLBACK_CONFLICT"


def test_field_check_rejects_change_inside_rollback_transaction(tmp_path: Path, monkeypatch) -> None:
    _paths, database, service = build_copy_service(tmp_path)
    audit = service.apply_merge_plan(create_plan(service, "60"), confirmed=True)
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE ap_extension_points SET ap_name = 'later-name' WHERE import_batch_id = ?", (audit["operation_id"],))
        connection.commit()
    monkeypatch.setattr(service.repository, "database_hash", lambda _site_id: audit["database_hash_after"])

    with pytest.raises(BaseDataImportError) as error:
        service.rollback_import(
            site_id="demo",
            operation_id=audit["operation_id"],
            explicit_confirmation=True,
        )

    assert error.value.code == "BASE_DATA_ROLLBACK_CONFLICT"
