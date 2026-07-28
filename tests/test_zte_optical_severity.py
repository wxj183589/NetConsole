from __future__ import annotations

import pytest

from netconsole.core.optical_severity_engine import (
    compute_optical_severity,
    compute_zte_optical_severity,
)


@pytest.mark.parametrize(
    ("record", "severity"),
    [
        ({"module_online": False}, "offline"),
        ({"module_online": True, "rx_power": None}, "no_light"),
        (
            {
                "module_online": True,
                "rx_power": -29.0,
                "rx_low_alarm": -28.2,
                "rx_high_alarm": 0.0,
            },
            "alarm",
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
            "alarm",
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
            "alarm",
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
            "alarm",
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
            "unknown",
        ),
        (
            {
                "module_online": True,
                "rx_power": -15.2,
                "rx_low_alarm": -28.2,
                "device_reported_status": "Unknown",
            },
            "unknown",
        ),
        (
            {
                "status": "offline",
                "rx_power": None,
            },
            "offline",
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

    assert result.reason == "Device did not report RX power; raw value is N/A"
    assert "-35" not in str(result.reason)


def test_h3c_generic_severity_behavior_remains_unchanged() -> None:
    result = compute_optical_severity(
        {"module_present": True, "rx_power": -36.0, "rx_low_alarm": -20.0}
    )

    assert result.severity == "no_light"
    assert result.reason == "RX power is missing or <= -35 dBm"
