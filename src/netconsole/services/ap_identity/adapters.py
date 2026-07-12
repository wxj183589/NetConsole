from __future__ import annotations

import re
from collections.abc import Mapping

from .models import (
    ApIdentityCandidate,
    ApObservation,
    CanonicalApIdentity,
    CanonicalApLocation,
    CanonicalApRadioIdentity,
)
from .normalizers import normalize_ap_name, normalize_identifier, normalize_mac, normalize_mileage, parse_line_direction


def candidate_from_ap_entity_row(row: Mapping[str, object]) -> ApIdentityCandidate:
    return _candidate_from_row(row, source="ap_entity")


def candidate_from_fit_ap_resource_row(row: Mapping[str, object]) -> ApIdentityCandidate:
    return _candidate_from_row(row, source="fit_ap_resource")


def candidate_from_extension_row(row: Mapping[str, object]) -> ApIdentityCandidate:
    return _candidate_from_row(row, source="ap_extension")


def observation_from_mesh_peer(row: Mapping[str, object]) -> ApObservation:
    return _observation_from_row(row, source="mesh_peer")


def observation_from_online_mr_sample(row: Mapping[str, object]) -> ApObservation:
    return _observation_from_row(row, source="online_mr")


def observation_from_wireless_bssid(row: Mapping[str, object]) -> ApObservation:
    return _observation_from_row(row, source="wireless_bssid")


def _candidate_from_row(row: Mapping[str, object], *, source: str) -> ApIdentityCandidate:
    raw = dict(row)
    ap_mac = normalize_mac(_first(raw, "ap_mac", "ap_mac_norm", "ap_mac_display"))
    ap_name = normalize_ap_name(_first(raw, "ap_name", "name"))
    ac_uuid = normalize_identifier(_first(raw, "ac_device_uuid", "ac_uuid"))
    ap_uuid = normalize_identifier(_first(raw, "ap_uuid"))
    ap_id = normalize_identifier(_first(raw, "apid", "ap_id"))
    line_value = _first(raw, "line_side", "line", "direction", "mileage", "mileage_text")
    line, inferred_direction = parse_line_direction(line_value)
    identity = CanonicalApIdentity(
        ap_uuid=ap_uuid,
        ap_mac=ap_mac,
        ap_name=ap_name,
        ac_uuid=ac_uuid,
        ap_id=ap_id,
        serial_number=normalize_identifier(_first(raw, "serial_number", "serial", "sn", "device_sn")),
        site_id=normalize_identifier(_first(raw, "site_id")),
        source=source,
        source_ref=_source_ref(raw),
    )
    location = CanonicalApLocation(
        site=normalize_ap_name(_first(raw, "site", "site_name")),
        station=normalize_ap_name(_first(raw, "station", "station_name", "ownership_station")),
        section=normalize_ap_name(_first(raw, "section", "section_name", "belong_section")),
        mileage=normalize_mileage(_first(raw, "mileage", "mileage_text", "milestone")),
        line=normalize_ap_name(_first(raw, "line_side", "line")) or line,
        direction=normalize_ap_name(_first(raw, "direction")) or inferred_direction,
        ownership_type=normalize_identifier(_first(raw, "ownership_type", "belong_type")),
        system_type=normalize_identifier(_first(raw, "system_type")),
        network_domain=normalize_identifier(_first(raw, "network_domain")),
    )
    return ApIdentityCandidate(identity=identity, radios=_radios_from_row(raw, identity), location=location, raw=raw)


def _observation_from_row(row: Mapping[str, object], *, source: str) -> ApObservation:
    raw = dict(row)
    return ApObservation(
        ap_uuid=normalize_identifier(_first(raw, "ap_uuid")),
        ap_id=normalize_identifier(_first(raw, "apid", "ap_id")),
        ap_mac=normalize_mac(_first(raw, "ap_mac", "peer_ap_mac")),
        ap_name=normalize_ap_name(_first(raw, "ap_name", "peer_ap_name", "resolved_peer_name", "peer_name")),
        peer_mac=normalize_mac(_first(raw, "peer_mac", "peer_mac_normalized", "peer_mac_raw")),
        peer_radio_mac=normalize_mac(_first(raw, "peer_radio_mac")),
        radio_mac=normalize_mac(_first(raw, "radio_mac")),
        bssid=normalize_mac(_first(raw, "bssid", "bbssid")),
        ac_uuid=normalize_identifier(_first(raw, "ac_device_uuid", "ac_uuid")),
        device_uuid=normalize_identifier(_first(raw, "device_uuid", "switch_uuid")),
        interface_name=normalize_identifier(_first(raw, "interface_name", "switch_interface", "local_interface")),
        site=normalize_ap_name(_first(raw, "site", "site_name")),
        station=normalize_ap_name(_first(raw, "station", "station_name", "belong_station")),
        section=normalize_ap_name(_first(raw, "section", "section_name", "belong_section")),
        mileage=normalize_mileage(_first(raw, "mileage", "mileage_text", "milestone")),
        source=source,
        source_ref=normalize_identifier(_first(raw, "source_ref", "source_file_id", "source_file", "id")),
        raw=raw,
    )


def _radios_from_row(row: Mapping[str, object], identity: CanonicalApIdentity) -> tuple[CanonicalApRadioIdentity, ...]:
    radios: dict[int | None, dict[str, object | None]] = {}
    generic_radio_id = _int_or_none(_first(row, "radio_id", "radio_index", "rid", "radio"))
    for key, value in row.items():
        key_text = str(key).casefold()
        if not any(token in key_text for token in ("radio", "bssid", "bbssid", "rid")):
            continue
        mac = normalize_mac(value)
        if not mac:
            continue
        radio_id = _radio_id_from_key(key_text) or generic_radio_id
        payload = radios.setdefault(radio_id, {"radio_mac": None, "bssid": None, "bbssid": None, "band": None})
        if "bbssid" in key_text:
            payload["bbssid"] = mac
        elif "bssid" in key_text:
            payload["bssid"] = mac
        elif "mac" in key_text:
            payload["radio_mac"] = mac
    if generic_radio_id is not None and generic_radio_id in radios:
        radios[generic_radio_id]["band"] = normalize_identifier(_first(row, "band", "radio_band"))
    return tuple(
        CanonicalApRadioIdentity(
            radio_id=radio_id,
            radio_mac=payload["radio_mac"],
            bssid=payload["bssid"],
            bbssid=payload["bbssid"],
            band=payload["band"],
            ap_uuid=identity.ap_uuid,
            ap_mac=identity.ap_mac,
        )
        for radio_id, payload in sorted(radios.items(), key=lambda item: (-1 if item[0] is None else item[0]))
    )


def _source_ref(row: Mapping[str, object]) -> str | None:
    explicit = normalize_identifier(_first(row, "source_ref"))
    if explicit:
        return explicit
    row_id = normalize_identifier(_first(row, "id"))
    return f"row:{row_id}" if row_id else None


def _first(row: Mapping[str, object], *keys: str) -> object | None:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _radio_id_from_key(key: str) -> int | None:
    match = re.search(r"(?:rid|radio)[_-]?([0-9]+)", key)
    return int(match.group(1)) if match else None


def _int_or_none(value: object) -> int | None:
    try:
        text = str(value or "").strip()
        return int(text) if text else None
    except ValueError:
        return None
