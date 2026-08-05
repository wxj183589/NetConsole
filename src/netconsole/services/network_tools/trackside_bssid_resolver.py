from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from netconsole.models.ap_identity_index import ApIdentityBatchResult, ApIdentityMatch
from netconsole.models.wireless_scan_models import TracksideBssidMatch
from netconsole.repositories.ac_repository import AcRepository
from netconsole.services.ap_identity import ApIdentityQueryService
from netconsole.services.ap_identity.normalizers import normalize_mac_key


@dataclass(frozen=True)
class TracksideBssidBatchResult:
    revision: int
    index_status: str
    requested_count: int
    distinct_count: int
    matched_count: int
    unresolved_count: int
    ambiguous_count: int
    invalid_count: int
    matches: Mapping[str, TracksideBssidMatch]

    def __post_init__(self) -> None:
        object.__setattr__(self, "matches", MappingProxyType(dict(self.matches)))

    def match_for(self, scanned_bssid: object) -> TracksideBssidMatch:
        key = normalize_mac_key(scanned_bssid)
        if key is None:
            return TracksideBssidMatch(
                matched=False,
                match_status="invalid",
                identity_revision=self.revision,
                identity_reason="invalid_peer_mac",
            )
        return self.matches.get(
            key,
            TracksideBssidMatch(
                matched=False,
                match_status="unresolved",
                identity_revision=self.revision,
                identity_reason="exact_alias_not_found",
            ),
        )


class TracksideApBssidResolver:
    def __init__(self, query_service: ApIdentityQueryService) -> None:
        self._query_service = query_service

    @classmethod
    def from_site_repository(
        cls,
        repository: AcRepository,
    ) -> "TracksideApBssidResolver":
        return cls(ApIdentityQueryService(repository.database))

    @classmethod
    def from_ac_repository(
        cls,
        repository: AcRepository,
    ) -> "TracksideApBssidResolver":
        """Compatibility alias; AP identity candidates are site-scoped."""

        return cls.from_site_repository(repository)

    def resolve_many(
        self,
        scanned_bssids: Sequence[object],
        *,
        peer_names: Mapping[str, str] | None = None,
    ) -> TracksideBssidBatchResult:
        del peer_names
        batch = self._query_service.resolve_peer_macs(
            scanned_bssids,
            ap_role="trackside",
        )
        return _batch_result(batch)

    def resolve(
        self,
        scanned_bssid: object,
        peer_name: object | None = None,
    ) -> TracksideBssidMatch:
        peer_names = None
        key = normalize_mac_key(scanned_bssid)
        if key and peer_name:
            peer_names = {key: str(peer_name)}
        return self.resolve_many(
            [scanned_bssid],
            peer_names=peer_names,
        ).match_for(scanned_bssid)


def _batch_result(batch: ApIdentityBatchResult) -> TracksideBssidBatchResult:
    return TracksideBssidBatchResult(
        revision=batch.revision,
        index_status=batch.index_status,
        requested_count=batch.requested_count,
        distinct_count=batch.distinct_count,
        matched_count=batch.matched_count,
        unresolved_count=batch.unresolved_count,
        ambiguous_count=batch.ambiguous_count,
        invalid_count=batch.invalid_count,
        matches={key: _query_match(match) for key, match in batch.items()},
    )


def _query_match(match: ApIdentityMatch) -> TracksideBssidMatch:
    if not match.matched:
        return TracksideBssidMatch(
            matched=False,
            match_status=match.status,
            identity_revision=match.identity_revision,
            identity_reason=match.unresolved_reason,
            candidates=tuple(dict(row) for row in match.candidates),
        )
    return TracksideBssidMatch(
        matched=True,
        match_status="matched",
        identity_entity_id=match.matched_entity_id,
        identity_revision=match.identity_revision,
        identity_source=match.matched_source,
        identity_reason=match.unresolved_reason,
        matched_alias_type=match.matched_alias_type,
        ap_name=match.effective_ap_name or match.point_code or "-",
        point_code=match.point_code,
        ap_mac=match.effective_ap_mac,
        station=match.station,
        section=match.section,
        belong_type=match.belong_type,
        belonging_source=match.matched_source,
        serial_number=match.serial_number,
        location=match.location,
        mileage=match.mileage,
        direction=match.direction,
        radio_id=match.radio_id,
        match_rule=match.match_rule,
        confidence=match.match_confidence,
        candidates=tuple(dict(row) for row in match.candidates),
    )


__all__ = ["TracksideApBssidResolver", "TracksideBssidBatchResult"]
