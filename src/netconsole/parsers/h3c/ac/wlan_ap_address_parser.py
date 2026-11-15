from __future__ import annotations

import re


IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
MAC_RE = re.compile(
    r"\b(?:[0-9a-f]{4}[-:.]){2}[0-9a-f]{4}\b|"
    r"\b(?:[0-9a-f]{2}[-:.]){5}[0-9a-f]{2}\b",
    re.IGNORECASE,
)
_NA_RE = re.compile(r"^(?:-NA-|NA|N/A|NONE|NULL|UNKNOWN|-)\s*$", re.IGNORECASE)
_HEADER_RE = re.compile(r"\b(?:ap\s+name|apname)\b.*\b(?:ip\s+address|ip)\b", re.IGNORECASE)


def parse_wlan_ap_addresses(output: str) -> dict[str, dict[str, object | None]]:
    rows: dict[str, dict[str, object | None]] = {}
    for line in output.splitlines():
        stripped = line.strip()
        if _is_noise_line(stripped):
            continue
        fields = _split_columns(stripped)
        if len(fields) >= 3:
            ap_name = fields[0].strip()
            ip_value = fields[1].strip()
            mac_value = fields[2].strip()
        else:
            ap_name, ip_value, mac_value = _parse_token_columns(stripped)
        if not ap_name or (not ip_value and not mac_value):
            continue
        rows[ap_name] = {
            "ap_name": ap_name,
            "ap_ip": _value_or_none(ip_value, is_ip=True),
            "ap_mac": _value_or_none(mac_value, is_ip=False),
            "address_observed": True,
            "raw_address_line": stripped,
        }
    return rows


def _is_noise_line(stripped: str) -> bool:
    lower = stripped.casefold()
    return (
        not stripped
        or stripped.startswith(("=", "<"))
        or lower.startswith(("total ", "number of ", "ap name", "apname"))
        or "ip address" in lower and "mac address" in lower
        or bool(re.fullmatch(r"[-=\s]+", stripped))
    )


def _split_columns(stripped: str) -> list[str]:
    return [part.strip() for part in re.split(r"\s{2,}|\t+", stripped) if part.strip()]


def _parse_token_columns(stripped: str) -> tuple[str, str, str]:
    tokens = stripped.split()
    if len(tokens) < 2:
        return "", "", ""
    ip_index = next(
        (index for index, token in enumerate(tokens[1:], start=1) if _is_ip(token) or _is_na(token)),
        -1,
    )
    mac_index = next(
        (index for index, token in enumerate(tokens[1:], start=1) if _is_mac(token) or _is_na(token)),
        -1,
    )
    indexes = [index for index in (ip_index, mac_index) if index >= 1]
    if not indexes:
        return "", "", ""
    first_value = min(indexes)
    ap_name = " ".join(tokens[:first_value]).strip()
    ip_value = tokens[ip_index] if ip_index >= 0 else ""
    mac_value = tokens[mac_index] if mac_index >= 0 else ""
    return ap_name, ip_value, mac_value


def _is_ip(value: str) -> bool:
    return bool(IP_RE.fullmatch(value))


def _is_mac(value: str) -> bool:
    return bool(MAC_RE.fullmatch(value))


def _is_na(value: str) -> bool:
    return bool(_NA_RE.fullmatch(value))


def _value_or_none(value: str, *, is_ip: bool) -> str | None:
    value = value.strip()
    if not value or _is_na(value):
        return None
    if is_ip:
        return value if _is_ip(value) else None
    return value if _is_mac(value) else None
