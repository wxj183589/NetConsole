from __future__ import annotations

import math
from dataclasses import dataclass

from netconsole.models.mesh_series import (
    MESH_METRICS,
    MeshLinkStateValue,
    MeshMetricDefinition,
    MeshUnitSemantics,
    MeshValueKind,
)


@dataclass(frozen=True, slots=True)
class MeshSeriesPresentation:
    label_key: str
    description_key: str
    decimals: int = 0


MESH_SERIES_PRESENTATION: dict[str, MeshSeriesPresentation] = {
    "peer.local_rssi": MeshSeriesPresentation("mesh_analysis.mr_rssi", "mesh_analysis.mr_rssi_description"),
    "peer.peer_rssi": MeshSeriesPresentation("mesh_analysis.peer_rssi_raw", "mesh_analysis.peer_rssi_description"),
    "peer.local_noise": MeshSeriesPresentation("mesh_analysis.local_noise", "mesh_analysis.noise_description"),
    "peer.peer_noise": MeshSeriesPresentation("mesh_analysis.peer_noise", "mesh_analysis.noise_description"),
    "peer.local_tx_busy": MeshSeriesPresentation("mesh_analysis.local_tx_busy", "mesh_analysis.tx_busy_description"),
    "peer.peer_tx_busy": MeshSeriesPresentation("mesh_analysis.peer_tx_busy", "mesh_analysis.tx_busy_description"),
    "peer.local_rx_busy": MeshSeriesPresentation("mesh_analysis.local_rx_busy", "mesh_analysis.rx_busy_description"),
    "peer.peer_rx_busy": MeshSeriesPresentation("mesh_analysis.peer_rx_busy", "mesh_analysis.rx_busy_description"),
    "peer.state": MeshSeriesPresentation("mesh_analysis.state", "mesh_analysis.state_description"),
    "active.active_local_rssi": MeshSeriesPresentation(
        "mesh_analysis.current_active_mr_rssi",
        "mesh_analysis.mr_rssi_description",
    ),
    "active.active_local_tx_busy": MeshSeriesPresentation("mesh_analysis.mr_tx_busy", "mesh_analysis.tx_busy_description"),
    "active.active_local_rx_busy": MeshSeriesPresentation("mesh_analysis.mr_rx_busy", "mesh_analysis.rx_busy_description"),
}


def format_mesh_value(value: object, metric_id: str) -> str:
    definition = MESH_METRICS[metric_id]
    presentation = MESH_SERIES_PRESENTATION[metric_id]
    numeric = _finite_number(value)
    if numeric is None:
        return "-"
    if definition.value_kind is MeshValueKind.STATE_CODE:
        return _format_state(numeric)
    text = _format_number(numeric, presentation.decimals)
    return _format_unit(text, definition)


def _finite_number(value: object) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _format_state(value: float) -> str:
    if int(value) == MeshLinkStateValue.ACTIVE:
        return "ACTIVE"
    if int(value) == MeshLinkStateValue.STANDBY:
        return "STANDBY"
    return "-"


def _format_number(value: float, decimals: int) -> str:
    if decimals <= 0:
        return str(int(round(value)))
    return f"{value:.{decimals}f}".rstrip("0").rstrip(".")


def _format_unit(text: str, definition: MeshMetricDefinition) -> str:
    if definition.unit is MeshUnitSemantics.PERCENT:
        return f"{text}%"
    if definition.unit is MeshUnitSemantics.SECONDS:
        return f"{text}s"
    if definition.unit is MeshUnitSemantics.NEGATIVE_DBM_MAGNITUDE:
        return f"{text} (meaning -{text} dBm)"
    return text
