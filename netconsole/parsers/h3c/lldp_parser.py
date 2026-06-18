from __future__ import annotations

import re

from netconsole.adapters.h3c.h3c_interface_parser import normalize_interface


def parse_lldp_neighbors(list_output: str, verbose_output: str = "") -> list[dict[str, object | None]]:
    neighbors = _parse_verbose(verbose_output)
    if not _has_chassis_table_header(list_output):
        if neighbors:
            return neighbors
        return _parse_list(list_output)
    list_neighbors = _parse_list(list_output)
    if list_neighbors:
        verbose_by_local = {str(item.get("local_interface") or ""): item for item in neighbors}
        for item in list_neighbors:
            verbose_item = verbose_by_local.get(str(item.get("local_interface") or ""))
            if verbose_item and verbose_item.get("neighbor_ip"):
                item["neighbor_ip"] = verbose_item.get("neighbor_ip")
        return list_neighbors
    if neighbors:
        return neighbors
    return list_neighbors


def _parse_list(output: str) -> list[dict[str, object | None]]:
    rows: list[dict[str, object | None]] = []
    header_positions: tuple[int, int, int, int] | None = None
    legacy_header_positions: tuple[int, int, int, int] | None = None
    lines = (output or "").splitlines()
    has_table_header = _has_chassis_table_header(output)
    has_legacy_header = any(
        "Local Interface" in line and "Neighbor Sysname" in line and "Neighbor Interface" in line and "Management Address" in line
        for line in lines
    )
    for line in lines:
        if "Local Interface" in line and "Chassis ID" in line and "Port ID" in line and "System Name" in line:
            header_positions = (
                line.index("Local Interface"),
                line.index("Chassis ID"),
                line.index("Port ID"),
                line.index("System Name"),
            )
            continue
        if "Local Interface" in line and "Neighbor Sysname" in line and "Neighbor Interface" in line and "Management Address" in line:
            legacy_header_positions = (
                line.index("Local Interface"),
                line.index("Neighbor Sysname"),
                line.index("Neighbor Interface"),
                line.index("Management Address"),
            )
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith("-"):
            continue
        if has_table_header and header_positions is None:
            continue
        if has_legacy_header and legacy_header_positions is None:
            continue
        row = _parse_list_row_by_header(line, header_positions) if header_positions else None
        row = row or (_parse_legacy_list_row_by_header(line, legacy_header_positions) if legacy_header_positions else None)
        row = row or _parse_list_row_fallback(stripped)
        if row:
            rows.append(row)
    return rows


def _has_chassis_table_header(output: str) -> bool:
    return any(
        "Local Interface" in line and "Chassis ID" in line and "Port ID" in line and "System Name" in line
        for line in (output or "").splitlines()
    )


def _parse_list_row_by_header(line: str, positions: tuple[int, int, int, int] | None) -> dict[str, object | None] | None:
    if positions is None:
        return None
    local_start, chassis_start, port_start, system_start = positions
    if len(line) < port_start:
        return None
    local_interface = line[local_start:chassis_start].strip()
    neighbor_mac = line[chassis_start:port_start].strip()
    neighbor_interface = line[port_start:system_start].strip()
    neighbor_sysname = line[system_start:].strip()
    if not local_interface or not neighbor_mac or not neighbor_interface:
        return None
    return {
        "local_interface": normalize_interface(local_interface),
        "neighbor_mac": neighbor_mac,
        "neighbor_interface": normalize_interface(neighbor_interface),
        "neighbor_sysname": neighbor_sysname or None,
    }


def _parse_legacy_list_row_by_header(line: str, positions: tuple[int, int, int, int] | None) -> dict[str, object | None] | None:
    if positions is None:
        return None
    local_start, sysname_start, interface_start, address_start = positions
    local_interface = line[local_start:sysname_start].strip()
    neighbor_sysname = line[sysname_start:interface_start].strip()
    neighbor_interface = line[interface_start:address_start].strip()
    neighbor_ip = line[address_start:].strip()
    if not local_interface or not neighbor_interface:
        return None
    return {
        "local_interface": normalize_interface(local_interface),
        "neighbor_sysname": neighbor_sysname or None,
        "neighbor_interface": normalize_interface(neighbor_interface),
        "neighbor_ip": neighbor_ip or None,
    }


def _parse_list_row_fallback(line: str) -> dict[str, object | None] | None:
    match = re.match(r"^(\S+)\s+(\S+)\s+(.+?)(?:\s{2,}(.+))?$", line)
    if not match:
        return None
    return {
        "local_interface": normalize_interface(match.group(1)),
        "neighbor_mac": match.group(2),
        "neighbor_interface": normalize_interface(match.group(3).strip()),
        "neighbor_sysname": (match.group(4) or "").strip() or None,
    }


def _parse_verbose(output: str) -> list[dict[str, object | None]]:
    rows: list[dict[str, object | None]] = []
    current: dict[str, object | None] = {}
    for raw_line in (output or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("LLDP neighbor-information of port"):
            if current.get("local_interface"):
                rows.append(current)
            current = {"local_interface": normalize_interface(_normalize_local_interface(line.rsplit(" ", 1)[-1]))}
            continue
        _set_if_match(current, "neighbor_sysname", line, r"(?i)System name\s*[:：]\s*(.+)")
        _set_if_match(current, "neighbor_mac", line, r"(?i)(?:Chassis ID|MAC address)\s*[:：]\s*(.+)")
        _set_if_match(current, "neighbor_interface", line, r"(?i)Port ID\s*[:：]\s*(.+)")
        _set_if_match(current, "neighbor_ip", line, r"(?i)(?:Management address|Management address value)\s*[:：]\s*(.+)")
    if current.get("local_interface"):
        rows.append(current)
    return rows


def _set_if_match(target: dict[str, object | None], field: str, text: str, pattern: str) -> None:
    match = re.search(pattern, text)
    if match:
        value = match.group(1).strip()
        target[field] = normalize_interface(value) if field == "neighbor_interface" else value


def _normalize_local_interface(value: str) -> str:
    text = value.strip().rstrip(":")
    bracket = re.search(r"\[([^\]]+)\]", text)
    return bracket.group(1).strip() if bracket else text
