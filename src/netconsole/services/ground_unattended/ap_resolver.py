from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from netconsole.services.ap_identity.normalizers import (
    normalize_mac as canonical_normalize_mac,
)


class GroundApDisplayResolver:
    """把 WMESH peer/radio 标识解析为唯一的轨旁 AP 展示身份。"""

    def __init__(
        self,
        rows: Iterable[Any] = (),
        *,
        resources: Iterable[Any] = (),
    ) -> None:
        by_ap_mac: dict[str, list[dict[str, str]]] = defaultdict(list)
        by_radio_mac: dict[str, list[dict[str, str]]] = defaultdict(list)
        by_alias_mac: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in rows:
            name = str(getattr(row, "name", "") or "")
            point_code = str(getattr(row, "point_code", "") or "")
            ap_mac = _mac_key(getattr(row, "mac", ""))
            value = {
                "peer_ap_id": str(getattr(row, "id", "") or ""),
                "peer_ap_name": name or point_code or ap_mac,
                "peer_ap_mac": ap_mac,
                "station": str(getattr(row, "station", "") or ""),
                "section": str(getattr(row, "section", "") or ""),
                "display_name_source": (
                    "BASE_NAME"
                    if name
                    else "POINT_CODE"
                    if point_code
                    else "MAC_FALLBACK"
                ),
            }
            metadata = getattr(row, "base_metadata", {}) or {}
            if ap_mac:
                by_ap_mac[ap_mac].append(value)
            for radio in getattr(row, "radios", []) or []:
                radio_mac = _mac_key(getattr(radio, "bssid", ""))
                if radio_mac:
                    by_radio_mac[radio_mac].append(value)
            if isinstance(metadata, dict):
                for item in _text_values(metadata.get("bssid_aliases")):
                    radio_mac = _mac_key(item)
                    if radio_mac:
                        by_radio_mac[radio_mac].append(value)
                for item in _text_values(metadata.get("mac_aliases")):
                    alias_mac = _mac_key(item)
                    if alias_mac:
                        by_alias_mac[alias_mac].append(value)
        self._by_ap_mac, self._ambiguous_ap_macs = _unique_index(by_ap_mac)
        self._by_radio_mac, self._ambiguous_radio_macs = _unique_index(
            by_radio_mac
        )
        self._by_alias_mac, self._ambiguous_alias_macs = _unique_index(
            by_alias_mac
        )
        resource_by_ap_mac: dict[str, list[dict[str, str]]] = defaultdict(list)
        resource_by_radio_mac: dict[str, list[dict[str, str]]] = defaultdict(
            list
        )
        for detail in resources:
            ap = getattr(detail, "ap", detail)
            ap_mac = _mac_key(getattr(ap, "mac", ""))
            trackside_name = str(
                getattr(ap, "trackside_ap_name", "") or ""
            ).strip()
            point_code = str(getattr(ap, "point_code", "") or "").strip()
            configured_name = str(getattr(ap, "name", "") or "").strip()
            display_name = (
                trackside_name
                or point_code
                or configured_name
                or ap_mac
            )
            value = {
                "peer_ap_id": str(getattr(ap, "id", "") or ""),
                "peer_ap_name": display_name,
                "peer_ap_mac": ap_mac,
                "station": str(getattr(ap, "station", "") or ""),
                "section": str(getattr(ap, "section", "") or ""),
                "display_name_source": (
                    "TRACKSIDE_AP_NAME"
                    if trackside_name
                    else "POINT_CODE"
                    if point_code
                    else "AC_AP_NAME"
                    if configured_name
                    else "MAC_FALLBACK"
                ),
            }
            if ap_mac:
                resource_by_ap_mac[ap_mac].append(value)
            for radio in getattr(detail, "radios", []) or []:
                radio_mac = _mac_key(getattr(radio, "bssid", ""))
                if radio_mac:
                    resource_by_radio_mac[radio_mac].append(
                        {
                            **value,
                            "resolved_radio_id": str(
                                getattr(radio, "radio_id", "") or ""
                            ),
                            "resolution_rule": "ac_radio_bssid_exact",
                            "resolution_confidence": "100",
                        }
                    )
        (
            self._resource_by_ap_mac,
            self._ambiguous_resource_ap_macs,
        ) = _unique_index(resource_by_ap_mac)
        (
            self._resource_by_radio_mac,
            self._ambiguous_resource_radio_macs,
        ) = _unique_index(resource_by_radio_mac)

    def resolve(
        self,
        *,
        name: object = "",
        mac: object = "",
        radio_mac: object = "",
    ) -> dict[str, str]:
        name_text = str(name or "").strip()
        mac_key = _mac_key(mac)
        radio_mac_key = _mac_key(radio_mac)
        observed_base_radio_key = radio_mac_key or mac_key
        value = self._by_radio_mac.get(observed_base_radio_key)
        resolution_status = "RADIO_BSSID"
        resolution_rule = "base_radio_bssid_exact"
        if value is None and observed_base_radio_key in self._ambiguous_radio_macs:
            return _unresolved_result(name_text, mac, radio_mac, ambiguous=True)
        if value is None:
            value = self._by_alias_mac.get(mac_key)
            resolution_status = "AP_ALIAS"
            resolution_rule = "base_ap_mac_alias"
            if value is None and mac_key in self._ambiguous_alias_macs:
                return _unresolved_result(
                    name_text, mac, radio_mac, ambiguous=True
                )
        if value is not None:
            return {
                **value,
                "resolution_status": resolution_status,
                "resolution_rule": resolution_rule,
                "resolution_confidence": "100",
            }

        value = self._by_ap_mac.get(mac_key)
        if value is not None:
            return {
                **value,
                "resolution_status": "PEER_MAC_EXACT",
                "resolution_rule": "base_ap_mac_exact",
                "resolution_confidence": "92",
            }

        observed_radio_key = radio_mac_key or mac_key
        value = self._resource_by_radio_mac.get(observed_radio_key)
        resolution_status = "RADIO_BSSID"
        if (
            value is None
            and observed_radio_key in self._ambiguous_resource_radio_macs
        ):
            return _unresolved_result(name_text, mac, radio_mac, ambiguous=True)
        if value is not None:
            return {**value, "resolution_status": resolution_status}

        if mac_key in self._ambiguous_ap_macs or mac_key in self._ambiguous_resource_ap_macs:
            return _unresolved_result(name_text, mac, radio_mac, ambiguous=True)

        return _unresolved_result(name_text, mac, radio_mac, ambiguous=False)

    def enrich_parsed(self, parsed: dict[str, Any]) -> dict[str, Any]:
        result = dict(parsed)
        details = dict(result.get("details") or {})
        current_name = result.get("peer_name")
        current_mac = result.get("peer_mac") or details.get("new_peer_mac")
        current_radio_mac = details.get(
            "peer_radio_mac"
        ) or details.get("new_peer_radio_mac")
        current = self.resolve(
            name=current_name,
            mac=current_mac,
            radio_mac=current_radio_mac,
        )
        previous_name = result.get("previous_peer_name")
        previous_mac = result.get(
            "previous_peer_mac"
        ) or details.get("old_peer_mac")
        previous_radio_mac = details.get(
            "previous_peer_radio_mac"
        ) or details.get("old_peer_radio_mac")
        previous = self.resolve(
            name=previous_name,
            mac=previous_mac,
            radio_mac=previous_radio_mac,
        )
        if str(result.get("event_type") or "").upper() == (
            "MESH_ACTIVELINK_SWITCH"
        ):
            if not any(
                str(value or "").strip()
                for value in (
                    current_name,
                    current_mac,
                    current_radio_mac,
                )
            ):
                current = _no_active_link("switch_new_peer_missing")
            if details.get("old_active_link_missing"):
                previous = _no_active_link("switch_old_peer_missing")
        result.update(
            {
                "peer_name": current["peer_ap_name"],
                "peer_mac": normalize_mac(
                    result.get("peer_mac") or details.get("new_peer_mac")
                ),
                "previous_peer_name": previous["peer_ap_name"],
                "previous_peer_mac": normalize_mac(
                    result.get("previous_peer_mac")
                    or details.get("old_peer_mac")
                ),
                "station": current["station"],
                "section": current["section"],
            }
        )
        details.update(
            {
                "peer_ap_id": current["peer_ap_id"],
                "peer_ap_name": current["peer_ap_name"],
                "peer_ap_mac": current["peer_ap_mac"],
                "previous_peer_ap_id": previous["peer_ap_id"],
                "previous_peer_ap_name": previous["peer_ap_name"],
                "previous_peer_ap_mac": previous["peer_ap_mac"],
                "peer_radio_mac": normalize_mac(
                    details.get("peer_radio_mac")
                    or details.get("new_peer_radio_mac")
                ),
                "previous_peer_radio_mac": normalize_mac(
                    details.get("previous_peer_radio_mac")
                    or details.get("old_peer_radio_mac")
                ),
                "previous_station": previous["station"],
                "previous_section": previous["section"],
                "resolution_status": current["resolution_status"],
                "resolution_rule": current["resolution_rule"],
                "resolution_confidence": current["resolution_confidence"],
                "display_name_source": current["display_name_source"],
                "resolved_radio_id": current.get("resolved_radio_id", ""),
                "previous_resolution_status": previous["resolution_status"],
                "previous_resolution_rule": previous["resolution_rule"],
                "previous_resolution_confidence": previous[
                    "resolution_confidence"
                ],
                "previous_display_name_source": previous[
                    "display_name_source"
                ],
                "previous_resolved_radio_id": previous.get(
                    "resolved_radio_id", ""
                ),
            }
        )
        result["details"] = details
        return result


