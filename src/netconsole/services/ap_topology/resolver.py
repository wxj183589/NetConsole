from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ApTopologyEvidence:
    """Structured, already-loaded evidence for one physical AP entity."""

    lldp_valid: bool = False
    lldp_conflict: bool = False
    lldp_switch_uuid: str = ""
    lldp_station_id: str = ""
    lldp_station: str = ""

    fit_ap_station: str = ""
    fit_ap_section: str = ""
    fit_ap_location: str = ""
    fit_ap_mileage: str = ""
    fit_ap_direction: str = ""
    fit_ap_belong_type: str = ""

    device_station: str = ""
    device_section: str = ""
    device_location: str = ""
    device_mileage: str = ""
    device_direction: str = ""
    device_belong_type: str = ""

    ac_runtime_station: str = ""
    ac_runtime_section: str = ""
    ac_runtime_location: str = ""
    ac_runtime_mileage: str = ""
    ac_runtime_direction: str = ""
    ac_runtime_belong_type: str = ""

    base_station: str = ""
    base_section: str = ""
    base_location: str = ""
    base_mileage: str = ""
    base_direction: str = ""
    base_belong_type: str = ""

    legacy_station: str = ""
    legacy_section: str = ""
    legacy_location: str = ""
    legacy_mileage: str = ""
    legacy_direction: str = ""
    legacy_belong_type: str = ""


@dataclass(frozen=True)
class ResolvedTopologyField:
    value: str = ""
    source: str = "unresolved"
    confidence: int = 0
    reason: str = ""


@dataclass(frozen=True)
class ResolvedApTopology:
    station: ResolvedTopologyField = ResolvedTopologyField()
    section: ResolvedTopologyField = ResolvedTopologyField()
    location: ResolvedTopologyField = ResolvedTopologyField()
    mileage: ResolvedTopologyField = ResolvedTopologyField()
    direction: ResolvedTopologyField = ResolvedTopologyField()
    belong_type: ResolvedTopologyField = ResolvedTopologyField(
        value="unknown", source="unresolved"
    )
    warnings: tuple[str, ...] = ()

    @property
    def effective_source(self) -> str:
        for field in (
            self.station,
            self.section,
            self.location,
            self.mileage,
            self.direction,
            self.belong_type,
        ):
            if field.source != "unresolved":
                return field.source
        return "unresolved"


_STATION_PRIORITY = (
    ("lldp_switch", "lldp_station"),
    ("fit_ap_runtime", "fit_ap_station"),
    ("device_management", "device_station"),
    ("ac_runtime", "ac_runtime_station"),
    ("base_data", "base_station"),
    ("legacy", "legacy_station"),
)
_FIELD_PRIORITIES = {
    "section": (
        ("fit_ap_runtime", "fit_ap_section"),
        ("device_management", "device_section"),
        ("ac_runtime", "ac_runtime_section"),
        ("base_data", "base_section"),
        ("legacy", "legacy_section"),
    ),
    "location": (
        ("fit_ap_runtime", "fit_ap_location"),
        ("device_management", "device_location"),
        ("ac_runtime", "ac_runtime_location"),
        ("base_data", "base_location"),
        ("legacy", "legacy_location"),
    ),
    "mileage": (
        ("fit_ap_runtime", "fit_ap_mileage"),
        ("device_management", "device_mileage"),
        ("ac_runtime", "ac_runtime_mileage"),
        ("base_data", "base_mileage"),
        ("legacy", "legacy_mileage"),
    ),
    "direction": (
        ("fit_ap_runtime", "fit_ap_direction"),
        ("device_management", "device_direction"),
        ("ac_runtime", "ac_runtime_direction"),
        ("base_data", "base_direction"),
        ("legacy", "legacy_direction"),
    ),
    "belong_type": (
        ("fit_ap_runtime", "fit_ap_belong_type"),
        ("device_management", "device_belong_type"),
        ("ac_runtime", "ac_runtime_belong_type"),
        ("base_data", "base_belong_type"),
        ("legacy", "legacy_belong_type"),
    ),
}


def resolve_ap_topology(evidence: ApTopologyEvidence) -> ResolvedApTopology:
    """Resolve each topology field independently from structured evidence.

    LLDP is eligible only when the caller has already established a unique,
    structured switch relationship. The resolver deliberately knows nothing
    about databases or display names, so a neighbor string cannot become a
    station by accident.
    """

    warnings: list[str] = []
    if evidence.lldp_conflict:
        warnings.append("topology_lldp_ambiguous")
    if evidence.lldp_valid and not _text(evidence.lldp_station):
        warnings.append("switch_station_missing")
    if evidence.lldp_valid and evidence.lldp_station and evidence.base_station:
        if _text(evidence.lldp_station) != _text(evidence.base_station):
            warnings.append("topology_lldp_base_conflict")
    if evidence.lldp_valid and evidence.lldp_station and evidence.fit_ap_station:
        if _text(evidence.lldp_station) != _text(evidence.fit_ap_station):
            warnings.append("topology_lldp_fit_ap_conflict")
    if evidence.fit_ap_station and evidence.base_station:
        if _text(evidence.fit_ap_station) != _text(evidence.base_station):
            warnings.append("topology_runtime_base_conflict")

    station = _resolve_field(
        evidence,
        _STATION_PRIORITY,
        lldp_allowed=bool(
            evidence.lldp_valid
            and not evidence.lldp_conflict
            and _text(evidence.lldp_switch_uuid)
        ),
    )
    fields: dict[str, ResolvedTopologyField] = {"station": station}
    for field, priorities in _FIELD_PRIORITIES.items():
        fields[field] = _resolve_field(evidence, priorities)
    return ResolvedApTopology(warnings=tuple(dict.fromkeys(warnings)), **fields)


def _resolve_field(
    evidence: ApTopologyEvidence,
    priorities: tuple[tuple[str, str], ...],
    *,
    lldp_allowed: bool = False,
) -> ResolvedTopologyField:
    for source, attribute in priorities:
        if source == "lldp_switch" and not lldp_allowed:
            continue
        value = _text(getattr(evidence, attribute, ""))
        if value:
            return ResolvedTopologyField(
                value=value,
                source=source,
                confidence={
                    "lldp_switch": 100,
                    "fit_ap_runtime": 90,
                    "device_management": 80,
                    "ac_runtime": 70,
                    "base_data": 60,
                    "legacy": 30,
                }.get(source, 0),
            )
    return ResolvedTopologyField()


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


__all__ = [
    "ApTopologyEvidence",
    "ResolvedApTopology",
    "ResolvedTopologyField",
    "resolve_ap_topology",
]
