from __future__ import annotations

import re


def parse_lldp_neighbors(list_output: str, verbose_output: str = "") -> list[dict[str, object | None]]:
    neighbors = _parse_verbose(verbose_output)
    if neighbors:
        return neighbors
    return _parse_list(list_output)


def _parse_list(output: str) -> list[dict[str, object | None]]:
    rows: list[dict[str, object | None]] = []
    for line in (output or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("-") or "Local Interface" in stripped:
            continue
        parts = re.split(r"\s{2,}", stripped)
        if len(parts) >= 3:
            rows.append(
                {
                    "local_interface": parts[0],
                    "neighbor_sysname": parts[1],
                    "neighbor_interface": parts[2],
                    "neighbor_ip": parts[3] if len(parts) >= 4 else None,
                }
            )
    return rows


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
            current = {"local_interface": _normalize_local_interface(line.rsplit(" ", 1)[-1])}
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
        target[field] = match.group(1).strip()


def _normalize_local_interface(value: str) -> str:
    text = value.strip().rstrip(":")
    bracket = re.search(r"\[([^\]]+)\]", text)
    return bracket.group(1).strip() if bracket else text
