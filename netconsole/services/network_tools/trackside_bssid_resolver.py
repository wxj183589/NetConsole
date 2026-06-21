from __future__ import annotations

from dataclasses import dataclass

from netconsole.models.wireless_scan_models import TracksideBssidMatch
from netconsole.repositories.ac_repository import AcRepository
from netconsole.services.network_tools.wireless_channel_analyzer import format_h3c_mac, normalize_mac


@dataclass(frozen=True)
class TracksideApIdentity:
    ap_name: str
    ap_mac: str
    station: str = ""
    location: str = ""
    mileage: str = ""
    direction: str = ""
    raw: dict[str, object] | None = None


class TracksideApBssidResolver:
    def __init__(self, aps: list[dict[str, object]] | None = None) -> None:
        self.aps = [_identity(row) for row in aps or [] if normalize_mac(row.get("ap_mac"))]
        self.exact_prefix11_map: dict[str, list[TracksideApIdentity]] = {}
        self.prefix10_map: dict[str, list[TracksideApIdentity]] = {}
        for ap in self.aps:
            mac = normalize_mac(ap.ap_mac)
            if not mac:
                continue
            self.exact_prefix11_map.setdefault(mac[:11], []).append(ap)
            self.prefix10_map.setdefault(mac[:10], []).append(ap)

    @classmethod
    def from_ac_repository(cls, repository: AcRepository) -> "TracksideApBssidResolver":
        rows = repository.list_all_fit_ap_resources_with_metadata()
        return cls(rows)

    def resolve(self, scanned_bssid: object) -> TracksideBssidMatch:
        bssid = normalize_mac(scanned_bssid)
        if not bssid:
            return TracksideBssidMatch(matched=False, match_status="invalid_mac")
        candidates: list[tuple[int, int, str, TracksideApIdentity]] = []
        for ap in self.exact_prefix11_map.get(bssid[:11], []):
            candidates.append((11, 1, "h3c_radio_1_prefix11", ap))
        for ap in self.prefix10_map.get(bssid[:10], []):
            ap_mac = normalize_mac(ap.ap_mac)
            if not ap_mac:
                continue
            diff = int(ap_mac[10], 16) - int(bssid[10], 16)
            if diff == 1:
                candidates.append((10, 2, "h3c_radio_2_nibble_minus_1", ap))
            elif diff == 2:
                candidates.append((10, 3, "h3c_radio_3_nibble_minus_2", ap))
        if not candidates:
            return TracksideBssidMatch(matched=False, match_status="unmatched")
        max_specificity = max(candidate[0] for candidate in candidates)
        best = [candidate for candidate in candidates if candidate[0] == max_specificity]
        if len(best) > 1:
            return TracksideBssidMatch(
                matched=False,
                match_status="multi_match",
                candidates=tuple(_candidate_payload(item[3], item[1], item[2]) for item in best),
            )
        _specificity, radio_id, rule, ap = best[0]
        return TracksideBssidMatch(
            matched=True,
            match_status="matched",
            ap_name=ap.ap_name or "-",
            ap_mac=format_h3c_mac(ap.ap_mac),
            station=ap.station,
            location=ap.location,
            mileage=ap.mileage,
            direction=ap.direction,
            radio_id=radio_id,
            match_rule=rule,
            confidence=100 if radio_id == 1 else 90,
            candidates=(_candidate_payload(ap, radio_id, rule),),
        )


def _identity(row: dict[str, object]) -> TracksideApIdentity:
    return TracksideApIdentity(
        ap_name=str(row.get("ap_name") or ""),
        ap_mac=str(row.get("ap_mac") or ""),
        station=str(row.get("site_name") or row.get("site") or ""),
        location=str(row.get("metadata_location_note") or row.get("location_note") or ""),
        mileage=str(row.get("metadata_mileage") or row.get("mileage") or ""),
        direction=str(row.get("metadata_direction") or row.get("direction") or ""),
        raw=row,
    )


def _candidate_payload(ap: TracksideApIdentity, radio_id: int, rule: str) -> dict[str, object]:
    return {
        "ap_name": ap.ap_name,
        "ap_mac": format_h3c_mac(ap.ap_mac),
        "station": ap.station,
        "location": ap.location,
        "mileage": ap.mileage,
        "direction": ap.direction,
        "radio_id": radio_id,
        "match_rule": rule,
    }
