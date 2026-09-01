from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.ap_identity_index import ApIdentityMatch
from netconsole.services.ap_identity import (
    ApIdentityQueryService,
    normalize_mac_key,
)


class MeshIdentityRevisionUnstable(RuntimeError):
    """AP Identity 在一次 MESH projection 期间持续变化。"""


class MeshPeerMappingService:
    _MAX_STABLE_PROJECTION_ATTEMPTS = 2

    def __init__(self, site_name: str, paths: PathResolver) -> None:
        self.site_name = site_name
        self.paths = paths
        self._query_service: ApIdentityQueryService | None = None
        self._last_batch_identity_revision: int | None = None
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
        return _mapping_from_match(peer, match)

    def build_rows(self, peer_macs: list[str]) -> list[dict[str, object]]:
        peers = tuple(
            dict.fromkeys(
                peer
                for peer_mac in peer_macs
                if (peer := normalize_mac_key(peer_mac)) is not None
            )
        )
        if not peers:
            self._last_batch_identity_revision = None
            return []
        service = self._get_query_service()
        if service is None:
            self._last_batch_identity_revision = 0
            return [_unresolved(peer) for peer in peers]
        matches = service.resolve_peer_macs(peers, ap_role="trackside")
        revisions = {match.identity_revision for match in matches.values()}
        self._last_batch_identity_revision = (
            next(iter(revisions)) if len(revisions) == 1 else 0
        )
        return [
            _mapping_from_match(
                peer,
                matches.get(peer)
                or ApIdentityMatch(
                    status="unresolved",
                    identity_revision=self._last_batch_identity_revision,
                    query_mac=peer,
                    unresolved_reason="exact_alias_not_found",
                ),
            )
            for peer in peers
        ]

    def refresh_repository(
        self,
        repo,
        *,
        source_file_ids: set[int] | None = None,
    ) -> int:
        """用同一 Identity snapshot 完成有限次数的来源投影。

        ``source_file_ids`` 只对索引库生效，用于 fresh import 只收口本次
        新来源；不传时保持维护任务对单个 detail repo 的原有语义。
        """

        selected_source_ids = (
            {int(source_id) for source_id in source_file_ids}
            if source_file_ids is not None
            else None
        )
        last_snapshot_revision: int | None = None
        last_current_revision: int | None = None
        for attempt in range(self._MAX_STABLE_PROJECTION_ATTEMPTS):
            service = self._get_query_service()
            if service is not None:
                service.ensure_index("mesh_peer_mapping_refresh")
            revision_before_batch = self.current_identity_revision()
            if selected_source_ids is None:
                peer_macs = repo.distinct_peer_macs()
            else:
                peer_macs = repo.distinct_peer_macs(
                    source_file_ids=selected_source_ids,
                )
            rows = self.build_rows(
                peer_macs,
            )
            revision = (
                self._last_batch_identity_revision
                if self._last_batch_identity_revision is not None
                else revision_before_batch
            )
            last_snapshot_revision = revision
            if revision != revision_before_batch:
                last_current_revision = revision_before_batch
                if attempt + 1 < self._MAX_STABLE_PROJECTION_ATTEMPTS:
                    continue
                break

            if selected_source_ids is None:
                summary = repo.replace_peer_identity_mappings(
                    rows,
                    identity_index_revision=revision,
                )
            else:
                summary = repo.replace_peer_identity_mappings(
                    rows,
                    identity_index_revision=revision,
                    source_file_ids=selected_source_ids,
                )
            current_revision = self.current_identity_revision()
            last_current_revision = current_revision
            if revision != current_revision:
                if attempt + 1 < self._MAX_STABLE_PROJECTION_ATTEMPTS:
                    continue
                break

            remap_verified = (
                summary.get("validation_status") == "passed"
                and bool(summary.get("facts_unchanged"))
            )
            self.last_remap_summary = summary
            self.last_remap_summary.update(
                identity_index_revision=revision,
                identity_mapping_status=(
                    "ready" if revision > 0 and remap_verified else "unavailable"
                ),
                identity_mapped_at=datetime.now().isoformat(timespec="seconds"),
                identity_revision_stable=True,
            )
            return int(self.last_remap_summary.get("mapping_count") or len(rows))

        raise MeshIdentityRevisionUnstable(
            "MESH AP Identity revision 在 projection 期间未稳定："
            f"snapshot={last_snapshot_revision or 0}, current={last_current_revision or 0}"
        )

    def current_identity_revision(self) -> int:
        service = self._get_query_service()
        if service is None:
            return 0
        state = service.index_state() or {}
        return int(state.get("revision") or 0)

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


def _mapping_from_match(
    peer: str,
    match: ApIdentityMatch,
) -> dict[str, object]:
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
        if radio_id or "radio" in radio_rule or "bssid" in radio_rule
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
        "station_source": match.station_source,
        "peer_section": match.section,
        "section_source": match.section_source,
        "belong_type": match.belong_type,
        "belonging_source": match.matched_source,
        "peer_serial_number": match.serial_number,
        "serial_number": match.serial_number,
        "peer_location": match.mileage or match.location,
        "peer_direction": match.direction,
        "match_rule": radio_rule or "resolved",
        "match_confidence": int(match.match_confidence or 0),
        "identity_status": "matched",
        "identity_source": match.matched_source,
        "identity_reason": match.data_quality_warning or match.unresolved_reason,
        "identity_entity_id": match.matched_entity_id,
        "matched_alias_type": match.matched_alias_type,
        "query_mac_display": match.query_mac_display,
        "effective_ap_mac_display": match.effective_ap_mac,
        "ac_ap_mac": match.ac_ap_mac,
        "base_ap_mac": match.base_ap_mac,
        "data_quality_warning": match.data_quality_warning,
        "topology_warning": match.topology_warning,
    }


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
        "station_source": "unresolved",
        "peer_section": "",
        "section_source": "unresolved",
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
        "topology_warning": "",
    }
