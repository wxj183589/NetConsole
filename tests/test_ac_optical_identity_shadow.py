from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import json

import pytest

from netconsole.services.ac.ac_models import AcOpticalRefreshResult, AcOpticalSnapshot
from netconsole.services.ac.ac_optical_identity_adapter import AcOpticalIdentityAdapter
from netconsole.services.ac.ac_optical_service import enrich_fit_ap_optical_rows
from netconsole.services.background_job import BackgroundJob
from netconsole.services.job_center.handlers import ac_jobs
from netconsole.services.job_center.job_runner import run_job


def _fit_ap(
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


def test_ap_side_shadow_reports_unchanged_unresolved_ambiguous_and_changed() -> None:
    adapter = AcOpticalIdentityAdapter()
    candidates = [
        _fit_ap("ap-1", "AP-01", "0011-2233-4455", ac_uuid="ac-1"),
        _fit_ap("ap-2", "AP-02", "0011-2233-4466", ac_uuid="ac-1"),
        _fit_ap("ap-3", "AP-03", "0011-2233-4455", ac_uuid="ac-2"),
    ]

    unchanged = adapter.shadow_compare_optical_binding(
        [{"record_type": "ap_side", "ap_uuid": "ap-1", "ap_name": "AP-01"}],
        candidates,
        ac_uuid="ac-1",
    )
    unresolved = adapter.shadow_compare_optical_binding(
        [{"record_type": "ap_side", "ap_uuid": "missing-ap"}],
        candidates,
        ac_uuid="ac-1",
    )
    ambiguous = adapter.shadow_compare_optical_binding(
        [{"record_type": "ap_side", "ap_mac": "0011.2233.4455"}],
        candidates,
    )
    changed = adapter.shadow_compare_optical_binding(
        [{"record_type": "ap_side", "ap_uuid": "old-ap", "ap_mac": "0011-2233-4466"}],
        candidates,
        ac_uuid="ac-1",
    )

    assert unchanged.identity_unchanged == 1
    assert unchanged.items[0].new_candidate_key == "uuid:ap-1"
    assert unresolved.unresolved == 1
    assert unresolved.identity_changed == 1
    assert ambiguous.ambiguous == 1
    assert ambiguous.missing_ac_scope == 1
    assert changed.matched == 1
    assert changed.identity_changed == 1
    assert changed.items[0].new_candidate_key == "uuid:ap-2"


def test_switch_side_interface_is_not_ap_identity_but_explicit_binding_can_be_compared() -> None:
    adapter = AcOpticalIdentityAdapter()
    candidates = [_fit_ap("ap-1", "AP-01", "0011-2233-4455")]
    report = adapter.shadow_compare_optical_binding(
        [
            {
                "record_type": "switch_side",
                "neighbor_device_name": "SW-01",
                "neighbor_interface": "GigabitEthernet1/0/1",
            },
            {
                "record_type": "switch_side",
                "ap_uuid": "ap-1",
                "neighbor_device_name": "SW-01",
                "neighbor_interface": "GigabitEthernet1/0/2",
            },
        ],
        candidates,
        ac_uuid="ac-1",
    )

    assert report.switch_side_records == 2
    assert report.interface_only_records == 1
    assert report.items[0].new_status == "unresolved"
    assert "交换机接口不是 AP identity" in " ".join(report.items[0].warnings)
    assert report.items[1].new_status == "matched"
    assert report.items[1].identity_unchanged is True


def test_scope_name_only_and_mac_like_name_diagnostics() -> None:
    adapter = AcOpticalIdentityAdapter()
    candidates = [
        _fit_ap("ap-1", "AP-01", "0011-2233-4455", ac_uuid="ac-1"),
        _fit_ap("ap-2", "AP-01", "0011-2233-4455", ac_uuid="ac-2"),
    ]

    scoped = adapter.shadow_compare_optical_binding(
        [{"record_type": "ap_side", "ap_mac": "0011-2233-4455"}],
        candidates,
        ac_uuid="ac-1",
    )
    name_only = adapter.shadow_compare_optical_binding(
        [{"record_type": "ap_side", "ap_name": "AP-01"}],
        candidates,
        ac_uuid="ac-2",
    )
    mac_like = adapter.shadow_compare_optical_binding(
        [{"record_type": "ap_side", "ap_name": "0011-2233-4455"}],
        candidates,
        ac_uuid="ac-1",
    )

    assert scoped.matched == 1
    assert scoped.ambiguous == 0
    assert name_only.name_only_matches == 1
    assert name_only.matched == 1
    assert name_only.unresolved == 0
    assert mac_like.mac_like_names == 1


def test_radio_bssid_and_peer_mac_never_become_optical_ap_match_inputs() -> None:
    adapter = AcOpticalIdentityAdapter()
    candidates = [
        _fit_ap(
            "ap-1",
            "AP-01",
            "0011-2233-4455",
            radio1_mac="0011-2233-4466",
            bssid="0011-2233-4477",
        )
    ]

    report = adapter.shadow_compare_optical_binding(
        [
            {
                "record_type": "ap_side",
                "radio_mac": "0011-2233-4466",
                "bssid": "0011-2233-4477",
                "peer_mac": "0011-2233-4455",
            },
            {
                "record_type": "ap_side",
                "ap_mac": "0011-2233-4455",
                "radio_mac": "0011-2233-4455",
            },
        ],
        candidates,
        ac_uuid="ac-1",
    )

    assert report.unresolved == 1
    assert report.items[0].old_ap_key is None
    warning_text = " ".join(report.items[0].warnings)
    assert "Radio MAC/BSSID 不作为光衰 AP 写入匹配依据" in warning_text
    assert "Peer MAC 不参与光衰 AP 写入匹配" in warning_text
    assert "存在语义混用风险" in " ".join(report.items[1].warnings)


def test_shadow_does_not_mutate_offline_or_switch_no_light_business_results() -> None:
    resources = [
        _fit_ap("ap-1", "AP-01", "0011-2233-4455", state="Run"),
        _fit_ap("ap-2", "AP-02", "0011-2233-4466", state="Offline"),
    ]
    rows = [
        {
            "ap_uuid": "ap-1",
            "ap_name": "AP-01",
            "neighbor_device_name": "SW-01",
            "neighbor_interface": "GigabitEthernet1/0/1",
            "optical_alarm_status": "normal",
        },
        {"ap_uuid": "ap-2", "ap_name": "AP-02", "optical_alarm_status": "no_light"},
    ]
    switch_lookup = {
        ("sw-01", "gigabitethernet1/0/1"): {"rx_power": None, "port_status": "DOWN"},
    }
    classified = enrich_fit_ap_optical_rows(rows, resources, switch_lookup)
    before_shadow = deepcopy(classified)

    report = AcOpticalIdentityAdapter().shadow_compare_optical_binding(classified, resources, ac_uuid="ac-1")

    assert report.total == 2
    assert classified == before_shadow
    assert classified[0]["switch_optical_status"] == "no_light"
    assert classified[0]["optical_alarm_status"] == "normal"
    assert classified[1]["ap_optical_status"] == "offline"
    assert classified[1]["data_source"] == "historical"


def test_optical_job_load_collect_single_adds_shadow_without_changing_result_fields(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    snapshot = AcOpticalSnapshot(
        "ac-1",
        {"total_aps": 1},
        [_fit_ap("ap-1", "AP-01", "0011-2233-4455")],
        [{"ap_uuid": "ap-1", "ap_name": "AP-01", "optical_alarm_status": "normal"}],
    )
    calls: list[str] = []

    class FakeOpticalService:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def load_optical_snapshot(self, *_args, **_kwargs):
            calls.append("load")
            return snapshot

        def refresh_fit_ap_optical(self, request, **_kwargs):
            calls.append("collect")
            return AcOpticalRefreshResult(
                True,
                False,
                "cli",
                request.refresh_scope,
                snapshot,
                optical_rows_updated=1,
            )

        def refresh_single_ap_optical(self, request, **_kwargs):
            calls.append("single")
            return AcOpticalRefreshResult(
                True,
                False,
                "cli",
                request.refresh_scope,
                snapshot,
                optical_rows_updated=1,
            )

    monkeypatch.setattr(ac_jobs, "AcOpticalService", FakeOpticalService)

    class FakeIdentityService:
        def __init__(self, _database) -> None:
            pass

        @staticmethod
        def rebuild_index(_reason: str) -> None:
            pass

    monkeypatch.setattr(ac_jobs, "ApIdentityQueryService", FakeIdentityService)
    base = {
        "device_uuid": "ac-1",
        "site_name": "demo",
        "db_path": str(tmp_path / "site.db"),
        "data_root": str(tmp_path),
    }
    load = run_job(BackgroundJob("load", "ac_fit_ap_optical_refresh", base))
    collect = run_job(BackgroundJob("collect", "ac_fit_ap_optical_refresh", {**base, "mode": "collect"}))
    single = run_job(
        BackgroundJob(
            "single",
            "ac_fit_ap_optical_refresh",
            {**base, "mode": "collect", "refresh_scope": "single", "ap_uuid": "ap-1"},
        )
    )

    assert load.ok is True
    assert load.result["ac_uuid"] == "ac-1"
    assert load.result["summary"] == {"total_aps": 1}
    assert load.result["resource_count"] == 1
    assert load.result["optical_row_count"] == 1
    assert "resources" not in load.result
    assert "optical_rows" not in load.result
    assert load.result["identity_shadow"]["matched"] == 1
    assert load.result["identity_shadow"]["items"] == []
    assert load.result["identity_shadow"]["items_omitted"] == 1
    assert len(json.dumps(load.to_event(), ensure_ascii=False).encode("utf-8")) < 64 * 1024

    for result in (collect, single):
        assert result.ok is True
        assert result.result["ac_uuid"] == "ac-1"
        assert result.result["data_persisted"] is True
        assert result.result["reload_required"] is True
        assert "summary" not in result.result
        assert "resources" not in result.result
        assert "optical_rows" not in result.result
        assert result.result["identity_shadow"]["available"] is True
        assert result.result["identity_shadow"]["matched"] == 1
        assert result.result["identity_shadow"]["items"] == []
        assert result.result["identity_shadow"]["items_omitted"] == 1
    assert calls == ["load", "collect", "single"]


def test_shadow_failure_is_non_blocking_and_removing_field_restores_original_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = {
        "ac_uuid": "ac-1",
        "summary": {"total_aps": 1},
        "resources": [_fit_ap("ap-1", "AP-01", "0011-2233-4455")],
        "optical_rows": [{"ap_uuid": "ap-1", "optical_alarm_status": "normal"}],
    }

    class BrokenAdapter:
        def shadow_compare_optical_binding(self, *_args, **_kwargs):
            raise RuntimeError("诊断失败")

    monkeypatch.setattr(ac_jobs, "AcOpticalIdentityAdapter", BrokenAdapter)
    result = ac_jobs._append_optical_identity_shadow(original, "ac-1")
    without_shadow = dict(result)
    without_shadow.pop("identity_shadow")

    assert result["identity_shadow"]["available"] is False
    assert "诊断失败" in result["identity_shadow"]["warnings"][0]
    assert without_shadow == original
    assert "identity_shadow" not in original


def test_optical_identity_adapter_static_boundaries() -> None:
    source = Path("src/netconsole/services/ac/ac_optical_identity_adapter.py").read_text(encoding="utf-8")

    assert "PySide6" not in source
    assert "netconsole.ui" not in source
    assert "repositories" not in source
    assert "Database" not in source
    assert "collect_h3c" not in source
