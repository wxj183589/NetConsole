from __future__ import annotations

import pytest

from netconsole.ui.diagnostics import (
    DIAGNOSTICS_ENABLED_FLAG,
    DIAGNOSTICS_SAMPLES_ENABLED_FLAG,
    DIAGNOSTICS_UI_ENABLED_FLAG,
    DiagnosticsSummaryViewModel,
)


def _enabled_settings(*, samples: bool = False) -> dict[str, bool]:
    return {
        DIAGNOSTICS_ENABLED_FLAG: True,
        DIAGNOSTICS_UI_ENABLED_FLAG: True,
        DIAGNOSTICS_SAMPLES_ENABLED_FLAG: samples,
    }


@pytest.mark.parametrize(
    "settings",
    [
        None,
        {},
        {DIAGNOSTICS_ENABLED_FLAG: False, DIAGNOSTICS_UI_ENABLED_FLAG: True},
        {DIAGNOSTICS_ENABLED_FLAG: True, DIAGNOSTICS_UI_ENABLED_FLAG: False},
    ],
)
def test_diagnostics_summary_is_disabled_by_default(settings) -> None:
    model = DiagnosticsSummaryViewModel.from_job_result(
        {"identity_shadow": {"available": True, "total": 1, "matched": 1}},
        settings,
    )

    assert model.is_enabled is False
    assert model.status == "disabled"
    assert model.metrics == ()


def test_diagnostics_summary_reports_not_collected_without_supported_payload() -> None:
    model = DiagnosticsSummaryViewModel.from_job_result(
        {"business_result": "unchanged"},
        _enabled_settings(),
    )

    assert model.status == "not_collected"
    assert model.blocks_takeover is False


def test_diagnostics_summary_extracts_only_allowed_identity_aggregates() -> None:
    result = {
        "identity_shadow": {
            "available": True,
            "total": 20,
            "matched": 15,
            "unresolved": 2,
            "ambiguous": 1,
            "identity_changed": 0,
            "name_only_matches": 2,
            "items": [{"ap_mac": "0011-2233-4455"}],
            "evidence": {"device_name": "列车01-MR-CT"},
            "warnings": ["敏感告警"],
            "database_path": "D:/private/site.sqlite",
            "unknown_counter": 999,
        }
    }

    model = DiagnosticsSummaryViewModel.from_job_result(result, _enabled_settings())

    assert model.status == "available"
    assert model.source == "identity_shadow"
    assert model.total == 20
    assert model.metrics_by_key["matched"].percentage == 75.0
    assert model.metrics_by_key["unresolved"].percentage == 10.0
    assert set(model.metrics_by_key) == {
        "total",
        "matched",
        "unresolved",
        "ambiguous",
        "identity_changed",
        "name_only_matches",
    }
    model_text = repr(model)
    assert "0011-2233-4455" not in model_text
    assert "列车01-MR-CT" not in model_text
    assert "site.sqlite" not in model_text
    assert "敏感告警" not in model_text


def test_diagnostics_summary_supports_detail_shadow() -> None:
    model = DiagnosticsSummaryViewModel.from_job_result(
        {
            "detail_identity_shadow": {
                "schema_version": 1,
                "available": True,
                "total": 4,
                "matched": 4,
            }
        },
        _enabled_settings(),
    )

    assert model.status == "available"
    assert model.source == "detail_identity_shadow"
    assert model.title == "AP Identity 详情诊断摘要"
    assert model.risk_level == "low"


