"""Parser for H3C ``display wlan ap ... verbose`` output.

The AC firmware has changed labels and whitespace between V7/V9 releases.  The
parser therefore treats the output as a sequence of labelled fields instead of
depending on a fixed column layout.  Unknown fields are retained in
``extra_fields`` so a newer firmware does not silently discard data.
"""

from __future__ import annotations

import re
from typing import Any


_NA_VALUES = {"", "-", "--", "n/a", "na", "not configured", "not-configured", "none", "null"}
_AP_START_RE = re.compile(r"^\s*AP\s+name\s*[:=]\s*(.*?)\s*$", re.IGNORECASE)
_RADIO_RE = re.compile(r"^\s*Radio(?:\s+ID)?\s*[:=]?\s*([0-9]+)\s*:?\s*$", re.IGNORECASE)
_RADIO_ID_RE = re.compile(r"^\s*Radio\s+ID\s*[:=]\s*([0-9]+)\s*$", re.IGNORECASE)
_FIELD_RE = re.compile(r"^\s*([^:=]{1,80}?)\s*(?::|=)\s*(.*?)\s*$")
_KNOWN_RADIO_LABEL_RE = re.compile(
    r"^(?:base\s+bssid|state|type|radio\s+type|antenna\s+type|channel\s+bandwidth|"
    r"operating\s+bandwidth|secondary\s+channel\s+mode|mimo|channel|channel\s+usage|"
    r"max\s+power|noise\s+floor|distance|beacon\s+interval|protection\s+mode|"
    r"twt\s+negotiation|radar[- ]?detect)",
    re.IGNORECASE,
)


