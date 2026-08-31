from __future__ import annotations

from netconsole.services.trackside_ap_business import (
    TRACKSIDE_AP_UNIDENTIFIED_REASON_CODES,
    build_trackside_ap_business_statistics,
    classify_trackside_ap_port_reason,
    classify_trackside_ap_port_rows,
)


def _port(**overrides: object) -> dict[str, object | None]:
    row: dict[str, object | None] = {
        "identity_match_status": "unresolved",
        "ap_identity_entity_id": "",
        "has_current_lldp": False,
        "has_historical_lldp": False,
        "has_fit_ap_resource": False,
        "is_ap_offline": False,
        "lldp_match_status": "NO_NEIGHBOR",
        "lldp_history_status": "no_current_evidence",
        "runtime_snapshot_status": "current",
        "pvid_plan_status": "unresolved",
        "link_status": "DOWN",
    }
    row.update(overrides)
    return row


def _identified(entity_id: str) -> dict[str, object | None]:
    return _port(
        identity_match_status="matched",
        ap_identity_entity_id=entity_id,
        has_current_lldp=True,
        pvid_plan_status="matched",
    )


def test_statistics_distinguish_configured_ports_from_planned_and_physical_aps() -> None:
    rows = [_identified(f"ac:ap-{index}") for index in range(6)] + [_port() for _ in range(4)]

    statistics = build_trackside_ap_business_statistics(rows, planned_ap_total=7)

    assert statistics.configured_ap_port_total == 10
    assert statistics.planned_ap_total == 7
    assert statistics.identified_ap_port_total == 6
    assert statistics.unidentified_ap_port_total == 4
    assert statistics.physical_ap_total == 6
    assert sum(statistics.unidentified_reason_counts.values()) == 4
    assert statistics.unidentified_reason_counts["EMPTY_CONFIGURED_PORT"] == 4


def test_physical_ap_count_deduplicates_multiple_identified_port_rows() -> None:
    statistics = build_trackside_ap_business_statistics(
        [_identified("ac:ap-1"), _identified("ac:ap-1")]
    )

    assert statistics.identified_ap_port_total == 2
    assert statistics.physical_ap_total == 1


def test_unidentified_port_reasons_have_one_primary_reason() -> None:
    cases = {
        "EMPTY_CONFIGURED_PORT": _port(),
        "AP_OFFLINE_NO_IDENTITY": _port(
            ap_mac="0011-2233-4455",
            has_fit_ap_resource=True,
            is_ap_offline=True,
        ),
        "FIT_AP_NOT_MATCHED": _port(
            ap_mac="0011-2233-4455",
            has_current_lldp=True,
            pvid_plan_status="matched",
            fit_ap_match_status="unmatched",
        ),
        "LLDP_MISSING": _port(
            ap_uuid="ap-1",
            has_fit_ap_resource=True,
        ),
        "LLDP_STALE": _port(
            ap_mac="0011-2233-4455",
            has_current_lldp=True,
            lldp_match_status="LLDP_SNAPSHOT_STALE",
            pvid_plan_status="matched",
        ),
        "PLANNING_NOT_MATCHED": _port(
            ap_mac="0011-2233-4455",
            has_current_lldp=True,
            pvid_plan_status="unresolved",
        ),
        "IDENTITY_INSUFFICIENT": _port(
            ap_mac="0011-2233-4455",
            identity_match_status="ambiguous",
            has_current_lldp=True,
            pvid_plan_status="matched",
        ),
    }

    for expected, row in cases.items():
        assert classify_trackside_ap_port_reason(row) == ("unidentified", expected)

def test_ambiguous_identity_is_not_bound_and_statistics_are_partitioned() -> None:
    ambiguous = _port(
        identity_match_status="ambiguous",
        ap_mac="0011-2233-4455",
        has_current_lldp=True,
        pvid_plan_status="matched",
    )
    rows = classify_trackside_ap_port_rows([ambiguous])
    statistics = build_trackside_ap_business_statistics(rows)

    assert rows[0]["identity_match_status"] == "ambiguous"
    assert rows[0]["ap_identity_entity_id"] == ""
    assert rows[0]["primary_reason_code"] == "IDENTITY_INSUFFICIENT"
    assert statistics.unidentified_ap_port_total == 1
    assert sum(statistics.unidentified_reason_counts[code] for code in TRACKSIDE_AP_UNIDENTIFIED_REASON_CODES) == 1
