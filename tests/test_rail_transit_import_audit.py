from __future__ import annotations

import json
import sqlite3
from argparse import Namespace
from pathlib import Path

import pytest

from netconsole.services.rail_transit.base_data_import_service import BaseDataImportError
from scripts.maintenance.test_rail_transit_base_data_apply import run

from tests.support.rail_transit_base_data_fixture import build_rail_transit_base_data_fixture
from tests.support.rail_transit_base_data_write_fixture import build_copy_service, create_plan


def test_apply_creates_backup_and_redacted_field_audit(tmp_path: Path) -> None:
    paths, _database, service = build_copy_service(tmp_path)
    plan = create_plan(service, "51")
    preview_id = service.save_preview(plan)

    audit = service.apply_preview(
        preview_id=preview_id,
        site_id="demo",
        expected_database_sha256=plan.database_hash,
        explicit_confirmation=True,
        owner="password=must-not-appear",
    )

    serialized = json.dumps(audit, ensure_ascii=False)
    assert audit["status"] == "APPLIED"
    assert audit["owner"] == ""
    assert str(tmp_path) not in serialized
    assert "must-not-appear" not in serialized
    assert audit["import_changes"]
    backup = paths.rail_transit_base_data_import_root("demo") / audit["backup_reference"]
    with sqlite3.connect(backup) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    operation = service.get_operation("demo", audit["operation_id"])
    changes = service.list_operation_changes("demo", audit["operation_id"])
    assert operation.preview_id == preview_id
    assert changes and all(change.source_reference == "controlled-preview.json" for change in changes)


def test_backup_or_post_integrity_failure_never_leaves_partial_business_rows(tmp_path: Path, monkeypatch) -> None:
    paths, _database, service = build_copy_service(tmp_path)
    backup_plan = create_plan(service, "58")
    before = service.repository.database_hash("demo")

    def fail_backup(_site_id, _target):
        raise sqlite3.OperationalError("backup failed")

    monkeypatch.setattr(service.repository, "backup_database", fail_backup)
    with pytest.raises(BaseDataImportError) as error:
        service.apply_merge_plan(backup_plan, confirmed=True)
    assert error.value.code == "BASE_DATA_BACKUP_FAILED"
    assert service.repository.database_hash("demo") == before
    audit_path = paths.rail_transit_base_data_import_operations_dir("demo") / f"{backup_plan.plan_id}.json"
    failed_audit = json.loads(audit_path.read_text(encoding="utf-8"))
    assert failed_audit["status"] == "FAILED"
    assert failed_audit["error_code"] == "BASE_DATA_BACKUP_FAILED"

    service = build_copy_service(tmp_path / "integrity")[2]
    integrity_plan = create_plan(service, "59")

    def fail_integrity(_site_id):
        raise sqlite3.DatabaseError("integrity failed")

    monkeypatch.setattr(service.repository, "assert_integrity", fail_integrity)
    with pytest.raises(BaseDataImportError) as error:
        service.apply_merge_plan(integrity_plan, confirmed=True)
    assert error.value.code == "BASE_DATA_TRANSACTION_FAILED"
    assert not any(row["ap_name"] == "AP-Copy-59" for row in service.repository.list_ap_records("demo"))


def test_copy_validation_script_applies_and_rolls_back_without_touching_source(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _paths, source = build_rail_transit_base_data_fixture(tmp_path / "source")
    preview_file = tmp_path / "preview.json"
    preview_file.write_text(
        json.dumps({"rows": [{"ap_name": "AP-Copy-Script", "ap_mac_norm": "001122334499"}]}),
        encoding="utf-8",
    )
    before = (source.read_bytes(), source.stat().st_mtime_ns)
    monkeypatch.setenv("RAIL_TRANSIT_BASE_DATA_WRITE_ENABLED", "1")
    monkeypatch.setenv("NETCONSOLE_ALLOW_BASE_DATA_COPY_WRITE", "1")
    monkeypatch.setenv("RAIL_TRANSIT_BASE_DATA_ROLLBACK_ENABLED", "1")
    monkeypatch.setenv("NETCONSOLE_ALLOW_REAL_BASE_DATA_WRITE", "0")

    result = run(
        Namespace(
            source_db=source,
            copy_dir=tmp_path / "copy-validation",
            preview_file=preview_file,
            site="demo-copy",
            apply=True,
            rollback=True,
        )
    )

    assert result["status"] == "ROLLED_BACK"
    assert result["source_unchanged"] is True
    assert (source.read_bytes(), source.stat().st_mtime_ns) == before
    assert str(source) != result["copy_db"]
