"""设备详情 ViewModel — computes switch status real-time from raw data.

The device detail page provides raw switch optical module data.
Status is computed real-time via ``compute_switch_status``.
"""
from __future__ import annotations

from netconsole.core.sources.switch_source import compute_switch_status
from netconsole.core.state_engine import STATUS_COLORS


class DeviceDetailViewModel:
    """ViewModel for 设备详情 (device detail) dialog."""

    def __init__(
        self,
        switch_data_lookup: dict | None = None,
    ) -> None:
        self._lookup = switch_data_lookup

    def get_color(
        self,
        *,
        device_name: object = None,
        interface_name: object = None,
        rx_power: object = None,
        port_status: object = None,
    ) -> str:
        """Return the display colour (hex, no '#') for one optical module."""
        status = compute_switch_status(
            device_name=device_name,
            interface_name=interface_name,
            switch_rx_power=rx_power,
            switch_port_status=port_status,
            lookup=self._lookup,
        )
        return STATUS_COLORS.get(status, STATUS_COLORS["unknown"])
