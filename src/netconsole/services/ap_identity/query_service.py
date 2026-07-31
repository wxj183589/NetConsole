from __future__ import annotations

from collections.abc import Mapping, Sequence

from netconsole.core.database import Database
from netconsole.models.ap_identity_index import (
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

    def rebuild_index(self, reason: str) -> ApIdentityBuildResult:
        return self.repository.rebuild_index(
            build_ap_identity_index,
            site_id=self.site_id,
            reason=str(reason or "manual"),
        )

    def index_state(self) -> dict[str, object] | None:
        return self.repository.index_state(site_id=self.site_id)

    def ensure_index(self, reason: str = "missing_index_compat") -> ApIdentityBuildResult | None:
        state = self.repository.index_state(site_id=self.site_id)
        if state is not None and (
            int(state.get("revision") or 0) > 0
            or not self.repository.has_source_rows()
        ):
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
        return self._resolve_exact_aliases(mac, alias_order=_EXACT_ALIAS_ORDER)

    def resolve_peer_mac(
        self,
        mac: object,
        *,
        peer_name: object | None = None,
    ) -> ApIdentityMatch:
        # A MESH Peer is a Radio/BSSID observation. Even an exact AP base MAC
        # is not sufficient evidence that the observed field represents it.
        del peer_name
        return self._resolve_exact_aliases(mac, alias_order=_PEER_ALIAS_ORDER)

    def _resolve_exact_aliases(
        self,
        mac: object,
        *,
        alias_order: Sequence[str],
    ) -> ApIdentityMatch:
        mac_key = normalize_mac_key(mac) or ""
        query_display = format_mac(mac_key)
        if mac_key:
            exact_rows = self.repository.exact_alias_rows(
                mac_key,
                site_id=self.site_id,
            )
            for alias_type in alias_order:
                matched = [
                    row
                    for row in exact_rows
                    if str(row.get("alias_type") or "") == alias_type
                ]
                if matched:
                    return self._result(
                        matched,
                        query_mac=mac_key,
                        query_display=query_display,
                    )

        return ApIdentityMatch(
            status="invalid_mac" if not mac_key else "unresolved",
            query_mac=mac_key,
            query_mac_display=query_display,
        )

    def search_aps(
        self,
        query: str,
        *,
        limit: int = 200,
    ) -> list[dict[str, object]]:
        mac_key = normalize_mac_key(query)
        if mac_key:
            match = self.resolve_mac(mac_key)
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
                query_mac=query_mac,
                query_mac_display=query_display,
                candidates=tuple(
                    _candidate_payload(row, query_display)
                    for row in by_entity.values()
                ),
            )
        row = next(iter(by_entity.values()))
        return ApIdentityMatch(
            status="matched",
            query_mac=query_mac,
            query_mac_display=query_display,
            matched_entity_id=str(row.get("entity_id") or ""),
            effective_ap_name=str(row.get("effective_ap_name") or ""),
            effective_ap_mac=str(row.get("effective_ap_mac_display") or ""),
            station=str(row.get("effective_station") or ""),
            section=str(row.get("effective_section") or ""),
            point_code=str(row.get("effective_point_code") or ""),
            serial_number=str(row.get("effective_serial_number") or ""),
            location=str(row.get("effective_location") or ""),
            mileage=str(row.get("effective_mileage") or ""),
            direction=str(row.get("effective_direction") or ""),
            belong_type=str(row.get("effective_belong_type") or "unknown"),
            matched_alias_type=str(row.get("alias_type") or ""),
            matched_source=str(
                row.get("source") or row.get("effective_source") or ""
            ),
            match_rule=str(row.get("derivation_rule") or ""),
            match_confidence=int(row.get("confidence") or 0),
            radio_id=_optional_int(row.get("radio_id")),
            ac_ap_mac=format_mac(row.get("ac_ap_mac_key")),
            base_ap_mac=format_mac(row.get("base_ap_mac_key")),
            base_record_id=str(row.get("base_record_id") or ""),
            has_conflict=bool(row.get("data_quality_warning")),
            data_quality_warning=str(row.get("data_quality_warning") or ""),
            candidates=(_candidate_payload(row, query_display),),
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


__all__ = ["ApIdentityQueryService"]
