"""Switch-side optical status source — computes real-time from raw data.

This module NEVER reads cached ``status`` or ``switch_optical_status`` fields.
It always delegates to ``compute_optical_severity()`` using raw rx_power /
port_status from the optical module row.
"""
from __future__ import annotations

from netconsole.core.optical_severity_engine import compute_optical_severity
from netconsole.utils.interface_normalize import normalize_interface_name


def build_switch_data_lookup(
    devices,
    optical_by_device: dict[str, list[dict[str, object | None]]],
) -> dict[tuple[str, str], dict[str, object | None]]:
    """Build a lookup: ``(device_name_lower, interface_name_lower) -> optical_module_row``.

    Returns the **raw** optical module row (not a cached status).
    Both ``device.name`` and ``device.system_name`` are indexed.
    """
    lookup: dict[tuple[str, str], dict[str, object | None]] = {}
    device_names_by_uuid: dict[str, set[str]] = {}

    for device in devices:
        names: set[str] = set()
        for raw in (device.name, device.system_name):
            normalized = str(raw or "").strip().casefold()
            if normalized:
                names.add(normalized)
        device_names_by_uuid[str(device.device_uuid or "")] = names

    for device_uuid, optical_modules in optical_by_device.items():
        names = device_names_by_uuid.get(device_uuid, set())
        for module in optical_modules:
            interface = normalize_interface_name(module.get("interface_name")).casefold()
            if interface:
                for name in names:
                    lookup[(name, interface)] = module

    return lookup


def compute_switch_status(
    *,
    device_name: object = None,
    interface_name: object = None,
    switch_rx_power: object = None,
    switch_port_status: object = None,
    alarm_low: object = None,
    alarm_high: object = None,
    warning_low: object = None,
    module_present: object = None,
    no_module: object = None,
    module_status: object = None,
    lookup: dict[tuple[str, str], dict[str, object | None]] | None = None,
) -> str:
    """Compute switch-side optical status real-time from raw data.

    If raw fields are provided directly, computes immediately.
    If a ``lookup`` is given, resolves the raw optical module row and
    computes from its ``rx_power`` field.
    """
    # Direct raw data path
    if switch_rx_power is not None or switch_port_status is not None or not lookup:
        return compute_optical_severity(
            {
                "switch_rx_power": switch_rx_power,
                "switch_port_status": switch_port_status,
                "alarm_low": alarm_low,
                "alarm_high": alarm_high,
                "warning_low": warning_low,
                "module_present": module_present,
                "no_module": no_module,
                "module_status": module_status,
                "device_type": "switch",
            }
        ).severity

    # Lookup path: find raw optical module row
    if lookup:
        name = str(device_name or "").strip().casefold()
        interface = normalize_interface_name(interface_name).casefold()
        if name and interface:
            module = lookup.get((name, interface))
            if module:
                return compute_optical_severity(
                    {
                        "switch_rx_power": module.get("rx_power"),
                        "switch_port_status": module.get("port_status"),
                        "alarm_low": module.get("rx_low_alarm"),
                        "alarm_high": module.get("rx_high_alarm"),
                        "warning_low": module.get("rx_low_warning"),
                        "module_present": module.get("module_present") if "module_present" in module else module.get("has_module"),
                        "no_module": module.get("no_module"),
                        "module_status": module.get("module_status") or module.get("status"),
                        "device_type": "switch",
                    }
                ).severity

    return "unknown"
