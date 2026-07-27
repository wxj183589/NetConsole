from __future__ import annotations

from netconsole.models.device import Device
from netconsole.services.trackside_ap_business import (
    build_trackside_ap_business_rows,
    trackside_row_status,
)


def _switch() -> Device:
    return Device(
        name="ZTE-TRACKSIDE-01",
        system_name="ZTE-TRACKSIDE-01",
        station="Station A",
        device_uuid="sw-zte-1",
        device_vendor="ZTE",
        device_type="SW",
    )


def _h3c_switch() -> Device:
    return Device(
        name="H3C-TRACKSIDE-01",
        system_name="H3C-TRACKSIDE-01",
        station="Station A",
        device_uuid="sw-zte-1",
        device_vendor="H3C",
        device_type="SW",
    )


def _interfaces() -> dict[str, list[dict[str, object | None]]]:
    return {
        "sw-zte-1": [
            {
                "interface_name": "xgei-0/1/1/2",
                "description": "Trackside AP",
                "link_status": "UP",
                "protocol_status": "UP",
                "updated_at": "2026-07-28T10:00:00+08:00",
            }
        ]
    }


def _optical(
    *,
    status: str = "unverified",
    collected_at: str = "2026-07-28T10:00:00+08:00",
) -> dict[str, list[dict[str, object | None]]]:
    return {
        "sw-zte-1": [
            {
                "interface_name": "xgei-0/1/1/2",
                "rx_power": -11.9,
                "tx_power": -2.8,
                "rx_low_alarm": -11.1,
                "rx_high_alarm": 0.5,
                "tx_low_alarm": -7.3,
                "tx_high_alarm": -1.0,
                "status": status,
                "collected_at": collected_at,
            }
        ]
    }


def _resource(
    ap_uuid: str,
    ap_name: str,
    ap_mac: str,
    ap_ip: str,
) -> dict[str, object | None]:
    return {
        "ac_device_uuid": "ac-1",
        "ap_uuid": ap_uuid,
        "ap_name": ap_name,
        "ap_mac": ap_mac,
        "ap_ip": ap_ip,
    }


def _remote_dom(
    ap_uuid: str,
    ap_name: str,
    ap_mac: str,
    *,
    collected_at: str = "2026-07-28T10:05:00+08:00",
) -> dict[str, object | None]:
    return {
        "ac_device_uuid": "ac-1",
        "ap_uuid": ap_uuid,
        "ap_name": ap_name,
        "ap_mac": ap_mac,
        "rx_power": -8.4,
        "tx_power": -3.1,
        "rx_low_alarm": -19.0,
        "rx_low_warning": -17.0,
        "collected_at": collected_at,
    }


def test_trackside_lldp_match_prefers_management_ip_over_mac() -> None:
    ap_by_ip = _resource("ap-ip", "AP-IP", "0011-2233-4455", "10.10.1.10")
    ap_by_mac = _resource("ap-mac", "AP-MAC", "0011-2233-4466", "10.10.1.11")

    rows = build_trackside_ap_business_rows(
        [_switch()],
        _interfaces(),
        _optical(),
        [
            _remote_dom("ap-ip", "AP-IP", "0011-2233-4455"),
            _remote_dom("ap-mac", "AP-MAC", "0011-2233-4466"),
        ],
        {
            "sw-zte-1": [
                {
                    "local_interface": "xgei-0/1/1/2",
                    "neighbor_ip": "10.10.1.10",
                    "neighbor_mac": "0011-2233-4466",
                }
            ]
        },
        [ap_by_ip, ap_by_mac],
    )

    assert rows[0]["ap_uuid"] == "ap-ip"
    assert rows[0]["ap_match_source"] == "LLDP_IP"
    assert rows[0]["ap_match_confidence"] == 96
    assert rows[0]["lldp_match_status"] == "MATCHED"


def test_trackside_lldp_name_requires_one_exact_candidate() -> None:
    resources = [
        _resource("ap-1", "DUPLICATE-AP", "0011-2233-4455", "10.10.1.10"),
        _resource("ap-2", "DUPLICATE-AP", "0011-2233-4466", "10.10.1.11"),
    ]

    rows = build_trackside_ap_business_rows(
        [_switch()],
        _interfaces(),
        _optical(),
        [],
        {
            "sw-zte-1": [
                {
                    "local_interface": "xgei-0/1/1/2",
                    "neighbor_sysname": "DUPLICATE-AP",
                }
            ]
        },
        resources,
    )

    assert rows[0]["lldp_match_status"] == "AMBIGUOUS"
    assert rows[0]["ap_match_source"] == "LLDP_SYSTEM_NAME"
    assert rows[0]["ap_uuid"] is None
    assert rows[0]["calculation_status"] == "NOT_VERIFIED"
    assert rows[0]["calculation_reason"] == "REAL_DEVICE_SAMPLE_REQUIRED"


