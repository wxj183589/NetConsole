from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import re

from netconsole.models.wireless_scan_models import TracksideBssidMatch
from netconsole.repositories.ac_repository import AcRepository
from netconsole.services.network_tools.wireless_channel_analyzer import format_h3c_mac, normalize_mac
from netconsole.utils.station_normalize import normalize_station_value


@dataclass(frozen=True)
class TracksideApIdentity:
    ap_name: str
    ap_mac: str
    station: str = ""
    section: str = ""
    belong_type: str = "unknown"
    belonging_source: str = ""
    serial_number: str = ""
    location: str = ""
    mileage: str = ""
    direction: str = ""
    radio_macs: tuple[tuple[str, int | None, str], ...] = ()
    peer_names: tuple[str, ...] = ()
    raw: dict[str, object] | None = None


class TracksideApBssidResolver:
    def __init__(self, aps: list[dict[str, object]] | None = None) -> None:
        self.aps = [ap for ap in (_identity(row) for row in aps or []) if normalize_mac(ap.ap_mac) or ap.ap_name]
        self.radio_mac_map: dict[str, list[tuple[TracksideApIdentity, int | None, str]]] = defaultdict(list)
        self.radio1_map: dict[str, list[TracksideApIdentity]] = defaultdict(list)
        self.radio2_map: dict[str, list[TracksideApIdentity]] = defaultdict(list)
        self.ap_mac_map: dict[str, list[TracksideApIdentity]] = defaultdict(list)
        self.peer_name_map: dict[str, list[TracksideApIdentity]] = defaultdict(list)
        for ap in self.aps:
            for peer_name in ap.peer_names:
                key = _name_key(peer_name)
                if key:
                    self.peer_name_map[key].append(ap)
            mac = normalize_mac(ap.ap_mac)
            if not mac:
                continue
            self.ap_mac_map[mac].append(ap)
            self.radio1_map[mac[:11]].append(ap)
            if mac[10] != "f":
                radio2 = f"{mac[:10]}{int(mac[10], 16) + 1:x}"
                self.radio2_map[radio2].append(ap)
            for radio_mac, radio_id, source in ap.radio_macs:
                self.radio_mac_map[radio_mac].append((ap, radio_id, source))

    @classmethod
    def from_ac_repository(cls, repository: AcRepository) -> "TracksideApBssidResolver":
        rows = repository.list_all_fit_ap_resources_with_metadata()
        rows.extend(_extension_identity_rows(repository, rows))
        return cls(rows)

    def resolve(self, scanned_bssid: object, peer_name: object | None = None) -> TracksideBssidMatch:
        bssid = normalize_mac(scanned_bssid)
        if not bssid:
            return TracksideBssidMatch(matched=False, match_status="invalid_mac")

        match = self._single_match([(ap, radio_id, source) for ap, radio_id, source in self.radio_mac_map.get(bssid, [])])
        if match is not None:
            return match

        h3c_candidates = [(ap, 1, "h3c_radio_1_ap_mac_prefix11") for ap in self.radio1_map.get(bssid[:11], [])]
        h3c_candidates.extend((ap, 2, "h3c_radio_2_ap_mac_nibble_plus_1") for ap in self.radio2_map.get(bssid[:11], []))
        match = self._single_match(h3c_candidates)
        if match is not None:
            return match

        match = self._single_match([(ap, None, "fit_ap_ap_mac_exact") for ap in self.ap_mac_map.get(bssid, [])])
        if match is not None:
            return match

        key = _name_key(peer_name)
        if key:
            match = self._single_match([(ap, None, "mesh_peer_name_ap_name_exact") for ap in self.peer_name_map.get(key, [])])
            if match is not None:
                return match
        return TracksideBssidMatch(matched=False, match_status="unmatched")

    def _single_match(self, candidates: list[tuple[TracksideApIdentity, int | None, str]]) -> TracksideBssidMatch | None:
        if not candidates:
            return None
        if len(candidates) > 1:
            return TracksideBssidMatch(
                matched=False,
                match_status="multi_match",
                candidates=tuple(_candidate_payload(ap, radio_id, rule) for ap, radio_id, rule in candidates),
            )
        ap, radio_id, rule = candidates[0]
        return TracksideBssidMatch(
            matched=True,
            match_status="matched",
            ap_name=ap.ap_name or "-",
            ap_mac=format_h3c_mac(ap.ap_mac),
            station=ap.station,
            section=ap.section,
            belong_type=ap.belong_type,
            belonging_source=ap.belonging_source,
            serial_number=ap.serial_number,
            location=ap.location,
            mileage=ap.mileage,
            direction=ap.direction,
            radio_id=radio_id,
            match_rule=rule,
            confidence=100 if rule.startswith(("radio_mac", "bssid", "mesh_peer_radio")) else 90,
            candidates=(_candidate_payload(ap, radio_id, rule),),
        )