def test_diagnostics_summary_normalizes_export_aggregate_aliases() -> None:
    model = DiagnosticsSummaryViewModel.from_job_result(
        {
            "export_identity_diagnostics": {
                "available": True,
                "total_rows": 100,
                "duplicate_peer_radio_mac_rows": 3,
                "peer_mac_equals_peer_radio_mac_rows": 4,
                "peer_mac_equals_ap_mac_rows": 5,
                "radio_or_bssid_only_rows": 6,
                "ap_name_mac_like_rows": 7,
                "missing_min_rssi_rows": 8,
                "missing_backup_link_rows": 9,
                "missing_ap_mac_rows": 10,
            }
        },
        _enabled_settings(),
    )

    metrics = model.metrics_by_key
    assert model.status == "available"
    assert model.total == 100
    assert metrics["duplicate_mac_field_records"].count == 3
    assert metrics["peer_mac_equals_peer_radio_mac"].count == 4
    assert metrics["peer_mac_equals_ap_mac"].count == 5
    assert metrics["radio_or_bssid_only_records"].count == 6
    assert metrics["mac_like_names"].count == 7
    assert metrics["missing_min_rssi_rows"].count == 8
    assert metrics["missing_backup_link_rows"].count == 9
    assert "missing_ap_mac_rows" not in metrics


def test_samples_flag_does_not_expose_samples() -> None:
    model = DiagnosticsSummaryViewModel.from_job_result(
        {
            "identity_shadow": {
                "available": True,
                "total": 1,
                "matched": 1,
                "samples": [{"record_ref": "secret-ref"}],
            }
        },
        _enabled_settings(samples=True),
    )

    assert model.status == "available"
    assert "secret-ref" not in repr(model)
    assert set(model.metrics_by_key) == {"total", "matched"}


@pytest.mark.parametrize(
    ("payload", "risk_level", "blocks_takeover", "action_fragment"),
    [
        ({"identity_changed": 1}, "critical", True, "identity_changed"),
        ({"ambiguous": 1}, "high", True, "歧义"),
        ({"duplicate_mac_field_records": 1}, "high", True, "重复字段"),
        ({"unresolved": 1}, "medium", True, "只读观测"),
        ({"missing_ac_scope": 1}, "medium", True, "作用域"),
        ({"matched": 1}, "low", False, "不改变"),
    ],
)
def test_diagnostics_summary_assigns_conservative_risk(
    payload,
    risk_level,
    blocks_takeover,
    action_fragment,
) -> None:
    model = DiagnosticsSummaryViewModel.from_job_result(
        {"identity_shadow": {"available": True, "total": 10, **payload}},
        _enabled_settings(),
    )

    assert model.risk_level == risk_level
    assert model.blocks_takeover is blocks_takeover
    assert action_fragment in model.recommended_action


@pytest.mark.parametrize(
    ("payload", "status"),
    [
        ({"available": False, "total": 10}, "unavailable"),
        ({"available": True, "matched": 3}, "insufficient_fields"),
        ({"available": True, "samples": [{"record_ref": "secret"}]}, "redacted"),
        ({"schema_version": 2, "available": True, "total": 1}, "not_supported"),
    ],
)
def test_diagnostics_summary_uses_safe_unavailable_states(payload, status) -> None:
    model = DiagnosticsSummaryViewModel.from_job_result(
        {"identity_shadow": payload},
        _enabled_settings(),
    )

    assert model.status == status
    assert model.risk_level == "none"
    assert model.blocks_takeover is False


def test_diagnostics_summary_redacts_sequence_payload() -> None:
    model = DiagnosticsSummaryViewModel.from_job_result(
        {"identity_shadow": [{"ap_mac": "0011-2233-4455"}]},
        _enabled_settings(),
    )

    assert model.status == "redacted"
    assert model.metrics == ()


def test_diagnostics_summary_failure_does_not_escape_or_change_business_result() -> None:
    class ExplodingMapping(dict):
        def __contains__(self, key) -> bool:
            raise RuntimeError("diagnostics failure")

    business_result = {"status": "finished", "rows": 7}
    result = {
        **business_result,
        "identity_shadow": ExplodingMapping(available=True, total=7),
    }

    model = DiagnosticsSummaryViewModel.from_job_result(result, _enabled_settings())

    assert model.status == "failed"
    assert model.blocks_takeover is False
    assert result["status"] == "finished"
    assert result["rows"] == 7
