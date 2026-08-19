from __future__ import annotations

import json
from pathlib import Path

from netconsole.services.history_legacy_migration import SUPPORTED_SPECS


ROOT = Path(__file__).resolve().parents[1]


def test_unsupported_history_contract_documents_real_consumers() -> None:
    contract = (ROOT / "docs/storage/UNSUPPORTED_HISTORY_CONSUMER_CONTRACT.md").read_text(
        encoding="utf-8"
    )
    for table in (
        "ac_fit_ap_unauthenticated_history",
        "ac_station_online_summary_history",
    ):
        assert table in contract
        assert table in SUPPORTED_SPECS
    assert "不能继续标成“无消费者”" in contract
    assert "SUPPORTED_TARGET_EVENT_CONTRACT" in contract


def test_unsupported_tables_have_producer_and_reader_evidence() -> None:
    ac_repository = (ROOT / "src/netconsole/repositories/ac_repository.py").read_text(
        encoding="utf-8"
    )
    handlers = (ROOT / "src/netconsole/services/job_center/handlers/legacy_tasks.py").read_text(
        encoding="utf-8"
    )
    exporters = (ROOT / "src/netconsole/services/export/common_exporters.py").read_text(
        encoding="utf-8"
    )
    snapshot = (ROOT / "src/netconsole/services/rail_transit/trackside_ap_business_snapshot.py").read_text(
        encoding="utf-8"
    )
    assert "replace_fit_ap_unauthenticated" in ac_repository
    assert "list_fit_ap_unauthenticated_history" in ac_repository
    assert "save_station_online_summary_history" in ac_repository
    assert "list_station_online_summary_history" in ac_repository
    assert "ac_overview_history_snapshot" in handlers
    assert "list_station_online_summary_history" in exporters
    assert "ac_fit_ap_unauthenticated_history" in snapshot


def test_supported_history_has_explicit_target_contract() -> None:
    migration = (ROOT / "src/netconsole/services/history_legacy_migration.py").read_text(
        encoding="utf-8"
    )
    assert 'classification = "SUPPORTED"' in migration
    assert "SUPPORTED_SPECS" in migration
    # Keep the machine-readable registry and the explicit target contract aligned.
    registry = json.loads(
        (ROOT / "config/storage_registry.yaml").read_text(encoding="utf-8")
    )
    text = json.dumps(registry, ensure_ascii=False)
    for table in (
        "ac_fit_ap_unauthenticated_history",
        "ac_station_online_summary_history",
    ):
        assert table in text

