from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from rail_transit_base_data_fixture import build_rail_transit_base_data_fixture, mark_base_data_copy
from netconsole.models.api.rail_transit_base_data import ImportPreviewRowDTO
from netconsole.repositories.rail_transit_base_data_repository import RailTransitBaseDataRepository
from netconsole.services.rail_transit.base_data_import_service import (
    BaseDataImportError,
    RailTransitBaseDataImportService,
)
from netconsole.services.rail_transit.base_data_write_guard import BaseDataWriteGuard


def _service(paths, *, repository=None, write_enabled: bool = True, rollback_enabled: bool = True):
    return RailTransitBaseDataImportService(
        paths,
        repository=repository,
        guard=BaseDataWriteGuard(
            paths,
            feature_enabled=True,
            write_enabled=write_enabled,
            copy_write_enabled=True,
            rollback_enabled=rollback_enabled,
        ),
    )


def _plan(service: RailTransitBaseDataImportService, *rows: ImportPreviewRowDTO):
    return service.build_merge_plan(
        site_id="demo",
        rows=rows,
        source_file_name="official.xlsx",
        source_file_sha256="b" * 64,
    )


def _create_row(number: int, suffix: str) -> ImportPreviewRowDTO:
    return ImportPreviewRowDTO(
        row_number=number,
        values={"ap_name": f"AP-New-{suffix}", "ap_mac_norm": f"0011223344{int(suffix):02d}"},
    )


def test_apply_is_disabled_by_default_and_rejects_changed_database(tmp_path: Path) -> None:
    paths, db_path = build_rail_transit_base_data_fixture(tmp_path)
    disabled = _service(paths, write_enabled=False)
    plan = _plan(disabled, _create_row(1, "10"))
    with pytest.raises(BaseDataImportError, match="未启用") as disabled_error:
        disabled.apply_merge_plan(plan, confirmed=True)
    assert disabled_error.value.code == "BASE_DATA_WRITE_DISABLED"

    mark_base_data_copy(paths)
    enabled = _service(paths)
    stale_plan = _plan(enabled, _create_row(1, "11"))
    with sqlite3.connect(db_path) as connection:
        connection.execute("UPDATE ap_extension_points SET remark = 'changed' WHERE id = 1")
        connection.commit()
    with pytest.raises(BaseDataImportError) as changed_error:
        enabled.apply_merge_plan(stale_plan, confirmed=True)
    assert changed_error.value.code == "BASE_DATA_DATABASE_CHANGED"


def test_import_policy_encapsulates_guard_status_and_source_rules(tmp_path: Path) -> None:
    paths, _db_path = build_rail_transit_base_data_fixture(tmp_path)
    service = _service(paths)

    real_policy = service.get_import_policy("demo")
    assert real_policy.write_scope == "real"
    assert real_policy.real_write_authorized is False
    assert real_policy.identity_boundaries["formal"].startswith("正式基础资料")
    assert next(item for item in real_policy.items if item.field_name == "management_ip").runtime_only is True

    mark_base_data_copy(paths)
    copy_policy = service.get_import_policy("demo")
    assert copy_policy.write_scope == "copy_validation"
    assert copy_policy.copy_write_authorized is True


def test_temp_database_apply_audit_and_rollback_are_atomic(tmp_path: Path) -> None:
    paths, _db_path = build_rail_transit_base_data_fixture(tmp_path)
    mark_base_data_copy(paths)
    service = _service(paths)
    plan = _plan(service, _create_row(1, "12"))

    audit = service.apply_merge_plan(plan, confirmed=True, owner="tester")
    assert audit["status"] == "APPLIED"
    assert audit["created_count"] == 1
    serialized = json.dumps(audit, ensure_ascii=False)
    assert str(tmp_path) not in serialized
    assert "password" not in serialized.casefold()
    assert any(row["ap_name"] == "AP-New-12" for row in service.repository.list_ap_records("demo"))

    rolled_back = service.rollback_import(
        site_id="demo",
        operation_id=audit["operation_id"],
        explicit_confirmation=True,
    )
    assert rolled_back["status"] == "ROLLED_BACK"
    assert not any(row["ap_name"] == "AP-New-12" for row in service.repository.list_ap_records("demo"))


def test_audit_drops_sensitive_owner_text(tmp_path: Path) -> None:
    paths, _db_path = build_rail_transit_base_data_fixture(tmp_path)
    mark_base_data_copy(paths)
    service = _service(paths)
    plan = _plan(service, _create_row(1, "16"))

    audit = service.apply_merge_plan(plan, confirmed=True, owner="password=not-for-audit")

    assert audit["owner"] == ""
    assert "not-for-audit" not in json.dumps(audit, ensure_ascii=False)


