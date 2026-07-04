from __future__ import annotations

import re
from dataclasses import dataclass

from netconsole.utils.interface_normalize import normalize_interface_name as display_interface_name


LLDP_SOURCE_LABELS = {
    "ac_bulk_lldp": "AC批量",
    "ap_direct_lldp": "AP直连",
    "ap_optical_diag": "光衰采集",
    "legacy_compat": "旧数据兼容",
    "merged": "合并",
    "manual": "手工",
    "unknown": "未知",
}
SOURCE_PRIORITY = {
    "ap_direct_lldp": 90,
    "ac_bulk_lldp": 60,
    "ap_optical_diag": 50,
    "legacy_compat": 30,
    "stored_previous": 10,
    "unknown": 0,
}


@dataclass(frozen=True)
class FitApLldpSnapshot:
    source: str
    local_interface: str = ""
    neighbor_name: str = ""
    neighbor_mac: str = ""
    neighbor_interface: str = ""
    collected_at: str = ""
    session_id: str = ""
    raw_log_path: str = ""


@dataclass(frozen=True)
class FitApOpticalSnapshot:
    source: str
    optical_interface: str = ""
    rx_power: str = ""
    tx_power: str = ""
    rx_low_alarm: str = ""
    rx_high_alarm: str = ""
    tx_low_alarm: str = ""
    tx_high_alarm: str = ""
    collected_at: str = ""
    session_id: str = ""
    raw_log_path: str = ""


@dataclass(frozen=True)
class FitApResolvedLink:
    lldp: FitApLldpSnapshot | None
    optical: FitApOpticalSnapshot | None
    link_match_status: str
    confidence: int


def normalize_interface_key(value: object) -> str:
    text = _compact_interface_text(display_interface_name(value))
    lower = text.casefold()
    prefixes = (
        ("tengigabitethernet", "xge"),
        ("ten-gigabitethernet", "xge"),
        ("xgigabitethernet", "xge"),
        ("gigabitethernet", "ge"),
        ("xge", "xge"),
        ("ge", "ge"),
    )
    for prefix, short in prefixes:
        if lower.startswith(prefix):
            suffix = lower[len(prefix) :]
            return f"{short}{suffix}" if suffix else short
    return lower


def normalize_mac(value: object) -> str:
    text = re.sub(r"[^0-9a-fA-F]", "", str(value or ""))
    return text.casefold() if len(text) == 12 else ""


def format_h3c_mac(value: object) -> str:
    mac = normalize_mac(value)
    return f"{mac[0:4]}-{mac[4:8]}-{mac[8:12]}" if mac else ""


def lldp_source_label(value: object) -> str:
    source = str(value or "").strip()
    if source == "merged":
        return "AP直连 + AC批量"
    return LLDP_SOURCE_LABELS.get(source, source or "未知")


def lldp_display_status(value: object) -> str:
    status = str(value or "").strip().casefold()
    return {
        "matched": "正常",
        "partial": "部分匹配",
        "conflict": "冲突",
        "unknown": "未知",
        "unmatched": "未知",
    }.get(status, status or "未知")


def resolve_fit_ap_link_info(row: dict[str, object | None]) -> dict[str, object | None]:
    data = dict(row or {})
    local_interface = _first_value(data, ("lldp_local_interface", "local_interface", "optical_interface", "interface_name"))
    neighbor_name = _first_value(data, ("lldp_neighbor_name", "neighbor_name", "lldp_neighbor", "neighbor_device_name"))
    neighbor_mac = _first_value(data, ("lldp_neighbor_mac", "neighbor_mac"))
    neighbor_interface = _first_value(data, ("lldp_neighbor_interface", "neighbor_port", "neighbor_interface", "lldp_neighbor_port"))
    optical_interface = _first_value(data, ("optical_interface", "interface_name"))
    optical_rx_power = _first_value(data, ("optical_rx_power", "neighbor_rx_power", "rx_power", "neighbor_receive_power"))
    optical_tx_power = _first_value(data, ("optical_tx_power", "tx_power", "neighbor_tx_power", "neighbor_transmit_power"))

    lldp_source = _resolve_lldp_source(data)
    data.update(
        {
            "lldp_source": lldp_source,
            "lldp_confidence": data.get("lldp_confidence") or SOURCE_PRIORITY.get(lldp_source, 0),
            "lldp_collected_at": _first_value(data, ("lldp_collected_at", "collected_at", "updated_at")),
            "lldp_local_interface": display_interface_name(local_interface) if _has_value(local_interface) else "",
            "lldp_local_interface_normalized": normalize_interface_key(local_interface),
            "lldp_neighbor_name": _text(neighbor_name),
            "lldp_neighbor_mac": format_h3c_mac(neighbor_mac) or _text(neighbor_mac),
            "lldp_neighbor_mac_normalized": normalize_mac(neighbor_mac),
            "lldp_neighbor_interface": display_interface_name(neighbor_interface) if _has_value(neighbor_interface) else "",
            "neighbor_device_name": _first_value(data, ("neighbor_device_name",)),
            "optical_interface": display_interface_name(optical_interface) if _has_value(optical_interface) else "",
            "optical_interface_normalized": normalize_interface_key(optical_interface),
            "optical_rx_power": optical_rx_power,
            "optical_tx_power": optical_tx_power,
            "optical_collected_at": _first_value(data, ("optical_collected_at", "collected_at", "updated_at")),
        }
    )
    data["lldp_match_status"] = _resolve_lldp_match_status(data)
    data["optical_match_status"] = _resolve_optical_power_status(data)
    if not _has_value(data.get("rx_power")) and _has_value(optical_rx_power):
        data["rx_power"] = optical_rx_power
    if not _has_value(data.get("tx_power")) and _has_value(optical_tx_power):
        data["tx_power"] = optical_tx_power
    return data


