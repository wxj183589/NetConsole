"""AP-side optical status source — computes real-time from raw data.

This module NEVER reads cached ``optical_alarm_status`` fields.
It always delegates to ``compute_optical_severity()`` using raw AP
rx_power / port_status.
"""
from __future__ import annotations

from netconsole.core.optical_severity_engine import compute_optical_severity


def compute_ap_status(
    fit_ap_row: dict[str, object | None] | None,
) -> str:
    """Compute AP-side optical alarm status real-time from raw data.

    Uses ``rx_power``, ``rx_low_alarm``, ``rx_low_warning``, ``rx_high_alarm``,
    and ``ap_port_status`` from *fit_ap_row*.
    """
    if fit_ap_row is None:
        return "unknown"

    return compute_optical_severity(
        {
            "ap_rx_power": fit_ap_row.get("rx_power"),
            "ap_port_status": fit_ap_row.get("ap_port_status"),
            "module_present": fit_ap_row.get("module_present") if "module_present" in fit_ap_row else fit_ap_row.get("has_module"),
            "no_module": fit_ap_row.get("no_module"),
            "module_status": fit_ap_row.get("module_status"),
            "transceiver_status": fit_ap_row.get("transceiver_status"),
            "optical_alarm_status": fit_ap_row.get("optical_alarm_status"),
            "status": fit_ap_row.get("status"),
            "alarm_low": fit_ap_row.get("rx_low_alarm"),
            "alarm_high": fit_ap_row.get("rx_high_alarm"),
            "warning_low": fit_ap_row.get("rx_low_warning"),
            "device_type": "ap",
        }
    ).severity
