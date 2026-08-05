from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ApIdentityEntityRecord:
    entity_id: str
    site_id: str
    effective_ap_name: str = ""
    effective_ap_mac_key: str = ""
    effective_ap_mac_display: str = ""
    effective_station: str = ""
    effective_section: str = ""
    effective_point_code: str = ""
    effective_serial_number: str = ""
    effective_location: str = ""
    effective_mileage: str = ""
    effective_direction: str = ""
    effective_belong_type: str = "unknown"
    ac_ap_uuid: str = ""
    ac_device_uuid: str = ""
    ac_ap_name: str = ""
    ac_ap_mac_key: str = ""
    ac_station: str = ""
    ac_section: str = ""
    ac_updated_at: str = ""
    base_record_id: str = ""
    base_ap_name: str = ""
    base_ap_mac_key: str = ""
    base_station: str = ""
    base_section: str = ""
    base_updated_at: str = ""
    effective_source: str = ""
    identity_status: str = "matched"
    data_quality_warning: str = ""


@dataclass(frozen=True)
class ApIdentityMacAliasRecord:
    entity_id: str
    site_id: str
    mac_key: str
    mac_display: str
    alias_type: str
    source: str
    match_priority: int
    confidence: int
    radio_id: int | None = None
    derivation_rule: str = ""
    is_exact: bool = True


@dataclass(frozen=True)
class ApIdentityH3cPrefixRecord:
    entity_id: str
    site_id: str
    base_mac_key: str
    prefix_key: str
    prefix_bits: int
    derivation_rule: str
    source: str
    match_priority: int
    confidence: int


@dataclass(frozen=True)
class ApIdentityConflictRecord:
    entity_id: str
    site_id: str
    conflict_type: str
    ac_value: str = ""
    base_value: str = ""
    effective_source: str = "ac_runtime"
    details: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ApIdentityIndexBuild:
    entities: tuple[ApIdentityEntityRecord, ...] = ()
    aliases: tuple[ApIdentityMacAliasRecord, ...] = ()
    prefixes: tuple[ApIdentityH3cPrefixRecord, ...] = ()
    conflicts: tuple[ApIdentityConflictRecord, ...] = ()
    base_record_count: int = 0
    ac_record_count: int = 0


@dataclass(frozen=True)
class ApIdentityBuildResult:
    site_id: str
    revision: int
    reason: str
    built_at: str
    base_record_count: int
    ac_record_count: int
    entity_count: int
    alias_count: int
    prefix_count: int
    conflict_count: int
    source_revision: int = 0
    actual_radio_alias_count: int = 0
    actual_bssid_alias_count: int = 0
    actual_bbssid_alias_count: int = 0
    derived_alias_count: int = 0
    ambiguous_alias_count: int = 0
    build_duration_ms: float = 0.0


@dataclass(frozen=True)
class ApIdentityRevisionState:
    site_id: str
    revision: int
    indexed_source_revision: int
    current_source_revision: int
    status: str
    revision_token: str
    built_at: str = ""


@dataclass(frozen=True)
class ApIdentityMatch:
    status: str
    identity_revision: int = 0
    query_mac: str = ""
    query_mac_display: str = ""
    matched_entity_id: str = ""
    effective_ap_name: str = ""
    effective_ap_mac: str = ""
    station: str = ""
    section: str = ""
    point_code: str = ""
    serial_number: str = ""
    location: str = ""
    mileage: str = ""
    direction: str = ""
    belong_type: str = "unknown"
    matched_alias_type: str = ""
    matched_source: str = ""
    match_rule: str = ""
    match_confidence: int = 0
    radio_id: int | None = None
    ac_ap_mac: str = ""
    base_ap_mac: str = ""
    base_record_id: str = ""
    has_conflict: bool = False
    data_quality_warning: str = ""
    candidates: tuple[Mapping[str, object], ...] = ()
    unresolved_reason: str = ""

    @property
    def matched(self) -> bool:
        return self.status == "matched"


@dataclass(frozen=True)
class ApIdentityBatchResult(Mapping[str, ApIdentityMatch]):
    revision: int
    index_status: str
    requested_count: int
    normalized_count: int
    distinct_count: int
    matched_count: int
    unresolved_count: int
    ambiguous_count: int
    invalid_count: int
    matches: Mapping[str, ApIdentityMatch] = field(default_factory=dict)

    def __getitem__(self, key: str) -> ApIdentityMatch:
        return self.matches[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.matches)

    def __len__(self) -> int:
        return len(self.matches)
