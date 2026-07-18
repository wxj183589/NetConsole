from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum


class MeshValueKind(str, Enum):
    NUMBER = "number"
    STATE_CODE = "state_code"


class MeshUnitSemantics(str, Enum):
    RAW = "raw"
    PERCENT = "percent"
    SECONDS = "seconds"
    NEGATIVE_DBM_MAGNITUDE = "negative_dbm_magnitude"


class MeshLinkStateValue(IntEnum):
    STANDBY = 0
    ACTIVE = 1


@dataclass(frozen=True, slots=True)
class MeshMetricDefinition:
    metric_id: str
    value_kind: MeshValueKind
    unit: MeshUnitSemantics
    minimum: float | None = None
    maximum: float | None = None


def _metric(
    metric_id: str,
    *,
    unit: MeshUnitSemantics = MeshUnitSemantics.RAW,
    value_kind: MeshValueKind = MeshValueKind.NUMBER,
    minimum: float | None = None,
    maximum: float | None = None,
) -> MeshMetricDefinition:
    return MeshMetricDefinition(
        metric_id=metric_id,
        value_kind=value_kind,
        unit=unit,
        minimum=minimum,
        maximum=maximum,
    )


MESH_METRICS: dict[str, MeshMetricDefinition] = {
    "peer.local_rssi": _metric("peer.local_rssi"),
    "peer.peer_rssi": _metric("peer.peer_rssi"),
    "peer.local_noise": _metric(
        "peer.local_noise",
        unit=MeshUnitSemantics.NEGATIVE_DBM_MAGNITUDE,
        minimum=0,
    ),
    "peer.peer_noise": _metric(
        "peer.peer_noise",
        unit=MeshUnitSemantics.NEGATIVE_DBM_MAGNITUDE,
        minimum=0,
    ),
    "peer.local_tx_busy": _metric(
        "peer.local_tx_busy",
        unit=MeshUnitSemantics.PERCENT,
        minimum=0,
        maximum=100,
    ),
    "peer.peer_tx_busy": _metric(
        "peer.peer_tx_busy",
        unit=MeshUnitSemantics.PERCENT,
        minimum=0,
        maximum=100,
    ),
    "peer.local_rx_busy": _metric(
        "peer.local_rx_busy",
        unit=MeshUnitSemantics.PERCENT,
        minimum=0,
        maximum=100,
    ),
    "peer.peer_rx_busy": _metric(
        "peer.peer_rx_busy",
        unit=MeshUnitSemantics.PERCENT,
        minimum=0,
        maximum=100,
    ),
    "peer.state": _metric(
        "peer.state",
        value_kind=MeshValueKind.STATE_CODE,
        minimum=float(MeshLinkStateValue.STANDBY),
        maximum=float(MeshLinkStateValue.ACTIVE),
    ),
    "active.active_local_rssi": _metric("active.active_local_rssi"),
    "active.active_local_tx_busy": _metric(
        "active.active_local_tx_busy",
        unit=MeshUnitSemantics.PERCENT,
        minimum=0,
        maximum=100,
    ),
    "active.active_local_rx_busy": _metric(
        "active.active_local_rx_busy",
        unit=MeshUnitSemantics.PERCENT,
        minimum=0,
        maximum=100,
    ),
}
