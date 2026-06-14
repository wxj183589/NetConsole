from __future__ import annotations

import re


INTERFACE_NAME = r"(?:[A-Za-z][A-Za-z-]*Ethernet|FortyGigE|Ten-GigabitEthernet|Twenty-FiveGigE|HundredGigE|GigabitEthernet)[\d/.:]+|Vlan-interface\d+|Bridge-Aggregation\d+|LoopBack\d+"
INTERFACE_HEADER = re.compile(rf"^({INTERFACE_NAME})\s+current state:\s+(.+)$", re.IGNORECASE)
INTERFACE_NAME_ONLY = re.compile(rf"^({INTERFACE_NAME})$", re.IGNORECASE)


def parse_interfaces(output: str) -> list[dict[str, object | None]]:
    interfaces: list[dict[str, object | None]] = []
    current: dict[str, object | None] | None = None
    pending_name: str | None = None
    for raw_line in (output or "").splitlines():
        line = raw_line.rstrip()
        header = INTERFACE_HEADER.match(line.strip())
        if header:
            if current:
                interfaces.append(_finalize_interface(current))
            current = {
                "interface_name": header.group(1),
                "link_status": header.group(2).strip(),
            }
            pending_name = None
            continue
        name_only = INTERFACE_NAME_ONLY.match(line.strip())
        if name_only:
            if current:
                interfaces.append(_finalize_interface(current))
            pending_name = name_only.group(1)
            current = None
            continue
        if pending_name and line.strip().lower().startswith("current state:"):
            current = {
                "interface_name": pending_name,
                "link_status": line.split(":", 1)[1].strip(),
            }
            pending_name = None
            continue
        if current is None:
            continue
        stripped = line.strip()
        if stripped.startswith("Line protocol current state:") or stripped.startswith("Line protocol state:"):
            current["protocol_status"] = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("Description:"):
            current["description"] = stripped.split(":", 1)[1].strip()
        elif stripped.lower().startswith("internet address"):
            address = _parse_internet_address(stripped)
            if address:
                current.setdefault("_ip_candidates", []).append(address)
        elif stripped.lower().startswith("ip packet frame type:"):
            mac = re.search(r"hardware address:\s*([0-9A-Fa-f.-]+)", stripped, re.IGNORECASE)
            if mac:
                current["mac_address"] = mac.group(1)
        elif stripped.startswith("PVID:"):
            current["pvid"] = stripped.split(":", 1)[1].strip()
            current["_has_l2"] = True
        elif stripped.startswith("Port link-type:"):
            current["_link_type"] = stripped.split(":", 1)[1].strip().lower()
            current["_has_l2"] = True
        elif _is_vlan_line(stripped):
            current.setdefault("_vlan_lines", []).append(stripped)
            current["_has_l2"] = True
        elif stripped.startswith("The Maximum Transmit Unit"):
            pass
        elif "Media type is" in stripped:
            pass
        elif stripped.startswith("Speed :"):
            current["speed"] = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("Duplex:"):
            current["duplex"] = stripped.split(":", 1)[1].strip()
        else:
            speed_duplex = re.search(r"([0-9]+[GMK]?bps)-speed mode,\s*([A-Za-z-]+)-duplex mode", stripped, re.IGNORECASE)
            if speed_duplex:
                current["speed"] = speed_duplex.group(1)
                current["duplex"] = speed_duplex.group(2)
    if current:
        interfaces.append(_finalize_interface(current))
    return interfaces


def _parse_internet_address(line: str) -> dict[str, object] | None:
    match = re.search(r"(?i)internet address(?: is)?\s*:\s*([0-9a-fA-F:.]+/\d+)\s*(.*)$", line)
    if not match:
        match = re.search(r"(?i)internet address is\s+([0-9a-fA-F:.]+/\d+)\s*(.*)$", line)
    if not match:
        return None
    suffix = match.group(2) or ""
    return {"value": match.group(1), "primary": "primary" in suffix.lower()}


def _is_vlan_line(line: str) -> bool:
    lowered = line.lower()
    return lowered.startswith(("tagged vlans:", "untagged vlans:", "vlan passing", "vlan permitted"))


def _finalize_interface(item: dict[str, object | None]) -> dict[str, object | None]:
    ip_candidates = item.pop("_ip_candidates", []) or []
    vlan_lines = item.pop("_vlan_lines", []) or []
    has_l2 = bool(item.pop("_has_l2", False))
    link_type = str(item.pop("_link_type", "") or "").strip().lower()
    if ip_candidates:
        primary = next((candidate for candidate in ip_candidates if candidate.get("primary")), ip_candidates[0])
        item["ip_address"] = primary.get("value")
        item["interface_type"] = "三层"
    elif has_l2:
        item["interface_type"] = "二层"
    if vlan_lines:
        item["vlan"] = "\n".join(vlan_lines)
    link_state = str(item.get("link_status") or "").lower()
    description = str(item.get("description") or "").lower()
    if "administratively down" in link_state or "shutdown" in description:
        item["port_status"] = "shutdown"
    elif item.get("interface_type") == "三层":
        item["port_status"] = "route"
    elif link_type in {"access", "hybrid", "trunk"}:
        item["port_status"] = link_type
    return item
