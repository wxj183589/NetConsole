from __future__ import annotations

import re

from netconsole.adapters.h3c.h3c_interface_parser import normalize_interface


_LLDP_COLUMNS = (
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
    header_positions: list[tuple[str, int]] | None = None
    legacy_header_positions: tuple[int, int, int, int] | None = None
    lines = (output or "").splitlines()
    has_table_header = _has_chassis_table_header(output)
    has_legacy_header = any(
        "Local Interface" in line and "Neighbor Sysname" in line and "Neighbor Interface" in line and "Management Address" in line
        for line in lines
    )
    for line in lines:
        if _has_chassis_table_header(line):
            header_positions = _scan_lldp_header(line)
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
        # Once a semantic table header is present, a malformed row must not be
        # reinterpreted by the legacy positional fallback.  That fallback is
        # only safe for genuinely headerless historical output.
        if row is None and not has_table_header and not has_legacy_header:
            row = _parse_list_row_fallback(stripped)
        if row:
            rows.append(row)
    return rows


def _has_chassis_table_header(output: str) -> bool:
    return any(
        _scan_lldp_header(line) and {field for field, _ in _scan_lldp_header(line)} >= {"local_interface", "chassis_id", "port_id"}
        for line in (output or "").splitlines()
    )


def _parse_list_row_by_header(line: str, positions: list[tuple[str, int]] | None) -> dict[str, object | None] | None:
    if positions is None:
        return None
    values: dict[str, str] = {}
    for index, (field, start) in enumerate(positions):
        end = positions[index + 1][1] if index + 1 < len(positions) else len(line)
        values[field] = line[start:end].strip()
    local_interface = values.get("local_interface", "")
    neighbor_mac = values.get("chassis_id", "")
    neighbor_interface = values.get("port_id", "")
    if not _is_interface(local_interface) or not _is_mac(neighbor_mac) or not neighbor_interface:
        return None
    return {
        "local_interface": normalize_interface(local_interface),
        "neighbor_mac": neighbor_mac,
        "neighbor_interface": normalize_interface(neighbor_interface),
        "neighbor_sysname": values.get("system_name") or None,
    }


def _scan_lldp_header(line: str) -> list[tuple[str, int]]:
    columns: list[tuple[str, int]] = []
    for field, pattern in _LLDP_COLUMNS:
        match = pattern.search(line)
        if match:
            columns.append((field, match.start()))
    return sorted(columns, key=lambda item: item[1])


def _is_interface(value: object) -> bool:
    return bool(_INTERFACE_RE.fullmatch(re.sub(r"\s+", "", str(value or "").strip())))


def _is_mac(value: object) -> bool:
    compact = re.sub(r"[^0-9a-fA-F]", "", str(value or ""))
    return len(compact) == 12 and bool(re.fullmatch(r"[0-9a-fA-F]{12}", compact))


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
    local_interface = match.group(1)
    neighbor_mac = match.group(2)
    neighbor_interface = match.group(3).strip().split()[0]
    if not _is_interface(local_interface) or not _is_mac(neighbor_mac) or not _is_interface(neighbor_interface):
        return None
    return {
        "local_interface": normalize_interface(local_interface),
        "neighbor_mac": neighbor_mac,
        "neighbor_interface": normalize_interface(neighbor_interface),
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
