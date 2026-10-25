"""AP-side optical status source — computes real-time from raw data.

This module NEVER reads cached ``optical_alarm_status`` fields.
It always delegates to ``compute_optical_severity()`` using raw AP
rx_power / port_status.
"""
from __future__ import annotations

from datetime import datetime

from netconsole.core.ap_optical_capability import (
    OPTICAL_NOT_APPLICABLE_STATUS,
    is_ap_optical_applicable,
)
from netconsole.core.optical_rx_threshold import (
    OPTICAL_BUSINESS_RX_MIN_DBM,
    parse_optical_rx_dbm,
)
from netconsole.core.optical_severity_engine import (
    classify_optical_freshness,
    compute_optical_severity,
)

AP_BUSINESS_RX_MIN_DBM = OPTICAL_BUSINESS_RX_MIN_DBM

_AP_OPTICAL_FAILURE_STATUSES = frozenset(
    {
        "failed",
        "failure",
        "error",
        "cancelled",
        "timeout",
        "auth_failed",
        "authentication_failed",
        "tcp_failed",
        "tcp_connection_failed",
        "ssh_failed",
        "connection_failed",
        "unreachable",
        "device_unreachable",
        "collection_failed",
        "parse_failed",
    }
)

# ``replace_fit_ap_optical`` deliberately retains the previous valid payload
# when a later collection fails.  Those fields are useful for history, but
# must not be consumed as the current AP-side optical fact.
_AP_OPTICAL_CURRENT_VALUE_FIELDS = (
    "rx_power",
    "tx_power",
    "temperature",
    "voltage",
    "bias_current",
    "rx_low_alarm",
    "rx_low_warning",
    "rx_high_alarm",
    "rx_high_warning",
    "tx_low_alarm",
    "tx_low_warning",
    "tx_high_alarm",
    "tx_high_warning",
    "module_model",
    "module_serial_number",
    "module_vendor",
    "wavelength",
    "transmission_distance",
    "connector_type",
    "module_present",
    "has_module",
    "no_module",
    "module_status",
    "transceiver_status",
    "optical_alarm_status",
)


def project_current_ap_optical_row(
    fit_ap_row: dict[str, object | None] | None,
    *,
    now: datetime | None = None,
) -> dict[str, object | None] | None:
    """Project persisted FIT-AP data into a current optical fact.

    The repository may retain the last valid Rx/Tx values on a failed
    collection.  Keep that persistence behavior for history, while clearing
    those retained values from the current projection.  Rows without an
    explicit collection status retain legacy fixture semantics.
    """

    if fit_ap_row is None:
        return None
    projected = dict(fit_ap_row)
    status = str(projected.get("status") or "").strip().casefold()
    if status in _AP_OPTICAL_FAILURE_STATUSES:
        for field in _AP_OPTICAL_CURRENT_VALUE_FIELDS:
            projected[field] = None
        projected["data_freshness"] = "unknown"
        return projected
    if status in {"no_module", "no module", "no-transceiver", "no transceiver"}:
        for field in _AP_OPTICAL_CURRENT_VALUE_FIELDS:
            projected[field] = None
        projected["data_freshness"] = "fresh"
        return projected
    if status == "success":
        freshness = str(projected.get("data_freshness") or "").strip().casefold()
        if freshness not in {"fresh", "stale", "current"}:
            freshness = classify_optical_freshness(
                projected.get("updated_at"),
                projected.get("collected_at"),
                now=now,
            )
        if freshness:
            projected["data_freshness"] = freshness
    return projected


def compute_ap_status(
    fit_ap_row: dict[str, object | None] | None,
) -> str:
    """Compute AP-side optical alarm status real-time from raw data.

    Uses ``rx_power``, ``rx_low_alarm``, ``rx_low_warning``, ``rx_high_alarm``,
    and ``ap_port_status`` from *fit_ap_row*.
    """
    fit_ap_row = project_current_ap_optical_row(fit_ap_row)
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
