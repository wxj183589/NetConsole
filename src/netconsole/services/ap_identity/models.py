from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Mapping


def _immutable_mapping(value: Mapping[str, object] | None) -> Mapping[str, object]:
    return MappingProxyType(dict(value or {}))


@dataclass(frozen=True)
class CanonicalApIdentity:
    ap_uuid: str | None = None
    ap_mac: str | None = None
    ap_name: str | None = None
    ac_uuid: str | None = None
    ap_id: str | None = None
    serial_number: str | None = None
    site_id: str | None = None
    source: str = ""
    source_ref: str | None = None


@dataclass(frozen=True)
class CanonicalApRadioIdentity:
    radio_id: int | None = None
    radio_mac: str | None = None
    bssid: str | None = None
    bbssid: str | None = None
    band: str | None = None
    ap_uuid: str | None = None
    ap_mac: str | None = None


@dataclass(frozen=True)
class CanonicalApLocation:
    site: str | None = None
    station: str | None = None
    section: str | None = None
    mileage: str | None = None
    line: str | None = None
    direction: str | None = None
    ownership_type: str | None = None
    system_type: str | None = None
    network_domain: str | None = None


@dataclass(frozen=True)
class ApObservation:
    ap_uuid: str | None = None
    ap_id: str | None = None
    ap_mac: str | None = None
    ap_name: str | None = None
    peer_mac: str | None = None
    peer_radio_mac: str | None = None
    radio_mac: str | None = None
    bssid: str | None = None
    ac_uuid: str | None = None
    device_uuid: str | None = None
    interface_name: str | None = None
    site: str | None = None
    station: str | None = None
    section: str | None = None
    mileage: str | None = None
    source: str = ""
    source_ref: str | None = None
    raw: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw", _immutable_mapping(self.raw))


@dataclass(frozen=True)
class ApIdentityCandidate:
    identity: CanonicalApIdentity
    radios: tuple[CanonicalApRadioIdentity, ...] = ()
    location: CanonicalApLocation = field(default_factory=CanonicalApLocation)
    raw: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        object.__setattr__(self, "radios", tuple(self.radios))
        object.__setattr__(self, "raw", _immutable_mapping(self.raw))


@dataclass(frozen=True)
class ApMatchEvidence:
    field: str
    observation_value: str
    candidate_value: str
    confidence: int
    reason: str


class ApMatchStatus(str, Enum):
    MATCHED = "matched"
    UNRESOLVED = "unresolved"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class ApMatchResult:
    status: ApMatchStatus
    candidate: ApIdentityCandidate | None = None
    candidates: tuple[ApIdentityCandidate, ...] = ()
    evidence: tuple[ApMatchEvidence, ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidates", tuple(self.candidates))
        object.__setattr__(self, "evidence", tuple(self.evidence))
        object.__setattr__(self, "warnings", tuple(self.warnings))
