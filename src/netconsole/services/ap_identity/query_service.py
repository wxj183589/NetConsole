from __future__ import annotations

from collections.abc import Mapping, Sequence

from netconsole.core.database import Database
from netconsole.models.ap_identity_index import (
    ApIdentityBatchResult,
    ApIdentityBuildResult,
    ApIdentityMatch,
)
from netconsole.repositories.ap_identity_repository import ApIdentityRepository
from netconsole.services.ap_identity.index_builder import build_ap_identity_index
from netconsole.services.ap_identity.normalizers import format_mac, normalize_mac_key


_EXACT_ALIAS_ORDER = (
    "ac_radio_mac",
    "ac_bssid",
    "ac_bbssid",
    "h3c_r1_derived",
    "h3c_r2_derived",
    "ac_ap_mac",
    "base_ap_mac",
    "legacy_mac",
)

_PEER_ALIAS_ORDER = _EXACT_ALIAS_ORDER[:5]


class ApIdentityQueryService:
    def __init__(
        self,
        database: Database,
        *,
        site_id: str = "current",
    ) -> None:
        self.repository = ApIdentityRepository(database)
        self.site_id = str(site_id or "current")
        self._health_cache: tuple[dict[str, object] | None, int] | None = None
        self._health_pinned = False

    def rebuild_index(self, reason: str) -> ApIdentityBuildResult:
        result = self.repository.rebuild_index(
            build_ap_identity_index,
            site_id=self.site_id,
            reason=str(reason or "manual"),
        )
        self._health_cache = None
        self._health_pinned = False
        return result

    def index_state(self) -> dict[str, object] | None:
        return self.repository.index_state(site_id=self.site_id)

    def ensure_index(
        self, reason: str = "missing_index_compat"
    ) -> ApIdentityBuildResult | None:
        state, source_revision = self.repository.index_health(site_id=self.site_id)
        indexed_source_revision = (
            int(state["source_revision"])
            if state is not None and state.get("source_revision") is not None
            else -1
        )
        if (
            state is not None
            and int(state.get("revision") or 0) > 0
            and indexed_source_revision == source_revision
        ):
            return None
        if not self.repository.has_source_rows() and state is not None:
            return None
        return self.rebuild_index(reason)

    def resolve_mac(
        self,
        mac: object,
        *,
        peer_name: object | None = None,
    ) -> ApIdentityMatch:
        # Kept for call-site compatibility. AP names are display/diagnostic
        # evidence and must not turn an unresolved MAC into a match.
        del peer_name
        return self.resolve_ap_mac(mac)

    def resolve_ap_mac(self, mac: object) -> ApIdentityMatch:
        return self._resolve_exact_aliases(mac, alias_order=_EXACT_ALIAS_ORDER)

    def resolve_ap_macs(
        self,
        macs: Sequence[object],
    ) -> ApIdentityBatchResult:
        return self._resolve_exact_alias_batch(
            macs,
            alias_order=_EXACT_ALIAS_ORDER,
        )

    def resolve_peer_mac(
        self,
        mac: object,
        *,
        peer_name: object | None = None,
        ap_role: str | None = None,
    ) -> ApIdentityMatch:
        # A MESH Peer is a Radio/BSSID observation. Even an exact AP base MAC
        # is not sufficient evidence that the observed field represents it.
        del peer_name
        return self._resolve_exact_aliases(
            mac,
            alias_order=_PEER_ALIAS_ORDER,
            ap_role=ap_role,
        )

    def resolve_peer_macs(
        self,
        macs: Sequence[object],
        *,
        ap_role: str | None = None,
    ) -> ApIdentityBatchResult:
        return self._resolve_exact_alias_batch(
            macs,
            alias_order=_PEER_ALIAS_ORDER,
            ap_role=ap_role,
        )

    def _resolve_exact_aliases(
        self,
        mac: object,
        *,
        alias_order: Sequence[str],
        ap_role: str | None = None,
    ) -> ApIdentityMatch:
        mac_key = normalize_mac_key(mac) or ""
        query_display = format_mac(mac_key)
        if not mac_key:
            return ApIdentityMatch(
                status="unresolved",
                query_mac="",
                query_mac_display="",
                unresolved_reason="invalid_peer_mac",
            )

        state, source_revision = self._cached_health()
        identity_revision = int((state or {}).get("revision") or 0)
        health_reason = _index_health_reason(state, source_revision)
        if health_reason:
            return ApIdentityMatch(
                status="unresolved",
                identity_revision=identity_revision,
                query_mac=mac_key,
                query_mac_display=query_display,
                unresolved_reason=health_reason,
            )

        if mac_key:
            exact_rows = self.repository.exact_alias_rows(
                mac_key,
                site_id=self.site_id,
            )
            allowed_types = set(alias_order)
            matched = [
                row
                for row in exact_rows
                if str(row.get("alias_type") or "") in allowed_types
                and _matches_ap_role(row, ap_role)
            ]
            if matched:
                alias_rank = {
                    alias_type: index for index, alias_type in enumerate(alias_order)
                }
                matched.sort(
                    key=lambda row: (
                        alias_rank.get(str(row.get("alias_type") or ""), 999),
                        -int(row.get("match_priority") or 0),
                    )
                )
                return self._result(
                    matched,
                    identity_revision=identity_revision,
                    query_mac=mac_key,
                    query_display=query_display,
                )

        collected_alias_count = _collected_alias_count(state or {})
        return ApIdentityMatch(
            status="unresolved",
            identity_revision=identity_revision,
            query_mac=mac_key,
            query_mac_display=query_display,
            unresolved_reason=(
                "exact_alias_not_collected"
                if collected_alias_count == 0
                else "exact_alias_not_found"
            ),
        )

    def _resolve_exact_alias_batch(
        self,
        macs: Sequence[object],
        *,
        alias_order: Sequence[str],
        ap_role: str | None = None,
    ) -> ApIdentityBatchResult:
        normalized_keys = [
            mac_key for mac in macs if (mac_key := normalize_mac_key(mac)) is not None
        ]
        mac_keys = tuple(dict.fromkeys(normalized_keys))
        if not mac_keys:
            return ApIdentityBatchResult(
                revision=0,
                index_status="not_checked",
                requested_count=len(macs),
                normalized_count=len(normalized_keys),
                distinct_count=0,
                matched_count=0,
                unresolved_count=0,
                ambiguous_count=0,
                invalid_count=len(macs) - len(normalized_keys),
            )

        state, source_revision, exact_rows = self.repository.exact_alias_snapshot(
            mac_keys,
            site_id=self.site_id,
        )
        identity_revision = int((state or {}).get("revision") or 0)
        health_reason = _index_health_reason(state, source_revision)
        if health_reason:
            matches = {
                mac_key: ApIdentityMatch(
                    status="unresolved",
                    identity_revision=identity_revision,
                    query_mac=mac_key,
                    query_mac_display=format_mac(mac_key),
                    unresolved_reason=health_reason,
                )
                for mac_key in mac_keys
            }
            return _batch_result(
                matches,
                revision=identity_revision,
                index_status=health_reason,
                requested_count=len(macs),
                normalized_count=len(normalized_keys),
            )

        rows_by_mac: dict[str, list[Mapping[str, object]]] = {
            mac_key: [] for mac_key in mac_keys
        }
        allowed_types = set(alias_order)
        for row in exact_rows:
            mac_key = str(row.get("mac_key") or "")
            if (
                mac_key in rows_by_mac
                and str(row.get("alias_type") or "") in allowed_types
                and _matches_ap_role(row, ap_role)
            ):
                rows_by_mac[mac_key].append(row)

        alias_rank = {alias_type: index for index, alias_type in enumerate(alias_order)}
        unresolved_reason = (
            "exact_alias_not_collected"
            if _collected_alias_count(state or {}) == 0
            else "exact_alias_not_found"
        )
        results: dict[str, ApIdentityMatch] = {}
        for mac_key in mac_keys:
            rows = rows_by_mac[mac_key]
            query_display = format_mac(mac_key)
            if not rows:
                results[mac_key] = ApIdentityMatch(
                    status="unresolved",
                    identity_revision=identity_revision,
                    query_mac=mac_key,
                    query_mac_display=query_display,
                    unresolved_reason=unresolved_reason,
                )
                continue
            rows.sort(
                key=lambda row: (
                    alias_rank.get(str(row.get("alias_type") or ""), 999),
                    -int(row.get("match_priority") or 0),
                )
            )
            results[mac_key] = self._result(
                rows,
                identity_revision=identity_revision,
                query_mac=mac_key,
                query_display=query_display,
            )
        return _batch_result(
            results,
            revision=identity_revision,
            index_status="ready",
            requested_count=len(macs),
            normalized_count=len(normalized_keys),
        )

    def _cached_health(self) -> tuple[dict[str, object] | None, int]:
        if self._health_cache is None or not self._health_pinned:
            self._health_cache = self.repository.index_health(site_id=self.site_id)
        return self._health_cache

    def pin_index_health(self) -> None:
        self._health_cache = self.repository.index_health(site_id=self.site_id)
        self._health_pinned = True

    def unpin_index_health(self) -> None:
        self._health_pinned = False
        self._health_cache = None

    def _index_health_reason(self) -> str:
        state, source_revision = self._cached_health()
        return _index_health_reason(state, source_revision)

    def search_aps(
        self,
        query: str,
        *,
        limit: int = 200,
    ) -> list[dict[str, object]]:
        mac_key = normalize_mac_key(query)
        if mac_key:
            match = self.resolve_ap_mac(mac_key)
            if match.status == "matched":
                return [_search_payload(match)]
            if match.status == "ambiguous":
                return [dict(candidate) for candidate in match.candidates[:limit]]
            return []
        return [
            _entity_search_payload(row)
            for row in self.repository.search_entity_rows(
                query,
                site_id=self.site_id,
                limit=limit,
            )
        ]

    def get_entity(self, entity_id: str) -> dict[str, object] | None:
        row = self.repository.entity_row(
            entity_id,
            site_id=self.site_id,
        )
        return _entity_search_payload(row) if row is not None else None

    def list_entities(self) -> list[dict[str, object]]:
        return [
            _entity_search_payload(row)
            for row in self.repository.list_entity_rows(site_id=self.site_id)
        ]

    def list_conflicts(self) -> list[dict[str, object]]:
        return self.repository.conflict_rows(site_id=self.site_id)

    def _result(
        self,
        rows: Sequence[Mapping[str, object]],
        *,
        identity_revision: int,
        query_mac: str,
        query_display: str,
    ) -> ApIdentityMatch:
        by_entity: dict[str, Mapping[str, object]] = {}
        for row in rows:
            entity_id = str(row.get("entity_id") or "")
            current = by_entity.get(entity_id)
            if current is None or int(row.get("match_priority") or 0) > int(
                current.get("match_priority") or 0
            ):
                by_entity[entity_id] = row
        if len(by_entity) != 1:
            return ApIdentityMatch(
                status="ambiguous",
                identity_revision=identity_revision,
                query_mac=query_mac,
                query_mac_display=query_display,
                candidates=tuple(
                    _candidate_payload(row, query_display) for row in by_entity.values()
                ),
                unresolved_reason="duplicate_exact_alias",
            )
        row = next(iter(by_entity.values()))
        effective_ap_mac = str(row.get("effective_ap_mac_display") or "")
        if not normalize_mac_key(effective_ap_mac):
            return ApIdentityMatch(
                status="unresolved",
                identity_revision=identity_revision,
                query_mac=query_mac,
                query_mac_display=query_display,
                candidates=(_candidate_payload(row, query_display),),
                unresolved_reason="physical_ap_missing",
            )
        return ApIdentityMatch(
            status="matched",
            identity_revision=identity_revision,
            query_mac=query_mac,
            query_mac_display=query_display,
            matched_entity_id=str(row.get("entity_id") or ""),
            effective_ap_name=str(row.get("effective_ap_name") or ""),
            effective_ap_mac=effective_ap_mac,
            station=str(row.get("effective_station") or ""),
            section=str(row.get("effective_section") or ""),
            point_code=str(row.get("effective_point_code") or ""),
            serial_number=str(row.get("effective_serial_number") or ""),
            location=str(row.get("effective_location") or ""),
            mileage=str(row.get("effective_mileage") or ""),
            direction=str(row.get("effective_direction") or ""),
            belong_type=str(row.get("effective_belong_type") or "unknown"),
            matched_alias_type=str(row.get("alias_type") or ""),
            matched_source=str(row.get("source") or row.get("effective_source") or ""),
            match_rule=str(row.get("derivation_rule") or ""),
            match_confidence=int(row.get("confidence") or 0),
            radio_id=_optional_int(row.get("radio_id")),
            ac_ap_mac=format_mac(row.get("ac_ap_mac_key")),
            base_ap_mac=format_mac(row.get("base_ap_mac_key")),
            base_record_id=str(row.get("base_record_id") or ""),
            has_conflict=bool(row.get("data_quality_warning")),
            data_quality_warning=str(row.get("data_quality_warning") or ""),
            candidates=(_candidate_payload(row, query_display),),
            unresolved_reason=(
                "station_topology_missing"
                if not str(row.get("effective_station") or "").strip()
                else ""
            ),
        )


