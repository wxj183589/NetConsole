from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tests.support.rail_transit_base_data_write_fixture import build_copy_service, create_plan
from netconsole.models.api.rail_transit_base_data import (
    FieldProvenanceDTO,
    ImportPreviewRowDTO,
    MergeFieldDecisionDTO,
    MergeFieldDiffDTO,
)
from netconsole.services.rail_transit.base_data_import_service import BaseDataImportError


def test_same_preview_applies_only_once(tmp_path: Path) -> None:
    _paths, _database, service = build_copy_service(tmp_path)
    plan = create_plan(service, "54")
    preview_id = service.save_preview(plan)
    service.apply_preview(
        preview_id=preview_id,
        site_id="demo",
        expected_database_sha256=plan.database_hash,
        explicit_confirmation=True,
    )

    with pytest.raises(BaseDataImportError) as error:
        service.apply_preview(
            preview_id=preview_id,
            site_id="demo",
            expected_database_sha256=plan.database_hash,
            explicit_confirmation=True,
        )
    assert error.value.code == "ALREADY_APPLIED"


def test_expired_preview_and_changed_database_are_rejected_before_backup(tmp_path: Path) -> None:
    paths, database, service = build_copy_service(tmp_path)
    expired = create_plan(service, "55").model_copy(
        update={"preview_expires_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()}
    )
    expired_id = service.save_preview(expired)
    with pytest.raises(BaseDataImportError) as error:
        service.apply_preview(
            preview_id=expired_id,
            site_id="demo",
            expected_database_sha256=expired.database_hash,
            explicit_confirmation=True,
        )
    assert error.value.code == "BASE_DATA_PREVIEW_EXPIRED"

    current = create_plan(service, "56")
    current_id = service.save_preview(current)
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE ap_extension_points SET remark = 'changed' WHERE id = 1")
        connection.commit()
    with pytest.raises(BaseDataImportError) as error:
        service.apply_preview(
            preview_id=current_id,
            site_id="demo",
            expected_database_sha256=current.database_hash,
            explicit_confirmation=True,
        )
    assert error.value.code == "BASE_DATA_DATABASE_CHANGED"
    assert not paths.rail_transit_base_data_import_backups_dir("demo").exists()


def test_existing_value_is_preserved_and_blocking_conflict_cannot_be_skipped(
    tmp_path: Path,
) -> None:
    _paths, _database, service = build_copy_service(tmp_path)
    manual = service.build_merge_plan(
        site_id="demo",
        source_file_name="manual.json",
        source_file_sha256="e" * 64,
        rows=[
            ImportPreviewRowDTO(
                row_number=1,
                values={
                    "ap_name": "AP-Section",
                    "ap_mac_norm": "000000000002",
                    "section_name": "候选区间",
                },
            )
        ],
    )
    manual_id = service.save_preview(manual)
    audit = service.apply_preview(
        preview_id=manual_id,
        site_id="demo",
        expected_database_sha256=manual.database_hash,
        explicit_confirmation=True,
    )
    assert audit["unchanged_rows"] == 1
    assert any(issue["code"] == "existing_value_preserved" for issue in audit["issues"])
    persisted = next(
        row
        for row in service.repository.list_ap_records("demo")
        if row["ap_mac_norm"] == "000000000002"
    )
    assert persisted["section_name"] == "A-B 区间"

    conflict = service.build_merge_plan(
        site_id="demo",
        source_file_name="conflict.json",
        source_file_sha256="f" * 64,
        rows=[
            ImportPreviewRowDTO(
                row_number=1,
                values={
                    "ap_point_code": "OTHER-POINT",
                    "ap_mac_norm": "000000000002",
                },
            )
        ],
    )
    assert conflict.items[0].result == "CONFLICT"
    with pytest.raises(BaseDataImportError) as error:
        service.resolve_decisions(
            conflict,
            [MergeFieldDecisionDTO(row_number=1, action="skip_entity")],
        )
    assert error.value.code == "BASE_DATA_BLOCKING_ISSUES"


def test_runtime_field_decision_is_rejected(tmp_path: Path) -> None:
    _paths, _database, service = build_copy_service(tmp_path)
    plan = create_plan(service, "57")
    item = plan.items[0]
    runtime_diff = MergeFieldDiffDTO(
        field_name="management_ip",
        current_value="",
        proposed_value="10.0.0.10",
        source=FieldProvenanceDTO(field_name="management_ip", source_type="ac_fit_ap"),
        action="manual_review",
    )
    plan = plan.model_copy(
        update={"items": [item.model_copy(update={"field_diffs": [*item.field_diffs, runtime_diff]})]},
        deep=True,
    )
    with pytest.raises(BaseDataImportError) as error:
        service.resolve_decisions(
            plan,
            [MergeFieldDecisionDTO(row_number=1, field_name="management_ip", action="use_imported")],
        )
    assert error.value.code == "BASE_DATA_SOURCE_INVALID"
