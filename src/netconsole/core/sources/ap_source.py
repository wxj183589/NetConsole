"""AP-side optical status source — computes real-time from raw data.

This module NEVER reads cached ``optical_alarm_status`` fields.
It always delegates to ``compute_optical_severity()`` using raw AP
rx_power / port_status.
"""
from __future__ import annotations

from netconsole.core.ap_optical_capability import (
    OPTICAL_NOT_APPLICABLE_STATUS,
    is_ap_optical_applicable,
)
from netconsole.core.optical_rx_threshold import (
    OPTICAL_BUSINESS_RX_MIN_DBM,
    parse_optical_rx_dbm,
)
from netconsole.core.optical_severity_engine import compute_optical_severity

AP_BUSINESS_RX_MIN_DBM = OPTICAL_BUSINESS_RX_MIN_DBM


def compute_ap_status(
    fit_ap_row: dict[str, object | None] | None,
) -> str:
    """Compute AP-side optical alarm status real-time from raw data.

    Uses ``rx_power``, ``rx_low_alarm``, ``rx_low_warning``, ``rx_high_alarm``,
    and ``ap_port_status`` from *fit_ap_row*.
    """
    if fit_ap_row is None:
        return "unknown"

    if not is_ap_optical_applicable(fit_ap_row.get("model")):
        return OPTICAL_NOT_APPLICABLE_STATUS

    severity_result = compute_optical_severity(
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
    )
    result = severity_result.severity
    if result in {"no_module", "link_abnormal", "link_down"}:
        return result
    rx_power = parse_optical_rx_dbm(fit_ap_row.get("rx_power"))
    if rx_power is not None and rx_power < AP_BUSINESS_RX_MIN_DBM:
        return "abnormal"
    reported_status = str(
        fit_ap_row.get("optical_alarm_status")
        or fit_ap_row.get("module_status")
        or fit_ap_row.get("transceiver_status")
        or ""
    ).strip().casefold()
    explicit_status = {
        "no_light": "no_light",
        "no light": "no_light",
        "no-light": "no_light",
        "无光": "no_light",
        "link_abnormal": "link_abnormal",
        "link abnormal": "link_abnormal",
        "link-abnormal": "link_abnormal",
        "链路异常": "link_abnormal",
        "link_down": "link_down",
        "link down": "link_down",
        "link-down": "link_down",
        "链路断开": "link_down",
        "critical": "abnormal",
        "严重告警": "abnormal",
        "alarm": "alarm",
        "warning": "warning",
        "abnormal": "abnormal",
        "功率异常": "abnormal",
    }.get(reported_status)
    if explicit_status:
        return explicit_status
    if rx_power is not None:
        return "normal"
    return (
        "no_light"
        if result == "no_light" and severity_result.rx_power is not None
        else "unknown"
    )
