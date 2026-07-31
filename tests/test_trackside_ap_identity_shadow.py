from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from netconsole.core.database import Database
from netconsole.repositories.ac_repository import AcRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.background_job import BackgroundJob
from netconsole.services.job_center.job_runner import run_job
from netconsole.services.rail_transit.trackside_ap_identity_shadow import (
    TracksideApIdentityShadowService,
)
from netconsole.services.trackside_ap_export_service import (
    load_trackside_ap_business_snapshot,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _resource(
    ap_uuid: str,
    ap_name: str,
    ap_mac: str,
    *,
    ac_uuid: str = "ac-1",
    **extra: object,
) -> dict[str, object]:
    return {
        "ap_uuid": ap_uuid,
        "ap_name": ap_name,
        "ap_mac": ap_mac,
        "ac_device_uuid": ac_uuid,
        **extra,
    }


def _database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "site.db")
    database.initialize()
    return database


def test_row_shadow_preserves_rows_and_matches_uuid_and_mac_only() -> None:
    resources = [
        _resource("ap-1", "AP-01", "0011-2233-4455"),
        _resource("ap-2", "AP-02", "0011-2233-4466"),
        _resource("ap-3", "AP-03", "0011-2233-4477", ac_uuid="ac-2"),
    ]
    rows = [
        {"ap_uuid": "ap-1", "ac_device_uuid": "ac-1", "ap_name": "AP-01"},
        {"ap_mac": "00:11:22:33:44:66", "ac_device_uuid": "ac-1"},
        {"ap_name": "AP-03", "ac_device_uuid": "ac-2"},
    ]
    before = deepcopy(rows)

    report = TracksideApIdentityShadowService().shadow_rows(rows, resources)

    assert rows == before
    assert report.total == 3
    assert report.matched == 2
    assert report.identity_unchanged == 2
    assert report.identity_changed == 1
    assert report.name_only_matches == 0
    assert report.unresolved == 1


def test_row_shadow_reports_cross_ac_mac_as_ambiguous_without_scope() -> None:
    resources = [
        _resource("ap-1", "AP-01", "0011-2233-4455", ac_uuid="ac-1"),
        _resource("ap-2", "AP-02", "0011-2233-4455", ac_uuid="ac-2"),
    ]

    report = TracksideApIdentityShadowService().shadow_rows(
        [{"ap_mac": "0011.2233.4455"}],
        resources,
    )

    assert report.ambiguous == 1
    assert report.missing_ac_scope == 1
    assert report.identity_changed == 1
    assert report.items[0].old_identity_key == "mac:00:11:22:33:44:55"


def test_interface_location_radio_and_lldp_are_evidence_not_ap_identity() -> None:
    resources = [
        _resource(
            "ap-1",
            "AP-01",
            "0011-2233-4455",
            radio1_mac="0011.2233.4466",
            bssid="0011.2233.4477",
        )
    ]
    rows = [
        {"device_uuid": "sw-1", "interface_name": "GigabitEthernet1/0/1"},
        {
            "device_uuid": "sw-1",
            "interface_name": "GigabitEthernet1/0/2",
            "lldp_neighbor_mac": "0011-2233-4455",
        },
        {"station": "A站", "section": "A-B区间", "mileage": "K1+000"},
        {"radio_mac": "0011.2233.4466", "bssid": "0011.2233.4477"},
    ]

    report = TracksideApIdentityShadowService().shadow_rows(rows, resources)

    assert report.unresolved == 4
    assert report.matched == 0
    assert report.interface_only_records == 1
    assert report.lldp_only_records == 1
    assert "topology identity 不参与 AP 匹配" in " ".join(report.items[0].warnings)
    assert "LLDP neighbor MAC 仅作为 observation evidence" in " ".join(
        report.items[1].warnings
    )
    assert "Radio MAC/BSSID 不作为轨旁 AP MAC 匹配输入" in " ".join(
        report.items[3].warnings
    )


def test_optical_fallback_is_counted_without_changing_match_result() -> None:
    row = {
        "ap_uuid": "ap-1",
        "ac_device_uuid": "ac-1",
        "ap_name": "AP-01",
        "identity_source": "optical_fallback",
    }
    report = TracksideApIdentityShadowService().shadow_rows(
        [row],
        [_resource("ap-1", "AP-01", "0011-2233-4455")],
    )

    assert report.matched == 1
    assert report.identity_unchanged == 1
    assert report.optical_fallback_records == 1


def test_detail_shadow_preserves_old_matches_and_reports_different_candidate() -> None:
    resources = [
        _resource("ap-1", "AP-01", "0011-2233-4455"),
        _resource("ap-2", "AP-02", "0011-2233-4466"),
    ]
    old_matches = [dict(resources[0])]
    before = deepcopy(old_matches)

    report = TracksideApIdentityShadowService().shadow_detail_matches(
        old_matches,
        resources,
        {"ap_mac": "0011-2233-4466", "ac_device_uuid": "ac-1"},
    )

    assert old_matches == before
    assert report.matched == 1
    assert report.identity_changed == 1
    assert report.identity_unchanged == 0
    assert report.items[0].new_candidate_key == "uuid:ap-2"


