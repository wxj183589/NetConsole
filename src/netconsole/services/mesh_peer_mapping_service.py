from __future__ import annotations

import sqlite3
from pathlib import Path

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.services.ap_identity import (
    ApIdentityQueryService,
    normalize_mac_key,
)


class MeshPeerMappingService:
    def __init__(self, site_name: str, paths: PathResolver) -> None:
        self.site_name = site_name
        self.paths = paths
        self._query_service: ApIdentityQueryService | None = None
        self.last_remap_summary: dict[str, object] = {}

    def resolve(self, peer_mac: object, peer_name: object | None = None) -> dict[str, object] | None:
        peer = normalize_mac_key(peer_mac)
        if not peer:
            return None
        service = self._get_query_service()
        if service is None:
            return _unresolved(peer)
        match = service.resolve_peer_mac(
            peer,
            peer_name=peer_name,
            ap_role="trackside",
        )
        if not match.matched:
            return _unresolved(
                peer,
                status=match.status,
                reason=match.unresolved_reason or "exact_alias_not_found",
            )
        radio_id = int(match.radio_id or 0) or None
        radio_rule = str(match.match_rule or "")
        peer_radio_mac = (
            peer
            if radio_id
            or "radio" in radio_rule
            or "bssid" in radio_rule
            else ""
        )
        ap_mac_key = normalize_mac_key(match.effective_ap_mac) or ""
        return {
            "peer_mac_normalized": peer,
            "peer_ap_name": match.effective_ap_name,
            "peer_ap_mac": ap_mac_key,
            "canonical_ap_mac": ap_mac_key,
            "peer_radio_id": radio_id,
            "peer_radio_label": f"radio{radio_id}" if radio_id else "",
            "peer_radio_mac": peer_radio_mac,
            "peer_site": match.station,
            "peer_section": match.section,
            "belong_type": match.belong_type,
            "belonging_source": match.matched_source,
            "peer_serial_number": match.serial_number,
            "serial_number": match.serial_number,
            "peer_location": match.location,
            "peer_direction": match.direction,
            "match_rule": radio_rule or "resolved",
            "match_confidence": int(match.match_confidence or 0),
            "identity_status": "matched",
            "identity_source": match.matched_source,
            "identity_reason": (
                match.data_quality_warning or match.unresolved_reason
            ),
            "identity_entity_id": match.matched_entity_id,
            "matched_alias_type": match.matched_alias_type,
            "query_mac_display": match.query_mac_display,
            "effective_ap_mac_display": match.effective_ap_mac,
            "ac_ap_mac": match.ac_ap_mac,
            "base_ap_mac": match.base_ap_mac,
            "data_quality_warning": match.data_quality_warning,
        }

    def build_rows(self, peer_macs: list[str]) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        seen: set[str] = set()
        service = self._get_query_service()
        if service is not None:
            service.pin_index_health()
        try:
            for peer_mac in peer_macs:
                peer = normalize_mac_key(peer_mac)
                if not peer or peer in seen:
                    continue
                seen.add(peer)
                resolved = self.resolve(peer)
                if resolved:
                    rows.append(resolved)
        finally:
            if service is not None:
                service.unpin_index_health()
        return rows

    def refresh_repository(self, repo) -> int:
        rows = self.build_rows(repo.distinct_peer_macs())
        self.last_remap_summary = repo.replace_peer_identity_mappings(rows)
        return int(self.last_remap_summary.get("mapping_count") or len(rows))

    def _get_query_service(self) -> ApIdentityQueryService | None:
        if self._query_service is not None:
            return self._query_service
        db_path = Path(self.paths.site_db_path(self.site_name))
        if not db_path.exists():
            return None
        try:
            database = Database(db_path)
            self._query_service = ApIdentityQueryService(database)
        except (sqlite3.Error, RuntimeError, OSError):
            return None
        return self._query_service


def _unresolved(
    peer_mac: str,
    *,
    status: str = "unresolved",
    reason: str = "统一 AP Identity 索引未找到匹配",
) -> dict[str, object]:
    return {
        "peer_mac_normalized": peer_mac,
        "peer_ap_name": "",
        "peer_ap_mac": "",
        "peer_radio_id": None,
        "peer_radio_label": "",
        "peer_radio_mac": peer_mac,
        "peer_site": "",
        "peer_section": "",
        "belong_type": "unknown",
        "belonging_source": "",
        "peer_serial_number": "",
        "serial_number": "",
        "peer_location": "",
        "peer_direction": "",
        "match_rule": "unresolved",
        "match_confidence": 0,
        "canonical_ap_mac": "",
        "identity_status": status,
        "identity_source": "",
        "identity_reason": reason,
    }