def normalize_lldp_payload(data: dict[str, object | None], source: str) -> dict[str, object | None]:
    local_interface = data.get("lldp_local_interface") or data.get("local_interface") or data.get("interface_name")
    neighbor_name = data.get("lldp_neighbor_name") or data.get("neighbor_name") or data.get("lldp_neighbor") or data.get("neighbor_device_name")
    neighbor_mac = data.get("lldp_neighbor_mac") or data.get("neighbor_mac")
    neighbor_interface = data.get("lldp_neighbor_interface") or data.get("neighbor_interface")
    result = {
        "lldp_source": source,
        "lldp_confidence": SOURCE_PRIORITY.get(source, 0),
        "lldp_collected_at": data.get("lldp_collected_at") or data.get("collected_at"),
        "lldp_local_interface": display_interface_name(local_interface) if _has_value(local_interface) else "",
        "lldp_local_interface_normalized": normalize_interface_key(local_interface),
        "lldp_neighbor_name": "" if _is_unknown_neighbor_name(neighbor_name) else _text(neighbor_name),
        "lldp_neighbor_mac": format_h3c_mac(neighbor_mac) or _text(neighbor_mac),
        "lldp_neighbor_mac_normalized": normalize_mac(neighbor_mac),
        "lldp_neighbor_interface": display_interface_name(neighbor_interface) if _has_value(neighbor_interface) else "",
    }
    result["lldp_match_status"] = _resolve_lldp_match_status(result)
    return result


def merge_lldp_payload(existing: dict[str, object | None], incoming: dict[str, object | None]) -> dict[str, object | None]:
    current = normalize_lldp_payload(existing, str(existing.get("lldp_source") or "stored_previous"))
    new = normalize_lldp_payload(incoming, str(incoming.get("lldp_source") or incoming.get("source") or "unknown"))
    result = {field: existing.get(field) for field in _LLDP_FIELDS}
    current_priority = int(current.get("lldp_confidence") or 0)
    new_priority = int(new.get("lldp_confidence") or 0)
    prefer_new = new_priority >= current_priority

    conflict = _has_lldp_conflict(current, new)
    for field in _LLDP_FIELDS:
        old_value = current.get(field)
        new_value = new.get(field)
        if field == "lldp_neighbor_name":
            result[field] = _best_neighbor_name(old_value, new_value, prefer_new)
        elif field in {"lldp_source", "lldp_confidence", "lldp_collected_at"}:
            result[field] = _merged_meta_value(field, current, new, prefer_new)
        elif _has_value(new_value) and (prefer_new or not _has_value(old_value)):
            result[field] = new_value
        elif _has_value(old_value):
            result[field] = old_value
    current_source = str(current.get("lldp_source") or "")
    new_source = str(new.get("lldp_source") or "")
    if current_source not in {"", "stored_previous", "unknown"} and new_source and current_source != new_source and not conflict:
        result["lldp_source"] = "merged"
    result["lldp_match_status"] = "conflict" if conflict else _resolve_lldp_match_status(result)
    return result


def resolve_optical_match_status(lldp: dict[str, object | None], optical: dict[str, object | None]) -> str:
    lldp_key = normalize_interface_key(lldp.get("lldp_local_interface") or lldp.get("interface_name"))
    optical_key = normalize_interface_key(optical.get("optical_interface") or optical.get("interface_name"))
    rx_power = _first_value(optical, ("optical_rx_power", "neighbor_rx_power", "rx_power", "neighbor_receive_power"))
    if not _has_value(rx_power):
        return "unknown"
    if lldp_key and optical_key:
        return "matched" if lldp_key == optical_key else "conflict"
    return "partial"