def _candidate_payload(
    row: Mapping[str, object],
    query_mac_display: str,
) -> dict[str, object]:
    return {
        "entity_id": str(row.get("entity_id") or ""),
        "ap_name": str(row.get("effective_ap_name") or ""),
        "point_code": str(row.get("effective_point_code") or ""),
        "ap_mac": str(row.get("effective_ap_mac_display") or ""),
        "query_mac": query_mac_display,
        "station": str(row.get("effective_station") or ""),
        "section": str(row.get("effective_section") or ""),
        "source": str(row.get("source") or row.get("effective_source") or ""),
        "match_rule": str(row.get("derivation_rule") or ""),
        "confidence": int(row.get("confidence") or 0),
        "radio_id": _optional_int(row.get("radio_id")),
        "ac_ap_mac": format_mac(row.get("ac_ap_mac_key")),
        "base_ap_mac": format_mac(row.get("base_ap_mac_key")),
        "base_record_id": str(row.get("base_record_id") or ""),
        "data_quality_warning": str(row.get("data_quality_warning") or ""),
    }


def _search_payload(match: ApIdentityMatch) -> dict[str, object]:
    return {
        "entity_id": match.matched_entity_id,
        "ap_name": match.effective_ap_name,
        "ap_mac": match.effective_ap_mac,
        "matched_mac": match.query_mac_display,
        "matched_alias_type": match.matched_alias_type,
        "source": match.matched_source,
        "match_rule": match.match_rule,
        "confidence": match.match_confidence,
        "station": match.station,
        "section": match.section,
        "ac_ap_mac": match.ac_ap_mac,
        "base_ap_mac": match.base_ap_mac,
        "base_record_id": match.base_record_id,
        "data_quality_warning": match.data_quality_warning,
    }


