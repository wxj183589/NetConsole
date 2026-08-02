from __future__ import annotations

import re

from netconsole.services.fit_ap_link_info import format_h3c_mac, normalize_interface_key
from netconsole.utils.interface_normalize import normalize_interface_name


MAC_RE = re.compile(r"\b(?:[0-9a-f]{4}[-.:]){2}[0-9a-f]{4}\b|\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b|\b[0-9a-f]{12}\b", re.IGNORECASE)
_TABLE_COLUMNS = (
    ("system_name", re.compile(r"(?i)system\s+name")),
    ("local_interface", re.compile(r"(?i)local\s+interface")),
    ("chassis_id", re.compile(r"(?i)chassis\s+id")),
    ("port_id", re.compile(r"(?i)port\s+id")),
)
_INTERFACE_RE = re.compile(
    r"(?i)^(?:ge|gigabitethernet|xge|xgigabitethernet|"
    r"ten-gigabitethernet|tengigabitethernet|sge|"
    r"fortygigabitethernet|hundredgigabitethernet)\s*\d+(?:/\d+){1,3}$"
)


def parse_fit_ap_lldp_neighbors(output: str) -> list[dict[str, object | None]]:
    rows: list[dict[str, object | None]] = []
    in_table = False
    header: list[tuple[str, int]] | None = None
    for line in (output or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("<", "-", "=")):
            continue
        lower = stripped.casefold()
        if lower.startswith(("chassis id :", "# --", "default --")):
            continue
        candidate_header = _scan_table_header(line)
        if _is_supported_table_header(candidate_header):
            in_table = True
            header = candidate_header
            continue
        if not in_table:
            continue
        if header:
            row = _parse_table_row(line, header)
            if row is not None:
                rows.append(row)
            continue
        mac_match = MAC_RE.search(stripped)
        if not mac_match:
            continue
        row = _parse_unheaded_row(stripped, mac_match)
        if row is not None:
            rows.append(row)
    return rows


def _scan_table_header(line: str) -> list[tuple[str, int]]:
    columns: list[tuple[str, int]] = []
    for field, pattern in _TABLE_COLUMNS:
        match = pattern.search(line)
        if match:
            columns.append((field, match.start()))
    return sorted(columns, key=lambda item: item[1])


def _is_supported_table_header(columns: list[tuple[str, int]]) -> bool:
    return len(columns) >= 3 and {field for field, _ in columns} >= {
        "local_interface",
        "chassis_id",
        "port_id",
    }


def has_fit_ap_lldp_table_header(output: str) -> bool:
    """Return whether the output contains a supported direct-LLDP table header."""
    return any(
        _is_supported_table_header(_scan_table_header(line))
        for line in (output or "").splitlines()
    )


def _parse_table_row(line: str, header: list[tuple[str, int]]) -> dict[str, object | None] | None:
    if len(header) < 3:
        return None
    values: dict[str, str] = {}
    for index, (field, start) in enumerate(header):
        end = header[index + 1][1] if index + 1 < len(header) else len(line)
        values[field] = line[start:end].strip()
    local_interface = values.get("local_interface", "")
    neighbor_mac = values.get("chassis_id", "")
    neighbor_interface = values.get("port_id", "")
    if _is_interface(local_interface) and _normalize_mac_value(neighbor_mac) and neighbor_interface and not _is_generic_port_value(neighbor_interface):
        return _row(
            local_interface=local_interface,
            neighbor_mac=neighbor_mac,
            neighbor_interface=neighbor_interface,
            neighbor_name=values.get("system_name", ""),
        )

    # Some AC versions print the row with single spaces, so header character
    # offsets do not line up with the row. Reuse the semantic MAC/interface
    # parser instead of trusting those offsets.
    mac_match = MAC_RE.search(line.strip())
    return _parse_unheaded_row(line.strip(), mac_match) if mac_match else None


def _parse_unheaded_row(line: str, mac_match: re.Match[str]) -> dict[str, object | None] | None:
    before = line[: mac_match.start()].strip()
    after = line[mac_match.end() :].strip()
    before_parts = before.split()
    after_parts = after.split()
    if not before_parts or not after_parts:
        return None
    local_index = next((index for index in range(len(before_parts) - 1, -1, -1) if _is_interface(before_parts[index])), -1)
    if local_index < 0:
        return None
    local_interface = before_parts[local_index]
    neighbor_name = " ".join(before_parts[:local_index]).strip()
    neighbor_interface = after_parts[0]
    if _is_generic_port_value(neighbor_interface):
        return None
    if not _is_interface(neighbor_interface):
        return None
    if not neighbor_name and len(after_parts) > 1:
        neighbor_name = " ".join(after_parts[1:]).strip()
    return _row(
        local_interface=local_interface,
        neighbor_mac=mac_match.group(0),
        neighbor_interface=neighbor_interface,
        neighbor_name=neighbor_name,
    )


def _row(*, local_interface: str, neighbor_mac: str, neighbor_interface: str, neighbor_name: str) -> dict[str, object | None]:
    normalized_mac = _normalize_mac_value(neighbor_mac)
    return {
        "lldp_neighbor_name": neighbor_name.strip() or None,
        "lldp_local_interface": normalize_interface_name(local_interface),
        "lldp_local_interface_normalized": normalize_interface_key(local_interface),
        "lldp_neighbor_mac": format_h3c_mac(neighbor_mac) or neighbor_mac.strip(),
        "lldp_neighbor_mac_normalized": normalized_mac,
        "lldp_neighbor_interface": normalize_interface_name(neighbor_interface),
        "lldp_source": "ap_direct_lldp",
    }


def _normalize_mac_value(value: object) -> str:
    return re.sub(r"[^0-9a-fA-F]", "", str(value or "")).casefold() if len(re.sub(r"[^0-9a-fA-F]", "", str(value or ""))) == 12 else ""


def _is_interface(value: object) -> bool:
    return bool(_INTERFACE_RE.fullmatch(re.sub(r"\s+", "", str(value or "").strip())))


def _is_generic_port_value(value: object) -> bool:
    return str(value or "").strip().casefold() in {"h3c", "comware", "switch", "unknown", "n/a", "na", "-"}


def parse_fit_ap_lldp_neighbor(output: str, preferred_interface: object = None) -> dict[str, object | None]:
    rows = parse_fit_ap_lldp_neighbors(output)
    preferred_key = normalize_interface_key(preferred_interface)
    if preferred_key:
        for row in rows:
            if row.get("lldp_local_interface_normalized") == preferred_key:
                return row
    return rows[0] if rows else {
        "lldp_neighbor_name": None,
        "lldp_local_interface": None,
        "lldp_local_interface_normalized": None,
        "lldp_neighbor_mac": None,
        "lldp_neighbor_mac_normalized": None,
        "lldp_neighbor_interface": None,
        "lldp_source": "ap_direct_lldp",
    }