def optical_payload_from_row(row: dict[str, object | None]) -> dict[str, object | None]:
    interface = row.get("optical_interface") or row.get("interface_name")
    result = {
        "optical_interface": display_interface_name(interface),
        "optical_interface_normalized": normalize_interface_key(interface),
        "optical_rx_power": _first_value(row, ("optical_rx_power", "neighbor_rx_power", "rx_power", "neighbor_receive_power")),
        "optical_tx_power": _first_value(row, ("optical_tx_power", "tx_power", "neighbor_tx_power", "neighbor_transmit_power")),
        "optical_collected_at": row.get("collected_at"),
    }
    result["optical_match_status"] = row.get("link_match_status") or row.get("optical_match_status") or resolve_optical_match_status(row, result)
    return result


def _compact_interface_text(value: object) -> str:
    text = str(value or "").strip().rstrip(":")
    return re.sub(r"(?i)^(ge|gigabitethernet|xge|xgigabitethernet|ten-gigabitethernet|tengigabitethernet)\s+", lambda m: m.group(1), text)


def _has_lldp_conflict(current: dict[str, object | None], new: dict[str, object | None]) -> bool:
    for field in ("lldp_neighbor_mac_normalized", "lldp_local_interface_normalized"):
        if _has_value(current.get(field)) and _has_value(new.get(field)) and current.get(field) != new.get(field):
            return True
    old_neighbor_if = normalize_interface_key(current.get("lldp_neighbor_interface"))
    new_neighbor_if = normalize_interface_key(new.get("lldp_neighbor_interface"))
    return bool(old_neighbor_if and new_neighbor_if and old_neighbor_if != new_neighbor_if)


def _best_neighbor_name(old_value: object, new_value: object, prefer_new: bool) -> object:
    old_valid = _has_value(old_value) and not _is_unknown_neighbor_name(old_value)
    new_valid = _has_value(new_value) and not _is_unknown_neighbor_name(new_value)
    if new_valid and (prefer_new or not old_valid):
        return new_value
    if old_valid:
        return old_value
    return new_value if new_valid else old_value


def _merged_meta_value(field: str, current: dict[str, object | None], new: dict[str, object | None], prefer_new: bool) -> object:
    if field == "lldp_source":
        return new.get(field) if prefer_new else current.get(field)
    if field == "lldp_confidence":
        return max(int(current.get(field) or 0), int(new.get(field) or 0))
    return new.get(field) or current.get(field)


def _is_unknown_neighbor_name(value: object) -> bool:
    text = str(value or "").strip().casefold()
    return text in {"", "n/a", "na", "-", "none", "null", "unknown", "未知", "未匹配"}


def _has_value(value: object) -> bool:
    text = str(value or "").strip()
    return text.casefold() not in {"", "-", "n/a", "na", "none", "null", "unknown"} and text not in {"未知", "未匹配"}


def _text(value: object) -> str:
    return str(value or "").strip()


def _first_value(data: dict[str, object | None], fields: tuple[str, ...]) -> object:
    for field in fields:
        value = data.get(field)
        if _has_value(value):
            return value
    return ""


def _resolve_lldp_source(data: dict[str, object | None]) -> str:
    source = str(data.get("lldp_source") or "").strip()
    if _has_value(source):
        return source
    if any(_has_value(data.get(field)) for field in ("lldp_neighbor", "neighbor_name", "neighbor_mac", "neighbor_interface", "neighbor_port")):
        return "legacy_compat"
    if any(_has_value(data.get(field)) for field in ("neighbor_rx_power", "rx_power", "optical_rx_power")):
        return "ap_optical_diag"
    return "unknown"


def _resolve_lldp_match_status(data: dict[str, object | None]) -> str:
    existing = str(data.get("lldp_match_status") or "").strip().casefold()
    if existing == "conflict":
        return "conflict"
    if _has_value(data.get("lldp_neighbor_mac_normalized")) or _has_value(data.get("lldp_neighbor_mac")) or _has_value(data.get("lldp_neighbor_interface")):
        return "matched"
    if _has_value(data.get("lldp_neighbor_name")):
        return "partial"
    return "unknown"


def _resolve_optical_power_status(data: dict[str, object | None]) -> str:
    existing = str(data.get("optical_match_status") or data.get("link_match_status") or "").strip().casefold()
    if existing == "conflict":
        return "conflict"
    if not _has_value(data.get("optical_rx_power")):
        return "unknown"
    local_key = normalize_interface_key(data.get("lldp_local_interface") or data.get("local_interface"))
    optical_key = normalize_interface_key(data.get("optical_interface") or data.get("interface_name"))
    if local_key and optical_key:
        return "matched" if local_key == optical_key else "conflict"
    return "partial"


_LLDP_FIELDS = (
    "lldp_source",
    "lldp_confidence",
    "lldp_collected_at",
    "lldp_local_interface",
    "lldp_local_interface_normalized",
    "lldp_neighbor_name",
    "lldp_neighbor_mac",
    "lldp_neighbor_mac_normalized",
    "lldp_neighbor_interface",
    "lldp_match_status",
)