def test_detail_job_preserves_uuid_mac_and_name_fallback_matches(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    repository = AcRepository(database)
    repository.replace_fit_ap_resources(
        "ac-1",
        [
            _resource("ap-1", "AP-01", "0011-2233-4455"),
            _resource("ap-2", "AP-02", "0011-2233-4466"),
        ],
    )
    base = {"db_path": str(database.path), "data_root": str(tmp_path)}

    direct = run_job(
        BackgroundJob(
            job_id="trackside-detail-uuid",
            task_type="trackside_fit_ap_detail_resolve",
            params={
                **base,
                "ac_device_uuid": "ac-1",
                "ap_uuid": "ap-1",
                "ap_name": "AP-01",
            },
        )
    )
    by_mac = run_job(
        BackgroundJob(
            job_id="trackside-detail-mac",
            task_type="trackside_fit_ap_detail_resolve",
            params={**base, "ap_mac": "00:11:22:33:44:66", "ap_name": "wrong-name"},
        )
    )
    by_name = run_job(
        BackgroundJob(
            job_id="trackside-detail-name",
            task_type="trackside_fit_ap_detail_resolve",
            params={**base, "ap_name": "AP-01"},
        )
    )

    assert direct.ok is True
    assert direct.result["matches"] == [
        {"ac_device_uuid": "ac-1", "ap_uuid": "ap-1", "ap_name": "AP-01"}
    ]
    assert direct.result["detail_identity_shadow"]["identity_unchanged"] == 1
    assert by_mac.ok is True
    assert by_mac.result["matches"][0]["ap_uuid"] == "ap-2"
    assert by_mac.result["detail_identity_shadow"]["identity_unchanged"] == 1
    assert by_name.ok is True
    assert by_name.result["matches"] == []
    assert by_name.result["detail_identity_shadow"]["unresolved"] == 1


def test_detail_shadow_failure_does_not_change_matches_or_finished(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    AcRepository(database).replace_fit_ap_resources(
        "ac-1",
        [_resource("ap-1", "AP-01", "0011-2233-4455")],
    )

    def fail(*_args, **_kwargs):
        raise RuntimeError("诊断失败")

    monkeypatch.setattr(TracksideApIdentityShadowService, "shadow_detail_matches", fail)
    result = run_job(
        BackgroundJob(
            job_id="trackside-detail-shadow-failed",
            task_type="trackside_fit_ap_detail_resolve",
            params={
                "db_path": str(database.path),
                "data_root": str(tmp_path),
                "ac_device_uuid": "ac-1",
                "ap_uuid": "ap-1",
                "ap_name": "AP-01",
            },
        )
    )

    assert result.ok is True
    assert result.result["matches"] == [
        {"ac_device_uuid": "ac-1", "ap_uuid": "ap-1", "ap_name": "AP-01"}
    ]
    assert result.result["detail_identity_shadow"]["available"] is False
    assert "诊断失败" in result.result["detail_identity_shadow"]["warnings"][0]


def test_snapshot_and_compatibility_job_append_shadow_after_old_rows(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    repository = DeviceRepository(database)

    snapshot = load_trackside_ap_business_snapshot(repository, "demo", 1)
    job = run_job(
        BackgroundJob(
            job_id="trackside-business-shadow",
            task_type="ac_trackside_business_refresh",
            params={
                "db_path": str(database.path),
                "site_name": "demo",
                "data_root": str(tmp_path),
            },
        )
    )

    assert snapshot.rows == []
    assert snapshot.identity_shadow["available"] is True
    assert snapshot.identity_shadow["total"] == 0
    assert job.ok is True
    assert job.result["rows"] == []
    assert job.result["identity_shadow"]["available"] is True


def test_aggregate_shadow_failure_does_not_change_rows_or_finished(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)

    def fail(*_args, **_kwargs):
        raise RuntimeError("聚合诊断失败")

    monkeypatch.setattr(TracksideApIdentityShadowService, "shadow_rows", fail)
    snapshot = load_trackside_ap_business_snapshot(
        DeviceRepository(database), "demo", 1
    )
    job = run_job(
        BackgroundJob(
            job_id="trackside-business-shadow-failed",
            task_type="ac_trackside_business_refresh",
            params={
                "db_path": str(database.path),
                "site_name": "demo",
                "data_root": str(tmp_path),
            },
        )
    )

    assert snapshot.rows == []
    assert snapshot.identity_shadow["available"] is False
    assert job.ok is True
    assert job.result["rows"] == []
    assert job.result["identity_shadow"]["available"] is False


def test_trackside_shadow_static_boundaries_remain_pure() -> None:
    source = (
        PROJECT_ROOT
        / "src"
        / "netconsole"
        / "services"
        / "rail_transit"
        / "trackside_ap_identity_shadow.py"
    ).read_text(encoding="utf-8")

    for forbidden in (
        "PySide6",
        "netconsole.ui",
        "repositories",
        "Database",
        "subprocess",
        "netmiko",
        "socket",
    ):
        assert forbidden not in source
