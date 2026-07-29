from __future__ import annotations

import pytest

from netconsole.core.optical_severity_engine import (
    compute_optical_severity,
    compute_zte_optical_severity,
    normalize_zte_optical_record,
)


@pytest.mark.parametrize(
    ("record", "severity"),
    [
        ({"module_online": False}, "no_module"),
        ({"module_online": True, "rx_power": None}, "no_light"),
        (
            {
                "module_online": True,
                "rx_power": -29.0,
                "rx_low_alarm": -28.2,
                "rx_high_alarm": 0.0,
            },
            "abnormal",
        ),
        (
            {
                "module_online": True,
                "rx_power": -28.2,
                "rx_low_alarm": -28.2,
                "rx_high_alarm": 0.0,
                "tx_power": -5.8,
                "tx_low_alarm": -10.0,
                "tx_high_alarm": -0.5,
                "device_reported_status": "Normal",
            },
            "normal",
        ),
        (
            {
                "module_online": True,
                "rx_power": 0.1,
                "rx_high_alarm": 0.0,
            },
            "abnormal",
        ),
        (
            {
                "module_online": True,
                "rx_power": -15.2,
                "rx_low_alarm": -28.2,
                "rx_high_alarm": 0.0,
                "tx_power": -10.1,
                "tx_low_alarm": -10.0,
                "tx_high_alarm": -0.5,
            },
            "abnormal",
        ),
        (
            {
                "module_online": True,
                "rx_power": -15.2,
                "rx_low_alarm": -28.2,
                "rx_high_alarm": 0.0,
                "tx_power": -0.4,
                "tx_low_alarm": -10.0,
                "tx_high_alarm": -0.5,
            },
            "abnormal",
        ),
        (
            {
                "module_online": True,
                "rx_power": -15.2,
                "device_reported_status": "Normal",
            },
            "normal",
        ),
        (
            {
                "module_online": True,
                "rx_power": -15.2,
                "device_reported_status": "Unknown",
            },
            "no_light",
        ),
        (
            {
                "module_online": True,
                "rx_power": -15.2,
                "rx_low_alarm": -28.2,
                "device_reported_status": "Unknown",
            },
            "no_light",
        ),
        (
            {
                "status": "offline",
                "rx_power": None,
            },
            "no_module",
        ),
    ],
)
def test_zte_severity_uses_native_thresholds_and_strict_boundaries(
    record: dict[str, object], severity: str
) -> None:
    assert compute_zte_optical_severity(record).severity == severity


def test_zte_missing_rx_reason_does_not_reference_global_minus_35() -> None:
    result = compute_zte_optical_severity(
        {"module_online": True, "rx_power": None, "device_reported_status": "Unknown"}
    )

    assert result.reason == "设备未返回接收光功率"
    assert "-35" not in str(result.reason)


def test_zte_reported_abnormal_without_native_thresholds_is_unavailable() -> None:
    result = compute_zte_optical_severity(
        {
            "module_online": True,
            "rx_power": -10.0,
            "tx_power": -5.0,
            "device_reported_status": "Abnormal",
        }
    )

    assert result.severity == "unknown"
    assert result.warning_source == "missing"


def test_zte_no_module_normalization_clears_identity_power_and_thresholds() -> None:
    normalized = normalize_zte_optical_record(
        {
            "interface_name": "gei-0/3/0/1",
            "device_vendor": "ZTE",
            "device_reported_status": "offline",
            "module_model": "STALE",
            "module_serial_number": "STALE-SN",
            "rx_power": -7.2,
            "tx_power": -5.1,
            "rx_low_alarm": -28.2,
        }
    )

    assert normalized["status"] == "no_module"
    assert normalized["module_present"] is False
    assert normalized["module_online"] is False
    for field in (
        "module_model",
        "module_serial_number",
        "rx_power",
        "tx_power",
        "rx_low_alarm",
    ):
        assert normalized[field] is None


def test_h3c_generic_severity_behavior_remains_unchanged() -> None:
    result = compute_optical_severity(
        {"module_present": True, "rx_power": -36.0, "rx_low_alarm": -20.0}
    )

    assert result.severity == "no_light"
    assert result.reason == "RX power is missing or <= -35 dBm"
