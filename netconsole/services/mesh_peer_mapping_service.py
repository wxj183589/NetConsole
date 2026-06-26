from __future__ import annotations

import sqlite3
from pathlib import Path

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.repositories.ac_repository import AcRepository
from netconsole.services.network_tools.trackside_bssid_resolver import TracksideApBssidResolver
from netconsole.services.network_tools.wireless_channel_analyzer import normalize_mac


class MeshPeerMappingService:
    def __init__(self, site_name: str, paths: PathResolver) -> None:
        self.site_name = site_name
        self.paths = paths
        self._resolver: TracksideApBssidResolver | None = None

    def resolve(self, peer_mac: object) -> dict[str, object] | None:
        peer = normalize_mac(peer_mac)
        if not peer:
            return None
        resolver = self._get_resolver()
        if resolver is None:
            return _unresolved(peer)
        match = resolver.resolve(peer)
        if not match.matched:
            return _unresolved(peer)
        radio_id = int(match.radio_id or 0) or None
        return {
            "peer_mac_normalized": peer,
            "peer_ap_name": match.ap_name if match.ap_name != "-" else "",
            "peer_ap_mac": normalize_mac(match.ap_mac) or match.ap_mac,
            "peer_radio_id": radio_id,
            "peer_radio_label": f"radio{radio_id}" if radio_id else "",
            "peer_radio_mac": peer,
            "peer_site": match.station,
            "peer_location": match.location,
            "peer_direction": match.direction,
            "match_rule": match.match_rule or "h3c_rule",
            "match_confidence": int(match.confidence or 0),
        }

    def build_rows(self, peer_macs: list[str]) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        seen: set[str] = set()
        for peer_mac in peer_macs:
            peer = normalize_mac(peer_mac)
            if not peer or peer in seen:
                continue
            seen.add(peer)
            resolved = self.resolve(peer)
            if resolved:
                rows.append(resolved)
        return rows

    def refresh_repository(self, repo) -> int:
        rows = self.build_rows(repo.distinct_peer_macs())
        repo.upsert_peer_mappings(rows)
        repo.refresh_peer_mapping_on_links()
        return len(rows)

    def _get_resolver(self) -> TracksideApBssidResolver | None:
        if self._resolver is not None:
            return self._resolver
        db_path = Path(self.paths.site_db_path(self.site_name))
        if not db_path.exists():
            return None
        try:
            repository = AcRepository(Database(db_path))
            self._resolver = TracksideApBssidResolver.from_ac_repository(repository)
        except (sqlite3.Error, RuntimeError, OSError):
            return None
        return self._resolver


def _unresolved(peer_mac: str) -> dict[str, object]:
    return {
        "peer_mac_normalized": peer_mac,
        "peer_ap_name": "",
        "peer_ap_mac": "",
        "peer_radio_id": None,
        "peer_radio_label": "",
        "peer_radio_mac": "",
        "peer_site": "",
        "peer_location": "",
        "peer_direction": "",
        "match_rule": "unresolved",
        "match_confidence": 0,
    }
