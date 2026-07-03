from __future__ import annotations

from dataclasses import dataclass

from netconsole.core.paths import PathResolver
from netconsole.services.mesh_peer_mapping_service import MeshPeerMappingService
from netconsole.services.network_tools.wireless_channel_analyzer import format_h3c_mac, normalize_mac


@dataclass(frozen=True)
class PeerResolveResult:
    peer_mac: str
    ap_name: str | None
    site: str | None
    radio: str | None
    radio_mac: str | None
    serial_number: str | None
    source: str


class ApRadioMappingService:
    def __init__(self, site_name: str, paths: PathResolver) -> None:
        self.site_name = site_name
        self.paths = paths
        self._mesh_service = MeshPeerMappingService(site_name, paths)

    def refresh_from_fit_ap_resources(self, site_id: str | None = None) -> None:
        self._mesh_service = MeshPeerMappingService(site_id or self.site_name, self.paths)

    def resolve_peer_mac(self, peer_mac: str) -> PeerResolveResult:
        peer = normalize_mac(peer_mac)
        resolved = self._mesh_service.resolve(peer)
        if not peer or not resolved:
            return PeerResolveResult(peer, None, None, None, None, None, "unresolved")
        return PeerResolveResult(
            peer_mac=peer,
            ap_name=str(resolved.get("peer_ap_name") or "") or None,
            site=str(resolved.get("peer_site") or "") or None,
            radio=str(resolved.get("peer_radio_label") or "") or None,
            radio_mac=format_h3c_mac(str(resolved.get("peer_radio_mac") or peer)),
            serial_number=str(resolved.get("peer_serial_number") or resolved.get("serial_number") or "") or None,
            source=str(resolved.get("match_rule") or "h3c_rule"),
        )

    def resolve_many(self, peer_macs: list[str]) -> dict[str, PeerResolveResult]:
        return {normalize_mac(peer): self.resolve_peer_mac(peer) for peer in peer_macs if normalize_mac(peer)}
