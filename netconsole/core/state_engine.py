from __future__ import annotations

from dataclasses import dataclass

from netconsole.core.optical_severity_engine import (
    SEVERITY_RANK,
    STATUS_COLORS,
    compute_optical_severity,
    display_optical_status,
    worse_optical_severity,
)
from netconsole.core.sources.ap_source import compute_ap_status
from netconsole.core.sources.switch_source import compute_switch_status


@dataclass(frozen=True)
class StateResult:
    switch_status: str
    ap_status: str
    optical_status: str
    severity: int
    color: str


def compute_state(context: dict) -> StateResult:
    fit_ap_row = context.get("fit_ap_row") or {}
    has_switch_input = (
        "switch_rx_power" in context
        or "switch_port_status" in context
        or "neighbor_rx_power" in fit_ap_row
        or "switch_port_status" in fit_ap_row
        or bool(context.get("switch_data_lookup"))
        or bool(context.get("switch_device_name") and context.get("switch_interface_name"))
    )
    if has_switch_input:
        switch_status = compute_switch_status(
            device_name=context.get("switch_device_name"),
            interface_name=context.get("switch_interface_name"),
            switch_rx_power=context.get("switch_rx_power") if "switch_rx_power" in context else fit_ap_row.get("neighbor_rx_power"),
            switch_port_status=context.get("switch_port_status") or fit_ap_row.get("switch_port_status"),
            alarm_low=context.get("switch_alarm_low") or fit_ap_row.get("switch_rx_low_alarm") or fit_ap_row.get("neighbor_rx_low_alarm") or fit_ap_row.get("alarm_low_threshold") or fit_ap_row.get("rx_low_alarm"),
            alarm_high=context.get("switch_alarm_high") or fit_ap_row.get("switch_rx_high_alarm") or fit_ap_row.get("neighbor_rx_high_alarm") or fit_ap_row.get("alarm_high_threshold") or fit_ap_row.get("rx_high_alarm"),
            warning_low=context.get("switch_warning_low") or fit_ap_row.get("switch_rx_low_warning") or fit_ap_row.get("neighbor_rx_low_warning") or fit_ap_row.get("warning_low_threshold") or fit_ap_row.get("warning_low") or fit_ap_row.get("rx_low_warning"),
            lookup=context.get("switch_data_lookup"),
        )
    else:
        switch_status = "unknown"
    ap_status = compute_ap_status(fit_ap_row)
    optical_status = worse_optical_severity(switch_status, ap_status)
    return StateResult(
        switch_status=switch_status,
        ap_status=ap_status,
        optical_status=optical_status,
        severity=SEVERITY_RANK.get(optical_status, 0),
        color=STATUS_COLORS.get(optical_status, STATUS_COLORS["unknown"]),
    )


__all__ = [
    "STATUS_COLORS",
    "StateResult",
    "compute_optical_severity",
    "compute_state",
    "display_optical_status",
]
