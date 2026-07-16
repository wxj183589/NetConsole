from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from ac_management_web_fixture import build_ac_management_fixture
from netconsole.core.database import Database
from netconsole.repositories.ac_repository import AcRepository
from netconsole.services.ac.query_service import AcManagementQueryService
from netconsole.services.config_lifecycle_service import extract_h3c_configuration_body


def _fingerprint(path: Path) -> tuple[str, int]:
    return hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns


def test_ac_query_service_reads_summary_filters_and_details_without_writes(tmp_path: Path) -> None:
    paths, db_path, _files = build_ac_management_fixture(tmp_path)
    service = AcManagementQueryService(paths)
    before = _fingerprint(db_path)

    summary = service.get_summary("demo")
    online = service.list_aps("demo", status="online")
    offline = service.list_aps("demo", status="offline")
    unauthenticated = service.list_aps("demo", status="unauthenticated")
    section = service.list_aps("demo", section="A-B")
    detail = service.get_ap_detail("demo", "ap-offline")

    assert summary.ap_total == 3
    assert summary.online_aps == 2
    assert summary.offline_aps == 1
    assert summary.unauthenticated_aps == 1
    assert summary.acs[0].web_url == "https://10.0.0.1:443"
    assert online.total == 1
    assert offline.total == 1
    assert unauthenticated.total == 1
    assert section.items[0].id == "ap-online"
    assert detail is not None
    assert [radio.radio_id for radio in detail.radios] == [1, 2]
    assert all(radio.radio_id != 3 for radio in detail.radios)
    assert [radio.clients for radio in detail.radios] == [3, 1]
    assert "serial" not in str(detail.model_dump()).casefold()
    assert "SECRET-SN" not in str(detail.model_dump())
    assert _fingerprint(db_path) == before


def test_ac_query_service_returns_allowlisted_radio_history_without_raw_paths(tmp_path: Path) -> None:
    paths, _db_path, _files = build_ac_management_fixture(tmp_path)
    repository = AcRepository(Database(paths.site_db_path("demo")))
    ap = repository.get_fit_ap_resource_by_uuid("ac-1", "ap-online")
    assert ap is not None
    repository.upsert_fit_ap_resource("ac-1", ap)
    service = AcManagementQueryService(paths)

    history = service.get_ap_history("demo", "ap-online", "radio")

    assert history is not None
    assert history.total == 2
    assert {int(row["rid"]): int(row["clients"] or 0) for row in history.items} == {1: 3, 2: 1}
    assert all("ap_name" in row and "status" in row and "usage" in row for row in history.items)
    assert all("raw_log_path" not in row for row in history.items)
    with pytest.raises(ValueError, match="不支持"):
        service.get_ap_history("demo", "ap-online", "unknown")


def test_ac_optical_anomaly_requires_ap_offline_relation(tmp_path: Path) -> None:
    paths, _db_path, _files = build_ac_management_fixture(tmp_path)
    service = AcManagementQueryService(paths)

    online = service.get_ap_optical("demo", "ap-online")
    offline = service.get_ap_optical("demo", "ap-offline")
    anomalies = service.list_optical_anomalies("demo")

    assert online is not None
    assert online.raw_status == "no_light"
    assert online.optical_status == "unrelated"
    assert online.ap_offline_related is False
    assert offline is not None
    assert offline.optical_status == "critical"
    assert offline.ap_offline_related is True
    assert [item.id for item in anomalies.items] == ["ap-offline"]


def test_ac_config_snapshot_content_diff_and_path_isolation(tmp_path: Path) -> None:
    paths, db_path, files = build_ac_management_fixture(tmp_path)
    service = AcManagementQueryService(paths)
    running_before = _fingerprint(files["running"])
    db_before = _fingerprint(db_path)
    page = service.list_config_snapshots("demo")
    running = next(item for item in page.items if item.type == "running")

    content = service.get_config_snapshot("demo", running.id)
    diff = service.get_config_diff("demo", running.id)

    assert content is not None
    assert content.content == extract_h3c_configuration_body(files["running"].read_text(encoding="utf-8"))
    assert "header" not in content.content
    assert "<AC-TEST>" not in content.content
    assert diff is not None
    assert "10.0.0.1" in diff.raw_diff
    assert "10.0.0.9" in diff.raw_diff
    assert _fingerprint(files["running"]) == running_before
    assert _fingerprint(db_path) == db_before

    with pytest.raises(ValueError, match="路径越界"):
        service._snapshot_path("demo", {"file_path": "../outside.txt"})
