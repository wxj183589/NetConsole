"""Shared AP topology evidence resolution."""

from .resolver import (
    AP_TOPOLOGY_PROJECTION_VERSION,
    ApTopologyEvidence,
    ResolvedApTopology,
    ResolvedTopologyField,
    resolve_ap_topology,
)

__all__ = [
    "AP_TOPOLOGY_PROJECTION_VERSION",
    "ApTopologyEvidence",
    "ResolvedApTopology",
    "ResolvedTopologyField",
    "resolve_ap_topology",
]