def test_ambiguous_current_lldp_does_not_rebind_through_legacy_interface_fallback() -> None:
    resources = [
        _resource("ap-1", "DUPLICATE-AP", "0011-2233-4455", "10.10.1.10"),
        _resource("ap-2", "DUPLICATE-AP", "0011-2233-4466", "10.10.1.11"),
    ]
    optical_rows = [
        {
            **_optical()["sw-zte-1"][0],
            "ap_uuid": "ap-legacy",
            "ap_name": "LEGACY-AP",
            "neighbor_device_name": "ZTE-TRACKSIDE-01",
            "neighbor_interface": "xgei-0/1/1/2",
        }
    ]

    row = build_trackside_ap_business_rows(
        [_switch()],
        _interfaces(),
        _optical(),
        optical_rows,
        lldp_by_device={
            "sw-zte-1": [
                {
                    "local_interface": "xgei-0/1/1/2",
                    "neighbor_sysname": "DUPLICATE-AP",
                }
            ]
        },
        fit_ap_resource_rows=resources,
        historical_lldp_rows=[
            {
                "switch_name": "ZTE-TRACKSIDE-01",
                "interface_name": "xgei-0/1/1/2",
                "ap_uuid": "ap-historical",
                "ap_name": "HISTORICAL-AP",
                "ap_mac": "0011-2233-4477",
            }
        ],
    )[0]

    assert row["lldp_match_status"] == "AMBIGUOUS"
    assert row["ap_uuid"] is None
    assert row["ap_name"] is None
    assert row["ap_mac"] == ""
    assert row["has_fit_ap_resource"] is False
    assert row["calculation_status"] == "NOT_VERIFIED"
    assert row["calculation_reason"] == "REAL_DEVICE_SAMPLE_REQUIRED"


def test_zte_trackside_keeps_bidirectional_loss_not_verified() -> None:
    resource = _resource("ap-1", "AP-01", "0011-2233-4455", "10.10.1.10")

    rows = build_trackside_ap_business_rows(
        [_switch()],
        _interfaces(),
        _optical(status="unverified"),
        [_remote_dom("ap-1", "AP-01", "0011-2233-4455")],
        {
            "sw-zte-1": [
                {
                    "local_interface": "xgei-0/1/1/2",
                    "neighbor_mac": "00:11:22:33:44:55",
                }
            ]
        },
        [resource],
    )

    row = rows[0]
    assert row["switch_vendor"] == "ZTE"
    assert row["switch_optical_status"] == "unverified"
    assert row["calculation_status"] == "NOT_VERIFIED"
    assert row["calculation_reason"] == "REAL_DEVICE_SAMPLE_REQUIRED"
    assert row["forward_loss_db"] is None
    assert row["reverse_loss_db"] is None
    assert row["sample_time_delta_seconds"] is None


def test_zte_trackside_never_calculates_from_stale_or_single_ended_samples() -> None:
    resource = _resource("ap-1", "AP-01", "0011-2233-4455", "10.10.1.10")
    lldp = {
        "sw-zte-1": [
            {
                "local_interface": "xgei-0/1/1/2",
                "neighbor_mac": "00:11:22:33:44:55",
            }
        ]
    }

    stale = build_trackside_ap_business_rows(
        [_switch()],
        _interfaces(),
        _optical(),
        [
            _remote_dom(
                "ap-1",
                "AP-01",
                "0011-2233-4455",
                collected_at="2026-07-28T11:00:01+08:00",
            )
        ],
        lldp,
        [resource],
    )[0]
    single_ended = build_trackside_ap_business_rows(
        [_switch()],
        _interfaces(),
        _optical(),
        [],
        lldp,
        [resource],
    )[0]

    assert stale["calculation_status"] == "NOT_VERIFIED"
    assert stale["calculation_reason"] == "REAL_DEVICE_SAMPLE_REQUIRED"
    assert stale["forward_loss_db"] is None
    assert single_ended["calculation_status"] == "NOT_VERIFIED"
    assert single_ended["calculation_reason"] == "REAL_DEVICE_SAMPLE_REQUIRED"
    assert single_ended["forward_loss_db"] is None


def test_h3c_trackside_keeps_existing_bidirectional_loss_calculation() -> None:
    resource = _resource("ap-1", "AP-01", "0011-2233-4455", "10.10.1.10")
    row = build_trackside_ap_business_rows(
        [_h3c_switch()],
        _interfaces(),
        _optical(status="normal"),
        [_remote_dom("ap-1", "AP-01", "0011-2233-4455")],
        {
            "sw-zte-1": [
                {
                    "local_interface": "xgei-0/1/1/2",
                    "neighbor_mac": "00:11:22:33:44:55",
                }
            ]
        },
        [resource],
    )[0]

    assert row["switch_vendor"] == "H3C"
    assert row["calculation_status"] == "CALCULATED"
    assert row["forward_loss_db"] == 5.6
    assert row["reverse_loss_db"] == 8.8
    assert row["sample_time_delta_seconds"] == 300


def test_trackside_preserves_zte_abnormal_and_dom_unavailable_statuses() -> None:
    abnormal = build_trackside_ap_business_rows(
        [_switch()],
        _interfaces(),
        _optical(status="abnormal"),
        [],
    )[0]
    dom_unavailable = build_trackside_ap_business_rows(
        [_switch()],
        _interfaces(),
        _optical(status="dom_unavailable"),
        [],
    )[0]

    assert abnormal["switch_optical_status"] == "abnormal"
    assert trackside_row_status(abnormal) == "abnormal"
    assert dom_unavailable["switch_optical_status"] == "dom_unavailable"
    assert dom_unavailable["lldp_match_status"] == "SAMPLE_REQUIRED"