def normalize_mac(value: object) -> str:
    return canonical_normalize_mac(value) or ""


def _unresolved_result(
    name_text: str,
    mac: object,
    radio_mac: object,
    *,
    ambiguous: bool,
) -> dict[str, str]:
    return {
        "peer_ap_id": "",
        "peer_ap_name": name_text
        or normalize_mac(mac)
        or normalize_mac(radio_mac),
        "peer_ap_mac": "",
        "canonical_ap_mac": "",
        "station": "",
        "section": "",
        "resolution_status": "AMBIGUOUS" if ambiguous else "UNRESOLVED",
        "resolution_rule": "",
        "resolution_confidence": "",
        "identity_status": "ambiguous" if ambiguous else "unresolved",
        "identity_source": "",
        "identity_reason": "MAC 关联到多个候选" if ambiguous else "缺少明确 Radio/BSSID 映射",
        "display_name_source": "RAW_OBSERVATION",
        "resolved_radio_id": "",
    }


def _mac_key(value: object) -> str:
    return canonical_normalize_mac(value) or ""


def _mac_compact(value: object) -> str:
    return _mac_key(value).replace(":", "")


def _no_active_link(rule: str) -> dict[str, str]:
    return {
        "peer_ap_id": "",
        "peer_ap_name": "无主链路",
        "peer_ap_mac": "",
        "station": "",
        "section": "",
        "resolution_status": "NO_ACTIVE_LINK",
        "resolution_rule": rule,
        "resolution_confidence": "100",
        "display_name_source": "EVENT_STATE",
        "resolved_radio_id": "",
    }


def _text_values(value: object) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, (list, tuple, set)):
        return {str(item) for item in value if str(item or "").strip()}
    return set()


def _unique(values: list[dict[str, str]]) -> bool:
    return (
        len(
            {
                value["peer_ap_id"] or value["peer_ap_name"]
                for value in values
            }
        )
        == 1
    )


def _unique_index(
    values: dict[str, list[dict[str, str]]],
) -> tuple[dict[str, dict[str, str]], set[str]]:
    unique = {
        key: candidates[0]
        for key, candidates in values.items()
        if _unique(candidates)
    }
    return unique, set(values) - set(unique)


__all__ = ["GroundApDisplayResolver", "normalize_mac"]
