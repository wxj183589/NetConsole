"""轨旁AP业务 ViewModel — joins interface data with FIT-AP state results.

Rules
~~~~~
* ``switch_status``  →  computed real-time from raw switch rx/port data
* ``ap_alarm``       →  computed real-time from raw AP rx data

This ViewModel never reads cached status fields.
"""
from __future__ import annotations

from netconsole.core.state_engine import compute_state, StateResult


class TracksideViewModel:
    """ViewModel for 轨旁AP业务 (trackside AP business) tab."""

    def __init__(
        self,
        switch_data_lookup: dict | None = None,
    ) -> None:
        self._lookup = switch_data_lookup

    def populate_row(
        self,
        trackside_row: dict[str, object | None],
        fit_ap_row: dict[str, object | None] | None,
    ) -> StateResult:
        """Populate a trackside row with state-engine results.

        Computes all statuses real-time from raw data.
        """
        result = compute_state({
            "switch_device_name": trackside_row.get("device_name"),
            "switch_interface_name": trackside_row.get("interface_name"),
            "switch_data_lookup": self._lookup,
            "fit_ap_row": fit_ap_row,
        })

        trackside_row["switch_optical_status"] = result.switch_status
        trackside_row["optical_alarm_status"] = result.ap_status
        trackside_row["optical_status"] = result.optical_status
        trackside_row["_state_color"] = result.color

        return result
