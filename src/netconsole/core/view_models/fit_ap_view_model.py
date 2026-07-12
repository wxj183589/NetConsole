"""FIT-AP光衰 ViewModel — populates rows from state_engine results.

This ViewModel **only maps data** — it never computes status thresholds.
All status values come from :func:`compute_state` which computes real-time
from raw rx/tx/port data.
"""
from __future__ import annotations

from netconsole.core.state_engine import compute_state, StateResult


class FITAPViewModel:
    """ViewModel for FIT-AP光衰 (FIT-AP optical attenuation) tab."""

    def __init__(
        self,
        switch_data_lookup: dict | None = None,
    ) -> None:
        self._lookup = switch_data_lookup

    def populate_row(self, row: dict[str, object | None]) -> StateResult:
        """Populate a FIT-AP optical row with state-engine results.

        Computes switch_status and ap_status real-time from raw data in *row*.
        Mutates *row* with ``switch_optical_status``, ``optical_alarm_status``,
        and ``_state_color``.
        """
        result = compute_state({
            "switch_device_name": row.get("neighbor_device_name") or row.get("device_name"),
            "switch_interface_name": row.get("neighbor_interface") or row.get("local_interface"),
            "switch_data_lookup": self._lookup,
            "fit_ap_row": row,
        })

        row["switch_optical_status"] = result.switch_status
        row["optical_alarm_status"] = result.ap_status
        row["_state_color"] = result.color

        return result