def _entity_search_payload(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "entity_id": str(row.get("entity_id") or ""),
        "ap_name": str(row.get("effective_ap_name") or ""),
        "ap_mac": str(row.get("effective_ap_mac_display") or ""),
        "matched_mac": str(row.get("effective_ap_mac_display") or ""),
        "matched_alias_type": "entity_text",
        "source": str(row.get("effective_source") or ""),
        "match_rule": "entity_text_search",
        "confidence": 100,
        "station": str(row.get("effective_station") or ""),
        "section": str(row.get("effective_section") or ""),
        "point_code": str(row.get("effective_point_code") or ""),
        "serial_number": str(row.get("effective_serial_number") or ""),
        "location": str(row.get("effective_location") or ""),
        "mileage": str(row.get("effective_mileage") or ""),
        "direction": str(row.get("effective_direction") or ""),
        "belong_type": str(row.get("effective_belong_type") or "unknown"),
        "ac_ap_mac": format_mac(row.get("ac_ap_mac_key")),
        "base_ap_mac": format_mac(row.get("base_ap_mac_key")),
        "base_record_id": str(row.get("base_record_id") or ""),
        "identity_status": str(row.get("identity_status") or "matched"),
        "data_quality_warning": str(row.get("data_quality_warning") or ""),
    }