def test_update_rollback_restores_tracking_fields(tmp_path: Path) -> None:
    paths, _db_path = build_rail_transit_base_data_fixture(tmp_path)
    mark_base_data_copy(paths)
    service = _service(paths)
    before = next(row for row in service.repository.list_ap_records("demo") if row["ap_name"] == "AP-Section")
    plan = _plan(
        service,
        ImportPreviewRowDTO(
            row_number=1,
            values={
                "ap_name": "AP-Section",
                "ap_mac_norm": "000000000002",
                "uplink_switch": "SW-ROLLBACK-TEST",
            },
        ),
    )

    audit = service.apply_merge_plan(plan, confirmed=True)
    service.rollback_import(site_id="demo", operation_id=audit["operation_id"], explicit_confirmation=True)
    after = next(row for row in service.repository.list_ap_records("demo") if row["ap_name"] == "AP-Section")

    assert after == before


def test_partial_update_keeps_existing_mileage_remark_and_merges_source_metadata(tmp_path: Path) -> None:
    paths, db_path = build_rail_transit_base_data_fixture(tmp_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE ap_extension_points SET mileage_text = ?, mileage_m = ?, remark = ?, raw_payload_json = ? WHERE ap_name = ?",
            ("YDK12+350", 12350, "现场确认", json.dumps({"existing": "kept"}), "AP-Section"),
        )
        connection.commit()
    mark_base_data_copy(paths)
    service = _service(paths)
    plan = _plan(
        service,
        ImportPreviewRowDTO(
            row_number=2,
            values={
                "ap_name": "AP-Section",
                "ap_mac_norm": "000000000002",
                "mileage_text": "",
                "remark": "",
                "uplink_switch": "SW-POINT-TABLE",
                "source_sheet": "轨旁AP业务",
                "source_row": 2,
                "raw_payload_json": json.dumps({"import_source": {"station_name": "11-高桥西"}}, ensure_ascii=False),
            },
        ),
    )

    service.apply_merge_plan(plan, confirmed=True)
    after = next(row for row in service.repository.list_ap_records("demo") if row["ap_name"] == "AP-Section")

    assert after["mileage_text"] == "YDK12+350"
    assert after["mileage_m"] == 12350
    assert after["remark"] == "现场确认"
    assert after["uplink_switch"] == "SW-POINT-TABLE"
    assert after["source_sheet"] == "轨旁AP业务"
    assert after["source_row"] == 2
    assert json.loads(after["raw_payload_json"]) == {
        "existing": "kept",
        "import_source": {"station_name": "11-高桥西"},
    }


def test_transaction_failure_rolls_back_all_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths, _db_path = build_rail_transit_base_data_fixture(tmp_path)
    mark_base_data_copy(paths)
    repository = RailTransitBaseDataRepository(paths)
    service = _service(paths, repository=repository)
    plan = _plan(service, _create_row(1, "13"), _create_row(2, "14"))
    before = repository.database_hash("demo")
    original = repository._apply_operation
    calls = 0

    def fail_second(connection, site_id, operation_id, operation):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise sqlite3.OperationalError("injected transaction failure")
        return original(connection, site_id, operation_id, operation)

    monkeypatch.setattr(repository, "_apply_operation", fail_second)
    with pytest.raises(BaseDataImportError) as error:
        service.apply_merge_plan(plan, confirmed=True)

    assert error.value.code == "BASE_DATA_TRANSACTION_FAILED"
    assert repository.database_hash("demo") == before
    assert not any(row["ap_name"] in {"AP-New-13", "AP-New-14"} for row in repository.list_ap_records("demo"))


def test_rollback_rejects_later_database_changes(tmp_path: Path) -> None:
    paths, db_path = build_rail_transit_base_data_fixture(tmp_path)
    mark_base_data_copy(paths)
    service = _service(paths)
    audit = service.apply_merge_plan(_plan(service, _create_row(1, "15")), confirmed=True)
    with sqlite3.connect(db_path) as connection:
        connection.execute("UPDATE ap_extension_points SET remark = 'later-change' WHERE id = 1")
        connection.commit()

    with pytest.raises(BaseDataImportError) as error:
        service.rollback_import(site_id="demo", operation_id=audit["operation_id"], explicit_confirmation=True)
    assert error.value.code == "BASE_DATA_ROLLBACK_CONFLICT"
