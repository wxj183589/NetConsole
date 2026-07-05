from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TopologyNode:
    node_id: str
    name: str
    node_type: str = "未知设备"
    device_uuid: str = ""
    address: str = ""


@dataclass(frozen=True)
class TopologyEdge:
    source_id: str
    target_id: str
    edge_type: str = "unknown"
    local_interface: str = ""
    remote_interface: str = ""
    source: str = ""
    confidence: int = 0