def _optional_int(value: object) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number or None


def _index_health_reason(
    state: Mapping[str, object] | None,
    source_revision: int,
) -> str:
    if state is None or int(state.get("revision") or 0) <= 0:
        return "identity_index_missing"
    indexed_source_revision = (
        int(state["source_revision"])
        if state.get("source_revision") is not None
        else -1
    )
    if indexed_source_revision != source_revision:
        return "identity_index_stale"
    return ""


def _collected_alias_count(state: Mapping[str, object]) -> int:
    return sum(
        int(state.get(field) or 0)
        for field in (
            "actual_radio_alias_count",
            "actual_bssid_alias_count",
            "actual_bbssid_alias_count",
            "derived_alias_count",
        )
    )


def _batch_result(
    matches: Mapping[str, ApIdentityMatch],
    *,
    revision: int,
    index_status: str,
    requested_count: int,
    normalized_count: int,
) -> ApIdentityBatchResult:
    statuses = [match.status for match in matches.values()]
    return ApIdentityBatchResult(
        revision=revision,
        index_status=index_status,
        requested_count=requested_count,
        normalized_count=normalized_count,
        distinct_count=len(matches),
        matched_count=statuses.count("matched"),
        unresolved_count=statuses.count("unresolved"),
        ambiguous_count=statuses.count("ambiguous"),
        invalid_count=requested_count - normalized_count,
        matches=dict(matches),
    )


def _matches_ap_role(row: Mapping[str, object], requested_role: str | None) -> bool:
    role = str(requested_role or "").strip().casefold()
    if not role:
        return True
    belong_type = str(row.get("effective_belong_type") or "").strip().casefold()
    if belong_type in {"onboard", "vehicle", "train"}:
        entity_role = "onboard"
    elif belong_type in {"trackside", "station", "section", "yard"}:
        entity_role = "trackside"
    elif str(row.get("effective_source") or "") == "ac_runtime":
        entity_role = "trackside"
    else:
        entity_role = "unknown"
    return entity_role == role


__all__ = ["ApIdentityQueryService"]
