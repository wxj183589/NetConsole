from __future__ import annotations

import re
from dataclasses import dataclass


def normalize_mac(value: object) -> str:
    text = re.sub(r"[^0-9a-fA-F]", "", str(value or "")).casefold()
    return text if len(text) == 12 else ""


@dataclass(frozen=True)
class APRecord:
    ap_mac: str
    ap_name: str
    site_id: str = ""
    site: str = ""


@dataclass(frozen=True)
class RadioRecord:
    ap_mac: str
    radio_id: int
    bssid: str


@dataclass(frozen=True)
class MeshPeerRecord:
    peer_mac: str
    ap_mac: str


class ApMappingService:
    def __init__(self) -> None:
        self.ap_table: dict[str, APRecord] = {}
        self.radio_table: dict[str, RadioRecord] = {}
        self.peer_table: dict[str, MeshPeerRecord] = {}

    def upsert_ap(self, ap_mac: object, ap_name: str, site_id: str = "", site: str = "") -> None:
        mac = normalize_mac(ap_mac)
        if mac:
            self.ap_table[mac] = APRecord(mac, ap_name, site_id, site)

    def upsert_radio(self, ap_mac: object, radio_id: int, bssid: object) -> None:
        ap = normalize_mac(ap_mac)
        bssid_mac = normalize_mac(bssid)
        if ap and bssid_mac:
            self.radio_table[bssid_mac] = RadioRecord(ap, int(radio_id), bssid_mac)

    def upsert_peer(self, peer_mac: object, ap_mac: object) -> None:
        peer = normalize_mac(peer_mac)
        ap = normalize_mac(ap_mac)
        if peer and ap:
            self.peer_table[peer] = MeshPeerRecord(peer, ap)

    def resolve_peer(self, peer_mac: object) -> dict[str, object]:
        peer = normalize_mac(peer_mac)
        peer_record = self.peer_table.get(peer)
        radio = self.radio_table.get(peer)
        ap_mac = peer_record.ap_mac if peer_record else (radio.ap_mac if radio else peer)
        ap = self.ap_table.get(ap_mac)
        if ap is None:
            return {"ap_name": "", "site": "", "site_id": "", "radio": radio.radio_id if radio else None, "ap_mac": ap_mac}
        return {
            "ap_name": ap.ap_name,
            "site": ap.site or ap.site_id,
            "site_id": ap.site_id,
            "radio": radio.radio_id if radio else None,
            "ap_mac": ap.ap_mac,
        }