def parse_wlan_ap_verbose(output: str) -> list[dict[str, Any]]:
    """Parse one or more AP verbose blocks."""

    rows: list[dict[str, Any]] = []
    ap: dict[str, Any] | None = None
    radio: dict[str, Any] | None = None
    current_field: tuple[dict[str, Any], str] | None = None

    def finish_radio() -> None:
        nonlocal radio
        if ap is not None and radio is not None and radio.get("radio_id") is not None:
            ap.setdefault("radio_details", []).append(radio)
        radio = None

    def finish_ap() -> None:
        nonlocal ap, current_field
        finish_radio()
        if ap is not None and _clean_value(ap.get("ap_name")):
            ap["radios"] = list(ap.get("radio_details") or [])
            ap.setdefault("extra_fields", {})
            rows.append(ap)
        ap = None
        current_field = None

    for raw_line in str(output or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        if "---- more ----" in stripped.casefold() or stripped.startswith(("<", "[")):
            continue
        if re.fullmatch(r"[-=_]{3,}", stripped):
            continue

        ap_match = _AP_START_RE.match(line)
        if ap_match:
            finish_ap()
            ap = {"ap_name": _clean_value(ap_match.group(1)), "radio_details": [], "extra_fields": {}}
            current_field = None
            continue

        if ap is None:
            continue

        radio_match = _RADIO_ID_RE.match(line) or _RADIO_RE.match(line)
        if radio_match:
            finish_radio()
            radio = {"radio_id": int(radio_match.group(1)), "extra_fields": {}}
            current_field = None
            continue

        parsed = _split_field(line)
        if parsed is None:
            if current_field is not None:
                target, field = current_field
                continuation = _clean_value(stripped)
                if continuation:
                    target[field] = f"{target.get(field, '')} {continuation}".strip()
            continue
        label, value = parsed
        target = radio if radio is not None and _looks_like_radio_label(label) else ap
        mapped = _map_field(label, radio is not None and target is radio)
        if mapped is None:
            target.setdefault("extra_fields", {})[label.strip()] = _clean_value(value)
            current_field = (target, label.strip())
            continue
        value_text = _clean_value(value)
        if target is radio:
            _store_radio_field(target, mapped, value_text)
        else:
            _store_ap_field(target, mapped, value_text)
        current_field = (target, mapped)

    finish_ap()
    return rows


def parse_wlan_ap_verbose_output(output: str) -> list[dict[str, Any]]:
    return parse_wlan_ap_verbose(output)


def parse_wlan_ap_verbose_blocks(output: str) -> list[dict[str, Any]]:
    return parse_wlan_ap_verbose(output)


def _split_field(line: str) -> tuple[str, str] | None:
    match = _FIELD_RE.match(line)
    if match:
        label, value = match.group(1).strip(), match.group(2).strip()
        if label and (value or ":" in line or "=" in line):
            return label, value
    # Some releases align labels with spaces but omit a colon.
    if "  " in line:
        parts = re.split(r"\s{2,}", line.strip(), maxsplit=1)
        if len(parts) == 2 and _looks_like_known_label(parts[0]):
            return parts[0].strip(), parts[1].strip()
    return None


def _looks_like_known_label(label: str) -> bool:
    normalized = _normalize_label(label)
    return normalized.startswith(("ap", "state", "model", "serial", "mac", "ip", "radio", "channel", "software", "hardware", "boot", "system", "capwap", "tunnel", "connection", "region", "backup", "ready", "online", "latest", "current", "power", "map", "forward", "discovery", "description", "remote", "energysaving", "ctrl", "data", "base", "antenna", "operating", "secondary", "mimo", "noise", "distance", "beacon", "protection", "twt", "radar"))


def _looks_like_radio_label(label: str) -> bool:
    return bool(_KNOWN_RADIO_LABEL_RE.match(_normalize_label_for_regex(label)))


def _map_field(label: str, is_radio: bool) -> str | None:
    key = _normalize_label_for_regex(label)
    if is_radio:
        radio_map = {
            "radio_id": r"^(?:radio\s+)?id$",
            "base_bssid": r"^base\s+bssid$|^bssid$",
            "state": r"^state$",
            "radio_type": r"^(?:radio\s+)?type$",
            "antenna_type": r"^antenna\s+type$",
            "channel_bandwidth": r"^channel\s+bandwidth$",
            "operating_bandwidth": r"^operating\s+bandwidth$",
            "secondary_channel_mode": r"^secondary\s+channel\s+mode$",
            "mimo": r"^mimo$",
            "channel": r"^channel$",
            "channel_usage": r"^channel\s+usage$",
            "max_power": r"^max\s+power$",
            "noise_floor": r"^noise\s+floor$",
            "distance": r"^distance$",
            "beacon_interval": r"^beacon\s+interval$",
            "protection_mode": r"^protection\s+mode$",
            "twt_negotiation": r"^twt\s+negotiation$",
            "radar_detect": r"^radar[- ]?detect$",
        }
        for field, pattern in radio_map.items():
            if re.fullmatch(pattern, key, re.IGNORECASE):
                return field
        return None
    compact = re.sub(r"[^a-z0-9]", "", key.casefold())
    aliases = {
        "apname": "ap_name",
        "apid": "ap_id",
        "apgroupname": "ap_group_name",
        "groupname": "ap_group_name",
        "state": "state",
        "backuptype": "backup_type",
        "readyforswitchover": "ready_for_switchover",
        "onlinetime": "online_time",
        "systemuptime": "system_uptime",
        "model": "model",
        "regioncode": "region_code",
        "regioncodelock": "region_code_lock",
        "serialid": "serial_id",
        "serialnumber": "serial_id",
        "macaddress": "mac_address",
        "ipaddress": "ip_address",
        "udpcontrolportnumber": "udp_control_port_number",
        "udpdataportnumber": "udp_data_port_number",
        "hwversion": "hardware_version",
        "hardwareversion": "hardware_version",
        "swversion": "software_version",
        "softwareversion": "software_version",
        "bootversion": "boot_version",
        "mapfile": "map_file",
        "forwardingmode": "forwarding_mode",
        "powerlevel": "power_level",
        "powerinfo": "power_info",
        "description": "description",
        "capwapdatatunnelstatus": "capwap_data_tunnel_status",
        "discoverytype": "discovery_type",
        "lastrebootreason": "last_reboot_reason",
        "latestipaddress": "latest_ip_address",
        "currentacip": "current_ac_ip",
        "tunneldownreason": "tunnel_down_reason",
        "connectioncount": "connection_count",
        "ctrltunnelencryptionstate": "control_tunnel_encryption_state",
        "controltunnelencryptionstate": "control_tunnel_encryption_state",
        "datatunnelencryptionstate": "data_tunnel_encryption_state",
        "remoteconfiguration": "remote_configuration",
        "energysavinglevel": "energy_saving_level",
        "aptype": "ap_type",
    }
    return aliases.get(compact)


def _store_ap_field(target: dict[str, Any], field: str, value: str) -> None:
    if field == "channel":
        channel, mode = _split_channel(value)
        target["channel"] = channel
        if mode:
            target["channel_mode"] = mode
        return
    target[field] = value


def _store_radio_field(target: dict[str, Any], field: str, value: str) -> None:
    if field == "channel":
        channel, mode = _split_channel(value)
        target["channel"] = channel
        if mode:
            target["channel_mode"] = mode
        return
    if field in {"max_power", "noise_floor"}:
        number, unit = _split_number_unit(value)
        target[field] = number
        if unit:
            target[f"{field}_unit"] = unit
        return
    target[field] = value


def _split_channel(value: str) -> tuple[str, str]:
    match = re.match(r"^\s*([^\s(]+)\s*(?:\(([^)]+)\))?", value)
    if not match:
        return value, ""
    return match.group(1), (match.group(2) or "").strip()


def _split_number_unit(value: str) -> tuple[str, str]:
    match = re.match(r"^\s*([-+]?\d+(?:\.\d+)?)\s*([A-Za-z%]+)?", value)
    return (match.group(1), match.group(2) or "") if match else (value, "")


def _clean_value(value: object) -> str:
    text = str(value or "").strip()
    return "" if text.casefold() in _NA_VALUES else text


def _normalize_label(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(label or "").casefold())


def _normalize_label_for_regex(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(label or "").casefold()).strip()


__all__ = [
    "parse_wlan_ap_verbose",
    "parse_wlan_ap_verbose_blocks",
    "parse_wlan_ap_verbose_output",
]