def _identity(row: dict[str, object]) -> TracksideApIdentity:
    ap_name = str(row.get("ap_name") or "")
    station = normalize_station_value(row) or str(row.get("station_name") or "")
    section = str(row.get("section_name") or row.get("belong_section") or row.get("metadata_belong_section") or "")
    belong_type = _belong_type(row, station, section)
    return TracksideApIdentity(
        ap_name=ap_name,
        ap_mac=str(row.get("ap_mac") or row.get("ap_mac_display") or row.get("ap_mac_norm") or ""),
        station=station,
        section=section,
        belong_type=belong_type,
        belonging_source=str(row.get("_identity_source") or row.get("extension_match_status") or "fit_ap"),
        serial_number=_serial_number(row),
        location=str(row.get("metadata_location_note") or row.get("location_note") or ""),
        mileage=str(row.get("metadata_mileage") or row.get("mileage") or row.get("mileage_text") or ""),
        direction=str(row.get("metadata_direction") or row.get("direction") or ""),
        radio_macs=_extract_radio_macs(row),
        peer_names=tuple(value for value in (ap_name, str(row.get("peer_name") or ""), str(row.get("mesh_peer_name") or "")) if value),
        raw=row,
    )


def _candidate_payload(ap: TracksideApIdentity, radio_id: int | None, rule: str) -> dict[str, object]:
    return {
        "ap_name": ap.ap_name,
        "ap_mac": format_h3c_mac(ap.ap_mac),
        "station": ap.station,
        "section": ap.section,
        "belong_type": ap.belong_type,
        "belonging_source": ap.belonging_source,
        "serial_number": ap.serial_number,
        "location": ap.location,
        "mileage": ap.mileage,
        "direction": ap.direction,
        "radio_id": radio_id,
        "match_rule": rule,
    }


def _extract_radio_macs(row: dict[str, object]) -> tuple[tuple[str, int | None, str], ...]:
    result: list[tuple[str, int | None, str]] = []
    ap_mac = normalize_mac(row.get("ap_mac"))
    radio_keys = {
        "radio_mac",
        "bssid",
        "peer_radio_mac",
        "mesh_peer_radio_mac",
        "mesh_peer_mac",
        "local_mac",
        "rid1_mac",
        "rid2_mac",
        "radio1_mac",
        "radio2_mac",
    }
    for key, value in row.items():
        key_l = str(key).lower()
        if key_l not in radio_keys and not (("radio" in key_l or "bssid" in key_l) and "mac" in key_l):
            continue
        mac = normalize_mac(value)
        if not mac or mac == ap_mac:
            continue
        result.append((mac, _radio_id_from_key(key_l), key_l))
    return tuple(dict.fromkeys(result))


def _extension_identity_rows(repository: AcRepository, fit_rows: list[dict[str, object | None]]) -> list[dict[str, object]]:
    try:
        extensions = repository.list_ap_extension_points()
    except Exception:
        return []
    known_macs = {normalize_mac(row.get("ap_mac")) for row in fit_rows if normalize_mac(row.get("ap_mac"))}
    known_names = {str(row.get("ap_name") or "").strip().casefold() for row in fit_rows if str(row.get("ap_name") or "").strip()}
    rows: list[dict[str, object]] = []
    for extension in extensions:
        mac = normalize_mac(extension.get("ap_mac_display") or extension.get("ap_mac_norm"))
        name = str(extension.get("ap_name") or "").strip()
        if mac and mac in known_macs:
            continue
        if not mac and name and name.casefold() in known_names:
            continue
        row = dict(extension)
        row["ap_mac"] = extension.get("ap_mac_display") or extension.get("ap_mac_norm") or ""
        row["site_name"] = extension.get("station_name") or ""
        row["_identity_source"] = "ap_metadata"
        rows.append(row)
    return rows


def _belong_type(row: dict[str, object], station: str, section: str) -> str:
    value = str(row.get("belong_type") or row.get("metadata_belong_type") or "").strip().casefold()
    if value:
        return value
    if str(row.get("yard_name") or row.get("area_name") or "").strip():
        return "yard"
    if section:
        return "section"
    if station:
        return "station"
    return "unknown"


def _radio_id_from_key(key: str) -> int | None:
    match = re.search(r"(?:rid|radio)[_-]?([12])", key)
    return int(match.group(1)) if match else None


def _serial_number(row: dict[str, object]) -> str:
    for key in ("serial_number", "serial", "sn", "device_sn"):
        text = str(row.get(key) or "").strip()
        if text:
            return text
    return ""


def _name_key(value: object) -> str:
    return str(value or "").strip().casefold()
